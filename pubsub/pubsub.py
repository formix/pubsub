"""PubSub module for publishing, fetching, and subscribing to messages."""

import os
import time
import logging
import struct
from typing import Callable, Optional

from .message import Message
from .channel import Channel
from .abstractions import get_base_dir


def publish(topic: str, data: bytes, headers: dict | None = None) -> int:
    """
    Publish a message to a topic.
    
    Lists all channel directories in the pubsub base directory and matches against wildcard patterns
    using regex conversion (= -> [a-zA-Z0-9-], + -> [a-zA-Z0-9.-]*).
    
    Args:
        topic: The topic to publish to
        data: The message payload as bytes
        headers: Optional dictionary of string key-value pairs for metadata
    Returns:
        The number of times the messages was published in a channel
        
    Raises:
        RuntimeError: If unable to publish to any matching channels
    """

    message = Message(topic=topic, content=data, headers=headers)
    tmp_dir = get_base_dir() / "tmp"
    tmp_dir.mkdir(exist_ok=True)  # Ensure temporary directory exists
    message_temp_file = tmp_dir / f"{message.id}"
    with open(message_temp_file, 'wb') as msg_file:
        message.write(msg_file)
    
    publication_count = 0
    matching_channels = Channel.matching_active_paths(topic)
    for channel_dir in matching_channels:
        queue_path = channel_dir / "queue"
        if not queue_path.exists():
            logging.warning(f"Channel directory {channel_dir} does not contain a queue file. Skipping.")
            continue
        try:
            message_file_path = channel_dir / str(message.id)
            os.link(str(message_temp_file), str(message_file_path))
            with os.fdopen(os.open(str(queue_path), os.O_WRONLY | os.O_NONBLOCK), 'wb') as queue_file:
                queue_file.write(struct.pack('!Q', message.id))
                publication_count += 1
        except (OSError, BrokenPipeError) as e:
            logging.warning(f"Failed to publish message {message.id} to {queue_path}: {e}")
    
    message_temp_file.unlink()
    
    return publication_count
    


def fetch(channel: Channel) -> Optional[Message]:
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
    """
    # Read message ID from queue (non-blocking)
    try:
        id_bytes = os.read(channel._fp, 8)
    except BlockingIOError:
        # No data available (non-blocking read)
        return None
    
    if not id_bytes or len(id_bytes) != 8:
        # No data available or incomplete ID
        return None

    id = struct.unpack('!Q', id_bytes)[0]
    message_file_path = channel.directory_path / str(id)
    if not message_file_path.exists():
        return None
        
    with open(message_file_path, 'rb') as msg_file:
        message = Message.read(msg_file)
        
    message_file_path.unlink()
    
    return message


def subscribe(channel: Channel, callback: Callable[[Message], None], timeout_seconds: float = 0) -> int:
    """
    Subscribe to a channel and call a function for each received message.
    
    Listens for messages for the specified duration and calls the callback function
    for each message received.
    
    Args:
        channel: The channel to subscribe to
        callback: Function to call with each received message
        timeout_seconds: How long to listen for messages (0 = listen indefinitely)
        
    Returns:
        Number of messages processed
        
    Raises:
        ValueError: If timeout_seconds is negative
        RuntimeError: If unable to open channel for reading
    """
    if timeout_seconds < 0:
        raise ValueError("timeout_seconds must be non-negative")
    
    message_count = 0
    start_time = time.time()
    listen_indefinitely = (timeout_seconds == 0)
    while listen_indefinitely or (time.time() - start_time < timeout_seconds):
        message = fetch(channel)
        if message:
            try:
                callback(message)
            except Exception as e:
                logging.warning(f"Error processing message {message}: {e}")
            message_count += 1
        time.sleep(0.01)  # Sleep briefly to avoid busy waiting
    
    return message_count

