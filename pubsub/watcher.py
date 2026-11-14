"""Directory change notification used by the subscribe loop to avoid busy waiting.

A watcher tells the subscriber, as soon as the operating system reports it, that something
changed in the channel directory. A notification is only a hint: the subscriber always
rescans the directory after a wake-up, so a missed, merged or spurious event costs at most
one wait timeout and never a message.

Implementations:

- Linux: inotify, through ctypes (one inotify instance shared by the whole process)
- macOS and BSD: kqueue (``select.kqueue``)
- Windows: FindFirstChangeNotification, through ctypes
- Anywhere else, or when the native watcher cannot be created: adaptive polling

Set the ``PUBSUB_WATCHER`` environment variable to ``poll`` to force the polling fallback.
"""

import logging
import os
import select
import struct
import sys
import threading
import time
from pathlib import Path


class DirWatcher:
    """Base class of the directory watchers."""

    # Longest time a single wait should last. It keeps the subscriber able to react to
    # signals and to events the system did not report.
    max_wait: float = 0.1

    def wait(self, timeout: float) -> None:
        """
        Block until the directory may have changed, or until the timeout elapses.

        Args:
            timeout: Maximum number of seconds to wait
        """
        raise NotImplementedError

    def activity(self) -> None:
        """Tell the watcher that a message was just received (resets any backoff)."""

    def close(self) -> None:
        """Release the resources held by the watcher."""


class PollingWatcher(DirWatcher):
    """Fallback watcher: sleeps for a growing interval while nothing happens."""

    INTERVALS = (0.001, 0.002, 0.005, 0.010, 0.025, 0.050)
    max_wait = INTERVALS[-1]

    def __init__(self) -> None:
        self._step = 0

    def wait(self, timeout: float) -> None:
        interval = self.INTERVALS[min(self._step, len(self.INTERVALS) - 1)]
        self._step += 1
        if timeout > 0:
            time.sleep(min(interval, timeout))

    def activity(self) -> None:
        self._step = 0


# ---------------------------------------------------------------------------------------
# Linux: inotify
# ---------------------------------------------------------------------------------------

_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE_SELF = 0x00000400
_IN_Q_OVERFLOW = 0x00004000
_IN_IGNORED = 0x00008000
_IN_NONBLOCK = os.O_NONBLOCK
_IN_CLOEXEC = getattr(os, "O_CLOEXEC", 0o2000000)
_INOTIFY_EVENT_HEADER = struct.Struct("iIII")


class _InotifyHub:
    """
    One inotify instance shared by every watcher of the process.

    Linux limits the number of inotify instances per user (128 by default), so channels
    share one. Several threads may wait at the same time: one of them reads the instance
    and records which watches fired, the others wait to be told.
    """

    def __init__(self) -> None:
        import ctypes
        import ctypes.util

        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        self._ctypes = ctypes
        self._libc = libc
        self._libc.inotify_init1.argtypes = [ctypes.c_int]
        self._libc.inotify_init1.restype = ctypes.c_int
        self._libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self._libc.inotify_add_watch.restype = ctypes.c_int
        self._libc.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
        self._libc.inotify_rm_watch.restype = ctypes.c_int
        fd = self._libc.inotify_init1(_IN_NONBLOCK | _IN_CLOEXEC)
        if fd < 0:
            errno_value = ctypes.get_errno()
            raise OSError(errno_value, os.strerror(errno_value))
        self.pid = os.getpid()
        self._fd = fd
        self._cond = threading.Condition()
        self._reader_active = False
        self._watched: set[int] = set()
        self._dirty: set[int] = set()

    def add_watch(self, path: Path) -> int:
        wd = self._libc.inotify_add_watch(
            self._fd, os.fsencode(str(path)), _IN_CREATE | _IN_MOVED_TO | _IN_DELETE_SELF
        )
        if wd < 0:
            errno_value = self._ctypes.get_errno()
            raise OSError(errno_value, os.strerror(errno_value), str(path))
        with self._cond:
            self._watched.add(wd)
            self._dirty.discard(wd)
        return wd

    def remove_watch(self, wd: int) -> None:
        with self._cond:
            self._watched.discard(wd)
            self._dirty.discard(wd)
        # Fails with EINVAL if the kernel already dropped the watch (directory deleted)
        self._libc.inotify_rm_watch(self._fd, wd)

    def wait(self, wd: int, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            with self._cond:
                if wd in self._dirty:
                    self._dirty.discard(wd)
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                if self._reader_active:
                    self._cond.wait(remaining)
                    continue
                self._reader_active = True
            data = b""
            try:
                ready, _, _ = select.select([self._fd], [], [], remaining)
                if ready:
                    try:
                        data = os.read(self._fd, 65536)
                    except BlockingIOError:
                        data = b""
            finally:
                with self._cond:
                    self._reader_active = False
                    self._record(data)
                    self._cond.notify_all()

    def _record(self, data: bytes) -> None:
        """Mark as dirty the watches named by the raw events. Caller holds the lock."""
        offset = 0
        size = _INOTIFY_EVENT_HEADER.size
        while offset + size <= len(data):
            wd, mask, _cookie, length = _INOTIFY_EVENT_HEADER.unpack_from(data, offset)
            offset += size + length
            if mask & _IN_Q_OVERFLOW:
                self._dirty.update(self._watched)  # events were lost: wake everybody up
            elif wd in self._watched:
                self._dirty.add(wd)
                if mask & _IN_IGNORED:
                    self._watched.discard(wd)

    def close(self) -> None:
        try:
            os.close(self._fd)
        except OSError:
            pass


_hub: _InotifyHub | None = None
_hub_lock = threading.Lock()


def _get_hub() -> _InotifyHub:
    """Return the process's inotify hub, creating it (again after a fork)."""
    global _hub
    with _hub_lock:
        if _hub is not None and _hub.pid != os.getpid():
            # Inherited from the parent process: it is not ours to share
            _hub.close()
            _hub = None
        if _hub is None:
            _hub = _InotifyHub()
        return _hub


class InotifyWatcher(DirWatcher):
    """Wakes up when a file is created in, or moved into, the watched directory."""

    def __init__(self, path: Path) -> None:
        self._hub = _get_hub()
        self._wd = self._hub.add_watch(path)
        self._closed = False

    def wait(self, timeout: float) -> None:
        if self._closed:
            time.sleep(min(timeout, 0.001))
            return
        self._hub.wait(self._wd, timeout)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._hub.remove_watch(self._wd)


# ---------------------------------------------------------------------------------------
# macOS and BSD: kqueue
# ---------------------------------------------------------------------------------------


class KqueueWatcher(DirWatcher):
    """Wakes up when entries are added to, or removed from, the watched directory."""

    def __init__(self, path: Path) -> None:
        self._fd = os.open(str(path), os.O_RDONLY)
        try:
            self._kq = select.kqueue()
            event = select.kevent(
                self._fd,
                filter=select.KQ_FILTER_VNODE,
                flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND,
            )
            self._kq.control([event], 0, 0)
        except BaseException:
            os.close(self._fd)
            raise
        self._closed = False

    def wait(self, timeout: float) -> None:
        if self._closed:
            time.sleep(min(timeout, 0.001))
            return
        self._kq.control(None, 1, max(timeout, 0))

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._kq.close()
            os.close(self._fd)


# ---------------------------------------------------------------------------------------
# Windows: FindFirstChangeNotification
# ---------------------------------------------------------------------------------------

_FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
_WAIT_OBJECT_0 = 0
_WAIT_FAILED = 0xFFFFFFFF


class WindowsChangeWatcher(DirWatcher):
    """Wakes up when a file is created, renamed or deleted in the watched directory."""

    def __init__(self, path: Path) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.FindFirstChangeNotificationW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.FindFirstChangeNotificationW.restype = wintypes.HANDLE
        kernel32.FindNextChangeNotification.argtypes = [wintypes.HANDLE]
        kernel32.FindNextChangeNotification.restype = wintypes.BOOL
        kernel32.FindCloseChangeNotification.argtypes = [wintypes.HANDLE]
        kernel32.FindCloseChangeNotification.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self._kernel32 = kernel32
        handle = kernel32.FindFirstChangeNotificationW(
            str(path), False, _FILE_NOTIFY_CHANGE_FILE_NAME
        )
        if handle is None or handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle = handle
        self._closed = False

    def wait(self, timeout: float) -> None:
        if self._closed:
            time.sleep(min(timeout, 0.001))
            return
        milliseconds = max(1, int(timeout * 1000 + 0.999))
        result = self._kernel32.WaitForSingleObject(self._handle, milliseconds)
        if result == _WAIT_OBJECT_0:
            self._kernel32.FindNextChangeNotification(self._handle)  # re-arm
        elif result == _WAIT_FAILED:
            time.sleep(min(timeout, 0.01))  # never spin if the handle is unusable

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._kernel32.FindCloseChangeNotification(self._handle)


def create_watcher(path: Path) -> DirWatcher:
    """
    Create the best watcher available for a directory.

    Falls back to polling when the native mechanism is missing or cannot be set up (for
    example when the inotify watch limit is reached), or when PUBSUB_WATCHER is "poll".

    Args:
        path: The directory to watch
    """
    if os.environ.get("PUBSUB_WATCHER", "").strip().lower() in ("poll", "polling"):
        return PollingWatcher()
    try:
        if sys.platform.startswith("linux"):
            return InotifyWatcher(path)
        if hasattr(select, "kqueue"):
            return KqueueWatcher(path)
        if sys.platform == "win32":
            return WindowsChangeWatcher(path)
    except Exception as e:  # any failure here must leave the subscriber working
        logging.debug("Native directory watcher unavailable for %s (%s): polling instead.", path, e)
    return PollingWatcher()
