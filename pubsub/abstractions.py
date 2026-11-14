"""Platform abstraction utilities for the pubsub library."""

import errno
import os
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from .message import CHANNEL_ENTRY_MAX_LENGTH

T = TypeVar("T")

# Cache for the base directory to avoid repeated lookups
_base_dir_cache = None

# Windows without long path support limits a path to 259 characters (MAX_PATH is 260,
# including the terminating null character).
WINDOWS_MAX_PATH = 260

# Length of the random token prefixing the name of a channel directory being purged
PURGE_TOKEN_LENGTH = 8

# Win32 constants used to check whether a process is running
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5
_ERROR_FILENAME_EXCED_RANGE = 206

_long_paths_cache: bool | None = None
_kernel32_cache = None


def _is_windows() -> bool:
    """Tell whether pubsub is running on Windows."""
    return sys.platform == "win32"


def get_base_dir() -> Path:
    """
    Get the base directory for pubsub storage that works across platforms.

    First checks for the PUBSUB_HOME environment variable. If not set,
    uses the system's temporary directory with a 'pubsub' subdirectory.
    On Linux, prefers /dev/shm if available for better performance.

    The result is cached after the first call for performance.

    Returns:
        Path: The base directory path for pubsub storage
    """
    global _base_dir_cache
    if _base_dir_cache is not None:
        return _base_dir_cache

    env_dir = os.environ.get("PUBSUB_HOME")
    if env_dir:
        _base_dir_cache = Path(env_dir)
        return _base_dir_cache

    shm_path = Path("/dev/shm")
    if shm_path.exists() and shm_path.is_dir():
        temp_dir = shm_path
    else:
        temp_dir = Path(tempfile.gettempdir())

    # Append pubsub subdirectory
    _base_dir_cache = temp_dir / "pubsub"
    return _base_dir_cache


def get_tmp_dir() -> Path:
    """Directory where publishers stage a message file before linking it into channels."""
    return get_base_dir() / "tmp"


def get_purge_dir() -> Path:
    """Directory where closed channels are moved while their content is deleted."""
    return get_base_dir() / "purge"


def retry_fs(operation: Callable[[], T], attempts: int = 5, delay: float = 0.005) -> T:
    """
    Run a file system operation, retrying it on Windows when it fails with PermissionError.

    On Windows, a file or directory that is briefly open elsewhere (another process reading
    it, an antivirus or an indexer) cannot be deleted or renamed. Such a failure is usually
    gone a few milliseconds later. On other platforms PermissionError is a real error and
    the operation is run once.

    Args:
        operation: The operation to run, without arguments
        attempts: Maximum number of attempts on Windows
        delay: Seconds to wait between two attempts

    Returns:
        The value returned by the operation

    Raises:
        PermissionError: If the operation still fails after the last attempt
        OSError: Any other error raised by the operation
    """
    if not _is_windows():
        return operation()
    for attempt in range(attempts):
        try:
            return operation()
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def _windows_kernel32():
    """Load kernel32 with the signatures of the functions pubsub uses (cached)."""
    global _kernel32_cache
    if _kernel32_cache is None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        _kernel32_cache = kernel32
    return _kernel32_cache


def _is_process_running_windows(pid: int, kernel32=None, get_last_error=None) -> bool:
    """
    Check a process on Windows.

    A process the caller may not query (another user, elevated) is reported as running,
    because failing to open it proves nothing about whether it exists. A process that has
    exited but whose handle is still held by someone else is reported as not running.

    Args:
        pid: The process id
        kernel32: Object exposing OpenProcess, GetExitCodeProcess and CloseHandle (injectable)
        get_last_error: Function returning the last Win32 error (injectable)
    """
    import ctypes

    if kernel32 is None:
        kernel32 = _windows_kernel32()
    if get_last_error is None:
        get_last_error = ctypes.get_last_error
    try:
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except (OverflowError, ctypes.ArgumentError):
        return False
    if not handle:
        return get_last_error() == _ERROR_ACCESS_DENIED
    try:
        exit_code = ctypes.c_uint32()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True  # cannot tell: assume it is running
        return exit_code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def is_process_running(pid: int) -> bool:
    """
    Check if a process with the given PID is currently running.

    Works across different operating systems:
    - Unix-like (Linux, macOS, BSD): Uses os.kill(pid, 0) to check existence. A process
      that exists but belongs to another user (PermissionError) is running.
    - Windows: Uses OpenProcess and GetExitCodeProcess via ctypes. A process that cannot be
      queried because access is denied is running.

    Args:
        pid: The process ID to check

    Returns:
        True if the process is running, False otherwise
    """
    if pid <= 0:
        return False

    if _is_windows():
        return _is_process_running_windows(pid)

    try:
        # Signal 0 doesn't send a signal but checks if the process exists
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


def _read_long_paths_setting() -> bool:
    """Read the Windows LongPathsEnabled registry value (False if unreadable)."""
    if not _is_windows():
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
        return value == 1
    except (OSError, ImportError):
        return False


def windows_long_paths_enabled() -> bool:
    """
    Tell whether Windows long paths are enabled (the LongPathsEnabled registry value is 1).

    The value is read once and cached. It is False on other platforms and when the
    registry value cannot be read.
    """
    global _long_paths_cache
    if _long_paths_cache is None:
        _long_paths_cache = _read_long_paths_setting()
    return _long_paths_cache


def longest_channel_path_length(base_dir: Path | str, directory_name: str) -> int:
    """
    Length of the longest path pubsub creates for a channel.

    That is a message file inside the channel directory while it is being purged:
    <base>\\purge\\<token>_<directory_name>\\<longest entry of a channel>

    The longest entry of a channel is a locked message file (``<id>.locked``) or a message
    in the poison folder (``poison\\<id>``), 27 characters.
    """
    return (
        len(str(base_dir))
        + len("\\purge\\")
        + PURGE_TOKEN_LENGTH
        + 1
        + len(directory_name)
        + 1
        + CHANNEL_ENTRY_MAX_LENGTH
    )


def _path_too_long_error(length: int | None) -> OSError:
    """Build the error telling how to cope with the Windows path length limit."""
    if length is None:
        problem = "A path pubsub needs is too long for Windows."
    else:
        problem = (
            f"The longest path pubsub would create is {length} characters, but Windows "
            f"limits paths to {WINDOWS_MAX_PATH - 1} characters (MAX_PATH)."
        )
    return OSError(
        errno.ENAMETOOLONG,
        f"{problem} Use a shorter topic or a shorter PUBSUB_HOME, or remove the Windows "
        "path length limitation: re-run the Python installer (Modify) and tick 'Disable "
        "path length limit', or set the registry value "
        "HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem\\LongPathsEnabled to 1 "
        "(administrator rights, Windows 10 version 1607 or later), then restart the "
        "application.",
    )


def check_windows_path_length(
    base_dir: Path | str,
    directory_name: str,
    windows: bool | None = None,
    long_paths: bool | None = None,
) -> None:
    """
    Raise an error if a channel would need a path that Windows cannot handle.

    Does nothing on other platforms, or on Windows when long paths are enabled.

    Args:
        base_dir: The pubsub base directory
        directory_name: The channel directory name
        windows: Override of the platform detection (for tests)
        long_paths: Override of the long path detection (for tests)

    Raises:
        OSError: With errno ENAMETOOLONG, if the longest path reaches MAX_PATH
    """
    if windows is None:
        windows = _is_windows()
    if not windows:
        return
    if long_paths is None:
        long_paths = windows_long_paths_enabled()
    if long_paths:
        return
    length = longest_channel_path_length(base_dir, directory_name)
    if length >= WINDOWS_MAX_PATH:
        raise _path_too_long_error(length)


def raise_if_path_too_long(error: OSError) -> None:
    """
    Re-raise an OS error as the path length error if Windows reported ERROR_FILENAME_EXCED_RANGE.

    Does nothing for any other error, so it can be called on every OSError.
    """
    if getattr(error, "winerror", None) == _ERROR_FILENAME_EXCED_RANGE:
        raise _path_too_long_error(None) from error
