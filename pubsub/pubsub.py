"""PubSub module for publishing, fetching, and subscribing to messages."""

import logging
import os
import re
import signal
import struct
import time
from collections.abc import Callable

from .abstractions import get_base_dir
from .channel import Channel
from .message import Header, Message


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
        RuntimeError: If unable to publish to any matching channels
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

    message = Message(topic=topic, content=data, headers=headers)
    tmp_dir = get_base_dir() / "tmp"
    tmp_dir.mkdir(exist_ok=True)  # Ensure temporary directory exists
    message_temp_file = tmp_dir / f"{message.id}"
    with open(message_temp_file, "wb") as msg_file:
        message.write(msg_file)

    publication_count = 0
    for channel_dir in Channel.active_paths():
        # Channel directories are named {pattern}_{random_id}_{process_id}
        if not _is_matching(channel_dir.name.split("_")[0], topic):
            continue
        queue_path = channel_dir / "queue"
        if not queue_path.exists():
            logging.warning(
                f"Channel directory {channel_dir} does not contain a queue file. Skipping."
            )
            continue
        try:
            message_file_path = channel_dir / str(message.id)
            os.link(str(message_temp_file), str(message_file_path))
            with os.fdopen(
                os.open(str(queue_path), os.O_WRONLY | os.O_NONBLOCK), "wb"
            ) as queue_file:
                queue_file.write(struct.pack("!Q", message.id))
                publication_count += 1
        except (OSError, BrokenPipeError) as e:
            logging.warning(f"Failed to publish message {message.id} to {queue_path}: {e}")

    try:
        message_temp_file.unlink()
    except FileNotFoundError:
        logging.debug(f"Temporary message file {message_temp_file} already removed.")

    return publication_count


def fetch(channel: Channel) -> Message | None:
    """
    Fetch a single message from a channel (non-blocking).

    Reads an 8-byte message ID from the FIFO queue, then loads the actual message
    from the corresponding file.

    Args:
        channel: The channel to fetch from

    Returns:
        Message if one is available, None otherwise

    Raises:
        ValueError: If message format is invalid
        RuntimeError: If channel is not open for reading
    """
    if not channel.is_open:
        raise RuntimeError("Channel must be open to fetch messages")

    # Read message ID from queue (non-blocking)
    try:
        id_bytes = os.read(channel._fp, 8)
    except BlockingIOError:
        # No data available (non-blocking read)
        return None

    if not id_bytes or len(id_bytes) != 8:
        # No data available or incomplete ID
        return None

    id = struct.unpack("!Q", id_bytes)[0]
    message_file_path = channel.directory_path / str(id)
    if not message_file_path.exists():
        return None

    with open(message_file_path, "rb") as msg_file:
        message = Message.read(msg_file)

    message_file_path.unlink()

    return message


def subscribe(
    channel: Channel, callback: Callable[[Message], None], timeout_seconds: float = 0
) -> int:
    """
    Subscribe to a channel and call a function for each received message.

    Listens for messages for the specified duration and calls the callback function
    for each message received.

    Signal Handling:
        This function handles SIGTERM and SIGINT signals gracefully. When either signal
        is received:
        - The subscription loop exits cleanly
        - Any message being processed completes normally
        - The function returns the count of processed messages
        - The original signal handler (if any) is called before returning

        This allows subscribers services to be terminated gracefully.

    Args:
        channel: The channel to subscribe to
        callback: Function to call with each received message
        timeout_seconds: How long to listen for messages (0 = listen indefinitely)

    Returns:
        - Number of messages processed. Returned after normal timeout expiration.
        - Returns -1 if exited due to a termination signal (SIGTERM/SIGINT).

    Raises:
        RuntimeError: If channel is not open for reading
        ValueError: If timeout_seconds is negative

    """
    if timeout_seconds < 0:
        raise ValueError("timeout_seconds must be non-negative")

    if not channel.is_open:
        raise RuntimeError("Channel must be open to subscribe")

    # Set up signal handler for graceful shutdown
    shutdown_requested = False
    signal_args: tuple | None = None
    def signal_handler(signum, frame):
        nonlocal shutdown_requested, signal_args
        shutdown_requested = True
        signal_args = (signum, frame)
        logging.info("Received termination signal, exiting subscribe loop...")

    # Register SIGTERM and SIGINT handlers
    original_sigterm = signal.signal(signal.SIGTERM, signal_handler)
    original_sigint = signal.signal(signal.SIGINT, signal_handler)

    try:
        message_count = 0
        start_time = time.time()
        listen_forever = timeout_seconds == 0
        while not shutdown_requested and (
            listen_forever or (time.time() - start_time < timeout_seconds)
        ):
            message = fetch(channel)
            if message:
                try:
                    callback(message)
                except Exception as e:
                    logging.warning(f"Error processing message {message}: {e}")
                message_count += 1
            try:
                time.sleep(0.01)  # Sleep briefly to avoid busy waiting
            except KeyboardInterrupt:
                # time.sleep() can raise KeyboardInterrupt when SIGINT is
                # delivered during the sleep syscall, before the custom signal
                # handler has a chance to suppress it. Treat it identically.
                shutdown_requested = True
        if shutdown_requested:
            logging.info("Exiting subscribe loop on '%s'. Handled %i messages.",
                         channel.topic, message_count)
            return -1  # Indicate shutdown by signal
        return message_count
    finally:
        # Call original handler if a signal was received
        if signal_args is not None:
            if signal_args[0] == signal.SIGTERM and callable(original_sigterm):
                original_sigterm(*signal_args)
            elif signal_args[0] == signal.SIGINT and callable(original_sigint):
                original_sigint(*signal_args)
