"""Channel class for pubsub system: a directory of message files per subscriber."""

import logging
import os
import random
import re
import string
import threading
import time
from functools import partial
from pathlib import Path

from .abstractions import (
    PURGE_TOKEN_LENGTH,
    check_windows_path_length,
    get_base_dir,
    get_purge_dir,
    get_tmp_dir,
    is_process_running,
    raise_if_path_too_long,
    retry_fs,
)
from .message import (
    LOCKED_SUFFIX,
    POISON_DIRECTORY,
    Message,
    is_message_file_name,
    message_id_time_ms,
)

# Temporary message files older than this are leftovers of a publisher that died
STALE_TMP_SECONDS = 3600


class Channel:
    """
    Represents a pubsub channel: a directory of message files.

    Opening the channel creates a directory in the pubsub base directory with format:
    {topic}_{random_12_chars}_{process_id}
    Publishers link one file per message into it, named after the message id (zero-padded
    to 20 digits). The directory exists only while the channel is open, and its existence
    is what tells publishers that the channel is listening. Closing the channel moves the
    directory to the purge directory and deletes it there.

    Topic format supports wildcards:
    - '=' for single word wildcard
    - '+' for multiple words wildcard

    A channel has a single consumer: while a ``subscribe`` is listening on it, a second
    ``subscribe`` or a direct ``fetch`` raises a RuntimeError.
    """

    def __init__(self, topic: str):
        """
        Initialize a new channel. Nothing is created on disk until the channel is opened.

        Args:
            topic: The topic string (dot-separated terms with optional wildcards)

        Raises:
            ValueError: If topic contains invalid characters
            OSError: On Windows, with errno ENAMETOOLONG, if the channel would need a path
                longer than Windows allows (and Windows long paths are not enabled)
        """
        self._validate_topic_pattern(topic)
        self.topic = topic
        self.process_id = os.getpid()
        self.random_id = self._generate_random_id()
        self.directory_name = f"{topic}_{self.random_id}_{self.process_id}"
        self.directory_path = get_base_dir() / self.directory_name
        check_windows_path_length(get_base_dir(), self.directory_name)

        self._open = False
        # Guards the pending list and the subscription flag. It is never held while a
        # subscriber callback runs.
        self._lock = threading.Lock()
        self._subscribed = False
        # Message file names found by the last directory listing, largest first, so that
        # pop() yields the smallest id. The directory is listed again only when empty.
        self._pending: list[str] = []

    @property
    def is_open(self) -> bool:
        """Check if the channel is currently open (its directory exists)."""
        return self._open

    @property
    def poison_path(self) -> Path:
        """
        Directory where the messages rejected as poison are moved (see ``cancel_read_message``).

        It is created the first time a message is moved there, and is deleted with the
        rest of the channel when the channel is closed, so whoever handles the poison
        messages must do it before then. Each message is a file named after its id and can
        be read with ``Message.read`` or ``Message.from_bytes``.
        """
        return self.directory_path / POISON_DIRECTORY

    @property
    def is_subscribed(self) -> bool:
        """Check if a subscribe is currently listening on the channel."""
        return self._subscribed

    def begin_subscription(self) -> None:
        """
        Register the caller as the channel's single listener.

        Called by ``subscribe`` before it starts listening. Until ``end_subscription`` is
        called, no other listener can be registered and ``begin_read_message`` refuses direct
        (non-subscribed) use.

        Raises:
            RuntimeError: If the channel is not open, or already has a listener
        """
        with self._lock:
            if not self._open:
                raise RuntimeError("Channel must be open to subscribe")
            if self._subscribed:
                raise RuntimeError("Channel is already being listened to by another subscribe()")
            self._subscribed = True

    def end_subscription(self) -> None:
        """Unregister the listener registered by ``begin_subscription``."""
        with self._lock:
            self._subscribed = False

    def begin_read_message(self, subscribed: bool = False) -> Message | None:
        """
        Start reading the next message waiting in the channel.

        Messages are handed out in id order, each one once. The channel directory is listed
        only when the messages found by the previous listing have all been handed out, so a
        message that arrives meanwhile is handed out after them, by a later call.

        The message file is first claimed by renaming it with the ``.locked`` suffix. The
        rename is atomic, so only one reader gets a given message, and the renamed file is
        no longer listed. A file that vanished since the listing, or that another reader
        claimed first, is skipped. The claimed file stays in the channel until
        ``end_read_message`` is called with the returned message, which deletes it.

        Args:
            subscribed: True when called by the subscribe loop that registered with
                ``begin_subscription``; False for a direct fetch

        Returns:
            The next message, or None if no message is waiting

        Raises:
            RuntimeError: If the channel is not open; if ``subscribed`` is False while a
                subscribe is listening (a channel has a single consumer); or if
                ``subscribed`` is True while no subscribe is registered
            ValueError: If the message file is not a valid message. The claimed file is
                left in the channel, never handed out again, and the next call hands out
                the following message.
            OSError: If the message file cannot be claimed for another reason (for example
                it stays locked by another program)
        """
        while True:
            message_file_path = self._next_message_path(subscribed)
            if message_file_path is None:
                return None
            claimed_path = message_file_path.with_name(message_file_path.name + LOCKED_SUFFIX)
            try:
                retry_fs(partial(os.rename, message_file_path, claimed_path))
                with open(claimed_path, "rb") as stream:
                    return Message.read(stream)
            except FileNotFoundError:
                continue  # taken or deleted since the listing

    def end_read_message(self, message: Message) -> None:
        """
        Finish reading a message obtained from ``begin_read_message``: delete its file.

        Once a message is handed out the channel keeps no record of it: this and
        ``cancel_read_message`` are what dispose of it.

        Does nothing if the file is already gone (for example because the channel was
        closed meanwhile). A file that cannot be deleted is logged and left in the channel,
        which deletes it when it is closed.

        Args:
            message: The message returned by ``begin_read_message``
        """
        claimed_path = self.directory_path / (message.file_name + LOCKED_SUFFIX)
        try:
            retry_fs(claimed_path.unlink)
        except FileNotFoundError:
            pass
        except OSError as e:
            logging.warning(f"Could not delete message file {claimed_path}: {e}")

    def cancel_read_message(self, message: Message, poison: bool = False) -> None:
        """
        Give a message obtained from ``begin_read_message`` back to the channel.

        The channel keeps no record of a message once it has handed it out, so this only
        deals with the message file. Every call is logged: at INFO level when the message
        goes back to the channel, at WARNING level when it is moved as poison.

        - ``poison=False``: the file gets its original name back. The message is handed out
          again by the first listing of the directory that happens after the messages
          already listed have been handed out, in id order with the others.
        - ``poison=True``: the file is moved to the ``poison`` sub-directory of the channel
          (see ``poison_path``), under its original name. It is never handed out again by
          this channel: it is left to whoever handles the poison messages. Use it for a
          message that would fail every time it is processed.

        Does nothing to the file if it is already gone (for example because the channel was
        closed meanwhile). A file that cannot be renamed or moved is logged and left locked
        in the channel, which deletes it when it is closed.

        Args:
            message: The message returned by ``begin_read_message``
            poison: True to move the message to the poison folder instead of giving it back
        """
        claimed_path = self.directory_path / (message.file_name + LOCKED_SUFFIX)
        if poison:
            target_path = self.poison_path / message.file_name
            logging.warning(
                f"Message {message.id} on topic '{message.topic}' is poison: moving it to "
                f"{target_path}"
            )
        else:
            target_path = self.directory_path / message.file_name
            logging.info(
                f"Message {message.id} on topic '{message.topic}' rejected: giving it back "
                f"to {self}"
            )
        try:
            if poison:
                self.poison_path.mkdir(exist_ok=True)
            retry_fs(partial(os.rename, claimed_path, target_path))
        except FileNotFoundError:
            pass
        except OSError as e:
            logging.warning(f"Could not move message file {claimed_path} to {target_path}: {e}")

    def _next_message_path(self, subscribed: bool) -> Path | None:
        """Pop the file of the next message to hand out, listing the directory if needed."""
        with self._lock:
            if not self._open:
                raise RuntimeError("Channel must be open to fetch messages")
            if self._subscribed and not subscribed:
                raise RuntimeError(
                    "Cannot fetch from a channel that is being listened to by subscribe()"
                )
            if subscribed and not self._subscribed:
                raise RuntimeError("subscribed=True requires a registered subscription")
            if not self._pending:
                self._pending = self._load_pending()
            if not self._pending:
                return None
            return self.directory_path / self._pending.pop()

    def _load_pending(self) -> list[str]:
        """List the message file names waiting in the channel directory, the largest id first."""
        try:
            with os.scandir(self.directory_path) as entries:
                names = [e.name for e in entries if is_message_file_name(e.name)]
        except FileNotFoundError:
            return []
        names.sort(reverse=True)  # zero-padded names: string order is numeric order
        return names

    def _generate_random_id(self) -> str:
        """Generate a random 12-character string."""
        return "".join(random.choices(string.ascii_letters + string.digits, k=12))

    @staticmethod
    def _validate_topic_pattern(topic: str) -> None:
        """
        Validate that topic contains only allowed characters.

        Valid characters: [a-zA-Z0-9+=.-]
        The wildcards '=' and '+' must each be a whole dot-separated term, and a '+'
        term cannot be directly next to an '=' or '+' term.

        Args:
            topic: The topic string to validate

        Raises:
            ValueError: If topic is empty, has empty or blank words, or contains invalid
                characters
        """
        if not topic:
            raise ValueError("Topic cannot be empty")

        # Every dot-separated word must contain something other than whitespace
        if any(not word.strip() for word in topic.split(".")):
            raise ValueError(
                f"Topic '{topic}' cannot contain empty or blank words "
                "(leading, trailing or consecutive dots, or whitespace-only words)."
            )

        # Check for invalid characters using regex
        if not re.match(r"^[a-zA-Z0-9+=.-]+$", topic):
            invalid_chars = set(topic) - set(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+=.-"
            )
            raise ValueError(
                f"Topic '{topic}' contains invalid characters: {sorted(invalid_chars)}."
                "Only [a-zA-Z0-9+=.-] are allowed."
            )

        # Wildcards must be alone between dots (e.g. 'a.=.b', never 'a.b=' or 'a.+b')
        terms = topic.split(".")
        for term in terms:
            if ("=" in term or "+" in term) and term not in ("=", "+"):
                raise ValueError(
                    f"Topic '{topic}' has invalid wildcard usage in term '{term}': "
                    "'=' and '+' must be alone between dots."
                )

        # '+' next to '=' (either order) or to another '+' is ambiguous and not allowed
        for left, right in zip(terms, terms[1:]):
            if {left, right} == {"=", "+"} or left == right == "+":
                raise ValueError(
                    f"Topic '{topic}' has invalid wildcard usage: '+' cannot be adjacent "
                    "to '=' or to another '+'."
                )

    def open(self) -> None:
        """
        Open the channel: create its directory so that publishers can deliver messages.

        Opening an open channel does nothing. Messages published before the channel is
        opened are not delivered to it.

        Raises:
            RuntimeError: If the channel directory cannot be created
            OSError: With errno ENAMETOOLONG if Windows reports a path that is too long
        """
        with self._lock:
            if self._open:
                return
            try:
                self.directory_path.parent.mkdir(parents=True, exist_ok=True)
                self.directory_path.mkdir()
            except OSError as e:
                raise_if_path_too_long(e)
                raise RuntimeError(f"Failed to create channel directory: {e}") from e
            self._pending = []
            self._open = True

    def close(self) -> None:
        """
        Close the channel and delete its directory and any unconsumed messages.

        The directory is first moved to the purge directory, so publishers stop seeing the
        channel at once, then its content is deleted. Closing a channel that is not open
        does nothing.
        """
        with self._lock:
            if not self._open:
                return
            self._open = False
            self._pending = []
        self._purge_directory()

    def _purge_directory(self) -> None:
        """Move the channel directory to the purge directory, then delete it."""
        token = "".join(random.choices(string.ascii_letters + string.digits, k=PURGE_TOKEN_LENGTH))
        purge_dir = get_purge_dir()
        target = purge_dir / f"{token}_{self.directory_name}"
        source = self.directory_path
        try:
            purge_dir.mkdir(parents=True, exist_ok=True)
            retry_fs(lambda: os.rename(source, target))
        except OSError as e:
            # Could not move it (for example a file in it is locked): delete it in place
            logging.debug(f"Could not move {source} to {target} ({e}); deleting in place.")
            target = source
        Channel._delete_recursive(target)

    @staticmethod
    def _delete_recursive(dir: Path) -> None:
        """Recursively delete a directory and all its contents, tolerating races."""
        try:
            entries = list(os.scandir(dir))
        except FileNotFoundError:
            return
        except OSError as e:
            logging.warning(f"Failed to list {dir}: {e}")
            return
        for entry in entries:
            path = Path(entry.path)
            try:
                if entry.is_dir(follow_symlinks=False):
                    Channel._delete_recursive(path)
                else:
                    retry_fs(path.unlink)
            except FileNotFoundError:
                pass
            except OSError as e:
                logging.warning(f"Failed to delete {path}: {e}")
        try:
            retry_fs(dir.rmdir)
        except FileNotFoundError:
            pass
        except OSError as e:
            logging.warning(f"Failed to delete directory {dir}: {e}")

    @staticmethod
    def cleanup_inactive() -> None:
        """
        Clean up what dead processes left behind in the pubsub base directory.

        - Channels whose process is no longer running are deleted with their messages.
        - Channels being purged by a process that died before finishing are deleted.
        - Temporary message files older than one hour (STALE_TMP_SECONDS), left by a
          publisher that died while publishing, are deleted.
        """
        for path in Channel.inactive_paths():
            try:
                Channel._delete_recursive(path)
                logging.info(f"Cleaned up inactive channel at {path}")
            except OSError as e:
                logging.warning(f"Failed to clean up inactive channel at {path}: {e}")
        Channel._cleanup_purge()
        Channel._cleanup_stale_tmp()

    @staticmethod
    def _cleanup_purge() -> None:
        """Finish the purge of channels abandoned by a process that is no longer running."""
        try:
            entries = list(os.scandir(get_purge_dir()))
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            try:
                pid = int(entry.name.split("_")[-1])
            except ValueError:
                continue
            if not is_process_running(pid):
                Channel._delete_recursive(Path(entry.path))
                logging.info(f"Cleaned up abandoned purge at {entry.path}")

    @staticmethod
    def _cleanup_stale_tmp() -> None:
        """Delete temporary message files too old to belong to a publisher still writing."""
        try:
            entries = list(os.scandir(get_tmp_dir()))
        except OSError:
            return
        cutoff_ms = (time.time() - STALE_TMP_SECONDS) * 1000
        for entry in entries:
            if not is_message_file_name(entry.name):
                continue
            if message_id_time_ms(int(entry.name)) >= cutoff_ms:
                continue
            try:
                os.unlink(entry.path)
                logging.info(f"Cleaned up stale temporary message {entry.path}")
            except FileNotFoundError:
                pass
            except OSError as e:
                logging.debug(f"Could not delete stale temporary message {entry.path}: {e}")

    @staticmethod
    def _channel_dirs() -> list[tuple[Path, int]]:
        """List the channel directories of the base directory with their process id."""
        try:
            items = list(get_base_dir().iterdir())
        except OSError:
            return []
        found = []
        for item in items:
            parts = item.name.split("_")
            if len(parts) < 3:
                continue
            try:
                pid = int(parts[-1])
            except ValueError:
                continue
            if item.is_dir():
                found.append((item, pid))
        return found

    @staticmethod
    def active_paths() -> list[Path]:
        """
        List all active channel paths in the pubsub base directory.

        Only includes channels where the associated process is still running.

        Returns:
            List of active channel paths
        """
        return sorted(path for path, pid in Channel._channel_dirs() if is_process_running(pid))

    @staticmethod
    def inactive_paths() -> list[Path]:
        """
        List all inactive channel paths in the pubsub base directory.

        Includes channels where the associated process is no longer running.

        Returns:
            List of inactive channel paths
        """
        return sorted(
            path for path, pid in Channel._channel_dirs() if not is_process_running(pid)
        )

    def __str__(self) -> str:
        return f"Channel(topic='{self.topic}', directory='{self.directory_name}')"

    def __repr__(self) -> str:
        return f"Channel(topic='{self.topic}', pid={self.process_id}, random_id='{self.random_id}')"

    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources."""
        self.close()
