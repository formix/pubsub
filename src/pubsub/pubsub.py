"""PubSub module for publishing, fetching, and subscribing to messages."""

import os
import time
import select
import re
import logging
from typing import Callable, Optional, List
from pathlib import Path

from .message import Message
from .channel import Channel, PUBSUB_BASE_DIR


def publish(topic: str, data: bytes, headers: Optional[dict] = None) -> int:
    """
    Publish a message to a topic.
    
    Lists all channel directories in /dev/shm/pubsub and matches against wildcard patterns
    using regex conversion (= -> [a-zA-Z0-9-], + -> [a-zA-Z0-9.-]*).
    
    Args:
        topic: The topic to publish to
        data: The message payload as bytes
        headers: Optional metadata headers
        
    Returns:
        The number of messages sent
        
    Raises:
        RuntimeError: If unable to publish to any matching channels
    """

    message = Message(topic=topic, data=data, headers=headers)
    tmp_dir = PUBSUB_BASE_DIR / "tmp"
    tmp_dir.mkdir(exist_ok=True)  # Ensure temporary directory exists
    original_message_file = tmp_dir / f"{message.message_id}"
    with open(original_message_file, 'wb') as msg_file:
        message.write(msg_file)
    
    publication_count = 0
    matching_channels = _find_matching_channels_regex(topic)
    for channel_dir in matching_channels:
        queue_path = channel_dir / "queue"
        if not queue_path.exists():
            logging.warning(f"Channel directory {channel_dir} does not contain a queue file. Skipping.")
            continue
        try:
            message_file_path = channel_dir / str(message.message_id)
            os.link(str(original_message_file), str(message_file_path))
            with os.fdopen(os.open(str(queue_path), os.O_WRONLY | os.O_NONBLOCK), 'wb') as queue_file:
                queue_file.write(message.message_id.bytes)
                publication_count += 1
        except (OSError, BrokenPipeError) as e:
            logging.warning(f"Failed to publish message {message.message_id} to {queue_path}: {e}")
    
    original_message_file.unlink()
    
    return publication_count
    


def fetch(channel: Channel) -> Optional[Message]:
    """
    Fetch a single message from a channel (non-blocking).
    
    Reads a 16-byte UUID from the FIFO queue, then loads the actual message
    from the corresponding file.
    
    Args:
        channel: The channel to fetch from
        
    Returns:
        Message if one is available, None otherwise
        
    Raises:
        ValueError: If message format is invalid
    """
    try:
        # Open queue for reading (non-blocking)
        with os.fdopen(channel.open_queue_for_reading(), 'rb') as queue_file:
            # Read exactly 16 bytes (UUID size)
            uuid_bytes = queue_file.read(16)
            
            # Check if queue is empty
            if not uuid_bytes or len(uuid_bytes) != 16:
                return None
            
            # Convert bytes to UUID
            import uuid
            message_id = uuid.UUID(bytes=uuid_bytes)
            
            # Load message from file
            message_file_path = channel.directory_path / str(message_id)
            if not message_file_path.exists():
                # Message file doesn't exist (maybe already consumed)
                return None
                
            with open(message_file_path, 'rb') as msg_file:
                message = Message.read(msg_file)
                
            # Clean up the message file after reading
            message_file_path.unlink()
            return message
                
    except (OSError, BlockingIOError):
        # No message available or queue not ready
        return None


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
    
    try:
        # Open the queue for reading
        queue_fd = channel.open_queue_for_reading()
        
        with os.fdopen(queue_fd, 'rb') as queue_file:
            while True:
                if not listen_indefinitely:
                    # Calculate remaining time
                    elapsed = time.time() - start_time
                    remaining_time = timeout_seconds - elapsed
                    
                    if remaining_time <= 0:
                        break
                    
                    select_timeout = min(remaining_time, 1.0)
                else:
                    # Listen indefinitely - use 1 second timeout for select to allow interruption
                    select_timeout = 1.0
                
                # Use select to wait for data with timeout
                ready, _, _ = select.select([queue_file], [], [], select_timeout)
                
                if ready:
                    try:
                        message = fetch(channel)
                        if message:
                            callback(message)
                            message_count += 1
                    except (ValueError, OSError):
                        # Skip invalid messages or temporary read errors
                        continue
                else:
                    # No data available, continue polling (unless timed out)
                    if not listen_indefinitely:
                        continue
    
    except OSError as e:
        raise RuntimeError(f"Failed to subscribe to channel: {e}") from e
    
    return message_count


def _find_matching_channels_regex(topic: str) -> List[Path]:
    """
    Find all channel directories in /dev/shm/pubsub that match the given topic using regex.
    
    Converts wildcards to regex patterns:
    - '=' becomes '[a-zA-Z0-9-]' (single word wildcard)
    - '+' becomes '[a-zA-Z0-9.-]*' (multiple words wildcard)
    
    Args:
        topic: The topic to match against
        
    Returns:
        List of Path objects for matching channel directories
    """
    matching_channels = []
    pubsub_path = Path("/dev/shm/pubsub")
    
    if not pubsub_path.exists():
        return matching_channels
    
    # Look for channel directories (format: topic-randomid-pid)
    for item in pubsub_path.iterdir():
        if not item.is_dir():
            continue
            
        # Extract the topic part from directory name
        dir_name = item.name
        # Split by '_' and take all but last two parts (randomid and pid)
        parts = dir_name.split('_')
        if len(parts) < 3:
            continue
            
        # Reconstruct channel topic (everything except last two parts)
        channel_topic = '_'.join(parts[:-2])
        
        # Convert wildcards to regex pattern
        regex_pattern = channel_topic.replace('=', '[a-zA-Z0-9-]').replace('+', '[a-zA-Z0-9.-]*')
        
        # Check if the published topic matches the channel's regex pattern
        if re.fullmatch(regex_pattern, topic):
            matching_channels.append(item)
    
    return matching_channels


def list_active_channels() -> List[str]:
    """
    List all active channel topics in /dev/shm/pubsub.
    
    Only includes channels where the associated process is still running.
    
    Returns:
        List of active channel topic names
    """
    channels = []
    pubsub_path = Path("/dev/shm/pubsub")
    
    if not pubsub_path.exists():
        return channels
    
    for item in pubsub_path.iterdir():
        if not item.is_dir():
            continue
            
        dir_name = item.name
        parts = dir_name.split('_')
        if len(parts) < 3:
            continue
            
        # Extract topic and PID
        topic = '_'.join(parts[:-2])
        pid = parts[-1]
        
        # Check if process is still running
        try:
            if not os.path.exists(f"/proc/{pid}"):
                continue
            if topic not in channels:
                channels.append(topic)
        except (ValueError, OSError):
            # Invalid PID format or permission error, skip
            continue
    
    return sorted(channels)


def list_inactive_channels() -> List[str]:
    """
    List all inactive channel topics in /dev/shm/pubsub.
    
    Includes channels where the associated process is no longer running.
    
    Returns:
        List of inactive channel topic names
    """
    channels = []
    pubsub_path = Path("/dev/shm/pubsub")
    
    if not pubsub_path.exists():
        return channels
    
    for item in pubsub_path.iterdir():
        if not item.is_dir():
            continue
            
        dir_name = item.name
        parts = dir_name.split('_')
        if len(parts) < 3:
            continue
            
        # Extract topic and PID
        topic = '_'.join(parts[:-2])
        pid = parts[-1]
        
        # Check if process is no longer running
        try:
            if os.path.exists(f"/proc/{pid}"):
                continue
            if topic not in channels:
                channels.append(topic)
        except (ValueError, OSError):
            # Invalid PID format or permission error, consider inactive
            if topic not in channels:
                channels.append(topic)
    
    return sorted(channels)
