"""Channel class for pubsub system using shared memory and FIFO queues."""

import os
import stat
import random
import string
import re
from pathlib import Path
from typing import List

from .abstractions import get_base_dir, is_process_running


class Channel:
    """
    Represents a pubsub channel using shared memory filesystem and FIFO queues.
    
    Creates a directory in the pubsub base directory with format: {topic}_{random_12_chars}_{process_id}
    Contains a non-blocking FIFO named 'queue' for message passing.
    
    Topic format supports wildcards:
    - '=' for single word wildcard
    - '+' for multiple words wildcard
    """
    
    def __init__(self, topic: str):
        """
        Initialize a new channel.
        
        Args:
            topic: The topic string (dot-separated terms with optional wildcards)
            
        Raises:
            ValueError: If topic contains invalid characters
        """
        self._validate_topic(topic)
        self.topic = topic
        self.process_id = os.getpid()
        self.random_id = self._generate_random_id()
        self.directory_name = f"{topic}_{self.random_id}_{self.process_id}"
        self.directory_path = get_base_dir() / self.directory_name
        self.queue_path = self.directory_path / "queue"
        
        # Create the channel directory and FIFO
        self._create_channel()
    
    def _generate_random_id(self) -> str:
        """Generate a random 12-character string."""
        return ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    
    
    @staticmethod
    def _validate_topic(topic: str) -> None:
        """
        Validate that topic contains only allowed characters.
        
        Valid characters: [a-zA-Z0-9+=.-]
        
        Args:
            topic: The topic string to validate
            
        Raises:
            ValueError: If topic is empty or contains invalid characters
        """
        if not topic:
            raise ValueError("Topic cannot be empty")
        
        # Check for invalid characters using regex
        if not re.match(r'^[a-zA-Z0-9+=.-]+$', topic):
            invalid_chars = set(topic) - set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+=.-')
            raise ValueError(f"Topic '{topic}' contains invalid characters: {sorted(invalid_chars)}. Only [a-zA-Z0-9+=.-] are allowed.")
        
    
    def _create_channel(self) -> None:
        """Create the channel directory and FIFO queue."""
        try:
            # Create the directory in the pubsub base directory
            self.directory_path.mkdir(parents=True, exist_ok=True)
            
            # Create the FIFO queue if it doesn't exist
            if not self.queue_path.exists():
                os.mkfifo(str(self.queue_path))
                # Set permissions for the FIFO (readable/writable by owner and group)
                os.chmod(str(self.queue_path), stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP)
                
        except OSError as e:
            raise RuntimeError(f"Failed to create channel directory or FIFO: {e}") from e
        
    
    def cleanup(self) -> None:
        """
        Clean up the channel by removing unconsumed messages, the FIFO, and directory.
        
        This ensures that any undelivered messages are properly deleted when the
        channel is disposed, preventing resource leaks.
        """
        try:
            # Remove the fifo queue and all unconsumed message files in the directory
            if self.directory_path.exists() and self.directory_path.is_dir():
                for item in self.directory_path.iterdir():
                    # Use unlink() for both regular files and FIFOs
                    # is_file() returns False for FIFOs, so check exists() instead
                    if item.exists():
                        item.unlink()
            
            # Remove the directory
            if self.directory_path.exists():
                self.directory_path.rmdir()
                
        except OSError as e:
            raise RuntimeError(f"Failed to cleanup channel {self.directory_name}: {e}") from e

    
    def open_queue_for_reading(self) -> int:
        """
        Open the FIFO queue for reading in non-blocking mode.
        
        Returns:
            File descriptor for reading
            
        Raises:
            OSError: If unable to open the FIFO for reading
        """
        try:
            return os.open(str(self.queue_path), os.O_RDONLY | os.O_NONBLOCK)
        except OSError as e:
            raise OSError(f"Failed to open queue for reading: {e}") from e
        

    @staticmethod
    def active_paths() -> List[Path]:
        """
        List all active channel paths in the pubsub base directory.
        
        Only includes channels where the associated process is still running.
        
        Returns:
            List of active channel paths
        """
        channels = []
        pubsub_path = get_base_dir()
        if not pubsub_path.exists():
            return channels
        
        for item in [i for i in pubsub_path.iterdir() if i.is_dir()]:
            parts = item.name.split('_')
            if len(parts) < 3: continue
            pid = int(parts[-1])
            if is_process_running(pid):
                channels.append(item)
        
        return sorted(channels)


    @staticmethod
    def inactive_paths() -> List[Path]:
        """
        List all inactive channel paths in the pubsub base directory.
        
        Includes channels where the associated process is no longer running.
        
        Returns:
            List of inactive channel paths
        """
        channels = []
        pubsub_path = get_base_dir()
        if not pubsub_path.exists():
            return channels
        
        for item in [i for i in pubsub_path.iterdir() if i.is_dir()]:
            parts = item.name.split('_')
            if len(parts) < 3: continue
            pid = int(parts[-1])
            if not is_process_running(pid):
                channels.append(item)
        
        return sorted(channels)
    

    @staticmethod
    def matching_active_paths(topic: str) -> List[Path]:
        """
        Find all channel directories in the pubsub base directory that match the given topic using regex.
        
        Converts wildcards to regex patterns:
        - '=' becomes '[a-zA-Z0-9-]' (single word wildcard)
        - '+' becomes '[a-zA-Z0-9.-]*' (multiple words wildcard)
        
        Args:
            topic: The topic to match against
            
        Returns:
            List of Path objects for matching channel directories
        """
        matching_channels = []
        for item in Channel.active_paths():
            parts = item.name.split('_')
            topic_pattern = parts[0]
            regex_pattern = topic_pattern.replace('=', '[a-zA-Z0-9-]').replace('+', '[a-zA-Z0-9.-]*')
            if re.fullmatch(regex_pattern, topic):
                matching_channels.append(item)
        return matching_channels

        
    
    def __str__(self) -> str:
        return f"Channel(topic='{self.topic}', directory='{self.directory_name}')"
    
    def __repr__(self) -> str:
        return f"Channel(topic='{self.topic}', pid={self.process_id}, random_id='{self.random_id}')"
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources."""
        self.cleanup()
