"""PubSub module for publishing, fetching, and subscribing to messages."""

import errno
import logging
import os
import re
import shutil
import signal
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .abstractions import get_tmp_dir, raise_if_path_too_long, retry_fs
from .channel import Channel
from .message import Header, Message
from .watcher import create_watcher

# Longest time the subscribe loop waits for a notification before looking again, so
# that it keeps noticing signals and timeouts even if the system reports nothing.
_MAX_WAIT_SECONDS = 0.1

# Whether hard links work in the base directory: None until the first publication tells
_hardlinks_supported: bool | None = None
_hardlinks_lock = threading.Lock()

# errno values and Windows error codes meaning "this file system has no hard links"
_NO_HARDLINK_ERRNOS = {
    errno.EPERM,
    errno.ENOSYS,
    errno.EMLINK,
    getattr(errno, "EOPNOTSUPP", errno.EPERM),
    getattr(errno, "ENOTSUP", errno.EPERM),
}
_NO_HARDLINK_WINERRORS = {1, 50, 1142}  # invalid function, not supported, too many links


def _is_matching(pattern: str, topic: str) -> bool:
    """
    Check whether a channel pattern matches a concrete topic.

    Both are '.'-separated words. In the pattern, a word is either a literal, or a
    wildcard standing alone between dots:
    - '=' matches exactly one word
    - '+' matches one or more words, or zero or more words when it is the last word
    of the pattern

    Args:
        pattern: The channel pattern, possibly containing '=' and '+' words
        topic: The concrete topic being published (no wildcards)

    Returns:
        True if the topic matches the pattern, False otherwise
    """
    if not pattern: raise ValueError("Pattern cannot be empty")
    if not topic: raise ValueError("Topic cannot be empty")

    pwords = pattern.split(".")
    twords = topic.split(".")

    # A trailing '+' may match zero words: it simply absorbs whatever the rest of the
    # pattern leaves over, so it is removed from the pattern and remembered
    open_end = pwords[-1] == "+"
    if open_end:
        pwords.pop()

    p = 0  # index of the current pattern word
    t = 0  # index of the current topic word
    plus_p = -1  # pattern index of the last '+' seen, -1 if none
    plus_t = 0  # topic index just after the words absorbed so far by that '+'

    while t < len(twords):
        if p == len(pwords) and open_end:
            return True  # the trailing '+' absorbs all remaining topic words
        pword = pwords[p] if p < len(pwords) else None
        if pword == "+":
            # A '+' in the middle absorbs one word, and more only if what follows fails
            plus_p = p
            p += 1
            t += 1
            plus_t = t
        elif pword == "=":
            p += 1
            t += 1
        elif pword is not None and pword == twords[t]:
            p += 1
            t += 1
        elif plus_p != -1 and plus_t < len(twords):
            # Mismatch: let the last '+' absorb one more word and resume right after it
            plus_t += 1
            t = plus_t
            p = plus_p + 1
        else:
            return False

    return p == len(pwords)  # topic fully consumed: the pattern must be as well


def _is_hardlink_unsupported(error: OSError) -> bool:
    """Tell whether a failed os.link means the file system cannot hard link at all."""
    return error.errno in _NO_HARDLINK_ERRNOS or getattr(error, "winerror", None) in (
        _NO_HARDLINK_WINERRORS
    )


def _link_message(source: Path, target: Path) -> None:
    """
    Make the staged message file appear atomically under its name in a channel directory.

    Uses a hard link. On file systems without hard links (FAT, exFAT, some network
    shares) it copies the file next to its destination under a hidden name and renames it.

    Raises:
        FileExistsError: If a message with the same name is already in the channel
        FileNotFoundError: If the channel directory is gone
        OSError: On any other failure
    """
    global _hardlinks_supported
    if _hardlinks_supported is not False:
        try:
            os.link(source, target)
            _hardlinks_supported = True
            return
        except OSError as e:
            if isinstance(e, (FileExistsError, FileNotFoundError)):
                raise
            if not _is_hardlink_unsupported(e):
                raise
            with _hardlinks_lock:
                _hardlinks_supported = False
            logging.info("Hard links are not supported here, copying messages instead.")

    part = target.with_name(f".{target.name}.part")
    shutil.copyfile(source, part)
    try:
        if not sys.platform == "win32" and target.exists():
            raise FileExistsError(errno.EEXIST, "File exists", str(target))
        os.rename(part, target)  # on Windows this fails if the target exists
    except BaseException:
        try:
            part.unlink()
        except OSError:
            pass
        raise


def _validate_publish_topic(topic: str) -> None:
    """
    Validate the topic of a message about to be published.

    Args:
        topic: The topic to publish to

    Raises:
        ValueError: If a dot-separated word is empty or blank, or if the topic contains a
            character other than [a-zA-Z0-9.-] (wildcards are not allowed when publishing)
    """
    # Every dot-separated word must contain something other than whitespace
    if any(not word.strip() for word in topic.split(".")):
        raise ValueError(
            f"Topic '{topic}' cannot contain empty or blank words "
            "(leading, trailing or consecutive dots, or whitespace-only words)"
        )

    # Validate that topic contains only allowed characters (no wildcards)
    if not re.match(r"^[a-zA-Z0-9.-]+$", topic):
        raise ValueError(
            f"Topic '{topic}' can only contain alphanumeric characters, dots, and hyphens "
            "[a-zA-Z0-9.-] when publishing"
        )


def publish(topic: str, data: bytes, headers: Header | None = None) -> int:
    """
    Publish a message to a topic.

    Args:
        topic: The topic to publish to (only alphanumeric, dots, and hyphens allowed)
        data: The message payload as bytes
        headers: Optional dictionary with string keys and scalar values
                 (str, int, float, bool, None) for metadata
    Returns:
        The number of times the messages was published in a channel

    Raises:
        ValueError: If topic contains invalid characters (must be [a-zA-Z0-9.-])
        RuntimeError: If the message id already exists (id collision), in the temporary
            directory or in a matching channel
    """
    _validate_publish_topic(topic)

    message = Message(topic=topic, content=data, headers=headers)
    tmp_dir = get_tmp_dir()
    tmp_dir.mkdir(parents=True, exist_ok=True)  # Ensure temporary directory exists
    message_temp_file = tmp_dir / message.file_name
    try:
        with open(message_temp_file, "xb") as msg_file:
            message.write(msg_file)
    except FileExistsError as e:
        raise RuntimeError(
            f"Message id collision: {message_temp_file} already exists. Message {message.id} "
            "was not published."
        ) from e

    publication_count = 0
    try:
        for channel_dir in Channel.active_paths():
            # Channel directories are named {pattern}_{random_id}_{process_id}
            if not _is_matching(channel_dir.name.split("_")[0], topic):
                continue
            try:
                _link_message(message_temp_file, channel_dir / message.file_name)
            except FileExistsError as e:
                raise RuntimeError(
                    f"Message id collision: message {message.id} already exists in "
                    f"{channel_dir}. The message was published to {publication_count} "
                    "channel(s) before the collision."
                ) from e
            except FileNotFoundError:
                # The channel was closed between listing and linking: nobody to deliver to
                logging.debug(f"Channel {channel_dir} was closed while publishing. Skipping.")
            except OSError as e:
                raise_if_path_too_long(e)
                logging.warning(f"Failed to publish message {message.id} to {channel_dir}: {e}")
            else:
                publication_count += 1
    finally:
        try:
            retry_fs(message_temp_file.unlink)
        except FileNotFoundError:
            logging.debug(f"Temporary message file {message_temp_file} already removed.")
        except OSError as e:
            # Left for Channel.cleanup_inactive() to delete once it is stale
            logging.warning(f"Could not remove temporary message file {message_temp_file}: {e}")

    return publication_count


def fetch(channel: Channel, auto_ack: bool = True) -> Message | None:
    """
    Fetch a single message from a channel (non-blocking).

    Takes the message with the smallest id among those the channel has received. The
    channel directory is listed only when the messages found by the previous listing have
    all been handed out, so messages that arrive meanwhile are delivered by a later call.

    A channel has a single consumer: this cannot be used while a ``subscribe`` is
    listening on the channel.

    Args:
        channel: The channel to fetch from
        auto_ack: If True (the default), the message is deleted from the channel as soon
            as it is fetched. If False, the caller must dispose of the message with
            ``ack`` (delete it) or ``nack`` (give it back to the channel, which delivers
            it again later). Until then the message stays locked in the channel, and is
            lost if the channel is closed.

    Returns:
        Message if one is available, None otherwise

    Raises:
        ValueError: If message format is invalid
        RuntimeError: If channel is not open for reading, or is being listened to by a
            ``subscribe``
    """
    message = channel.begin_read_message()
    if message is not None and auto_ack:
        channel.end_read_message(message)
    return message


def ack(channel: Channel, message: Message) -> None:
    """
    Acknowledge a message fetched with ``auto_ack=False``: delete it from the channel.

    Once a message is handed out the channel keeps no record of it, so this and ``nack``
    are what dispose of it. Acknowledging a message twice, or after the channel was closed,
    does nothing.

    Args:
        channel: The channel the message was fetched from
        message: The message to acknowledge
    """
    channel.end_read_message(message)


def nack(channel: Channel, message: Message, poison: bool = False) -> None:
    """
    Reject a message fetched with ``auto_ack=False``.

    Every call is logged: at INFO level when the message goes back to the channel, at
    WARNING level when it is moved as poison.

    - ``poison=False`` (the default): the message keeps its id and is delivered again by
      the first listing of the channel directory that happens after the messages already
      listed have been delivered. A message that is rejected over and over is therefore
      delivered over and over.
    - ``poison=True``: the message is moved to the ``poison`` sub-directory of the channel
      (``channel.poison_path``) and is never delivered again by this channel, so that
      whoever handles the poison messages deals with it. Use it for a message that would
      fail every time it is processed. The poison folder is deleted with the channel when
      the channel is closed.

    Args:
        channel: The channel the message was fetched from
        message: The message to reject
        poison: True to move the message to the poison folder instead of giving it back
    """
    channel.cancel_read_message(message, poison=poison)


def subscribe(
    channel: Channel,
    callback: Callable[[Message], None],
    timeout_seconds: float = 0,
    auto_ack: bool = True,
) -> int:
    """
    Subscribe to a channel and call a function for each received message.

    Listens for messages for the specified duration and calls the callback function
    for each message received. The function sleeps until the operating system reports a
    change in the channel directory (inotify on Linux, kqueue on macOS, directory change
    notifications on Windows), or polls with an increasing delay where it cannot.

    Only one subscribe can listen on a channel at a time, and fetch cannot be used on the
    channel meanwhile (including from the callback).

    Signal Handling:
        This function handles SIGTERM and SIGINT signals gracefully (and SIGBREAK on
        Windows, where SIGTERM is never delivered). When one is received:
        - The subscription loop exits cleanly
        - Any message being processed completes normally
        - The function returns the count of processed messages
        - The original signal handler (if any) is called before returning

        Signal handlers can only be installed from the main thread; from another thread
        the function runs without signal handling.

        This allows subscribers services to be terminated gracefully.

    Args:
        channel: The channel to subscribe to
        callback: Function to call with each received message
        timeout_seconds: How long to listen for messages (0 = listen indefinitely)
        auto_ack: If True (the default), each message is deleted from the channel once the
            callback returns, or raises. If False, the callback must dispose of the message
            with ``ack`` or ``nack``; a message it does not dispose of (including when
            the callback raises) stays locked in the channel until the channel is closed.

    Returns:
        - Number of messages processed. Returned after normal timeout expiration.
        - Returns -1 if exited due to a termination signal (SIGTERM/SIGINT).

    Raises:
        RuntimeError: If channel is not open for reading, or already has a subscribe
        ValueError: If timeout_seconds is negative

    """
    if timeout_seconds < 0:
        raise ValueError("timeout_seconds must be non-negative")

    channel.begin_subscription()

    watcher = None
    original_handlers: dict[int, object] = {}
    received_signal: tuple | None = None
    shutdown_requested = False
    try:
        def signal_handler(signum, frame):
            nonlocal shutdown_requested, received_signal
            shutdown_requested = True
            received_signal = (signum, frame)
            logging.info("Received termination signal, exiting subscribe loop...")

        # Register SIGTERM and SIGINT (and SIGBREAK on Windows) handlers
        signals = [signal.SIGTERM, signal.SIGINT]
        if hasattr(signal, "SIGBREAK"):
            signals.append(signal.SIGBREAK)
        try:
            for signum in signals:
                original_handlers[signum] = signal.signal(signum, signal_handler)
        except ValueError:
            # Not the main thread: signals cannot be handled here
            for signum, handler in original_handlers.items():
                signal.signal(signum, handler)
            original_handlers.clear()

        # The watcher is created before the first look at the directory, so that no
        # message can arrive unnoticed between the two.
        watcher = create_watcher(channel.directory_path)

        message_count = 0
        deadline = None if timeout_seconds == 0 else time.monotonic() + timeout_seconds
        while not shutdown_requested:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                break

            message = channel.begin_read_message(subscribed=True)
            if message:
                watcher.activity()
                try:
                    callback(message)
                except Exception as e:
                    logging.warning(f"Error processing message {message}: {e}")
                finally:
                    if auto_ack:
                        channel.end_read_message(message)
                message_count += 1
                continue  # look again at once: more messages may be waiting

            wait = watcher.max_wait if remaining is None else min(watcher.max_wait, remaining)
            try:
                watcher.wait(wait)
            except KeyboardInterrupt:
                # A wait can raise KeyboardInterrupt when SIGINT is delivered before the
                # custom handler is installed or when none could be installed. Treat it
                # identically.
                shutdown_requested = True
        if shutdown_requested:
            logging.info("Exiting subscribe loop on '%s'. Handled %i messages.",
                         channel.topic, message_count)
            return -1  # Indicate shutdown by signal
        return message_count
    finally:
        if watcher is not None:
            watcher.close()
        channel.end_subscription()
        for signum, handler in original_handlers.items():
            signal.signal(signum, handler)
        # Call original handler if a signal was received
        if received_signal is not None:
            handler = original_handlers.get(received_signal[0])
            if callable(handler):
                handler(*received_signal)
