"""Channel class for pubsub system using shared memory and FIFO queues."""

import logging
import os
import random
import re
import stat
import string
from pathlib import Path

from .abstractions import get_base_dir, is_process_running


class Channel:
    """
    Represents a pubsub channel using shared memory filesystem and FIFO queues.

    Creates a directory in the pubsub base directory with format:
    {topic}_{random_12_chars}_{process_id}
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
        self._validate_topic_pattern(topic)
        self._fp = -1
        self.topic = topic
        self.process_id = os.getpid()
        self.random_id = self._generate_random_id()
        self.directory_name = f"{topic}_{self.random_id}_{self.process_id}"
        self.directory_path = get_base_dir() / self.directory_name
        self.queue_path = self.directory_path / "queue"

        # Create the channel directory and FIFO
        self._create_channel()

    @property
    def is_open(self) -> bool:
        """Check if the channel's FIFO is currently open for reading."""
        return self._fp != -1


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

    def _create_channel(self) -> None:
        """Create the channel directory and FIFO queue."""
        try:
            self.directory_path.mkdir(parents=True, exist_ok=True)
            if not self.queue_path.exists():
                os.mkfifo(str(self.queue_path))
                os.chmod(
                    str(self.queue_path),
                    stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP,
                )
        except OSError as e:
            raise RuntimeError(f"Failed to create channel directory or FIFO: {e}") from e


    def open(self) -> None:
        """
        Open the FIFO queue for reading in non-blocking mode.

        Raises:
            OSError: If unable to open the FIFO for reading
        """
        if self._fp != -1:
            return  # Already open

        try:
            self._fp = os.open(str(self.queue_path), os.O_RDONLY | os.O_NONBLOCK)
        except OSError as e:
            raise OSError(f"Failed to open queue for reading: {e}") from e


    def close(self) -> None:
        """
        Close and clean up the channel by removing unconsumed messages, the FIFO, and
        directory.

        This ensures that any undelivered messages are properly deleted when the
        channel is disposed, preventing resource leaks.
        """
        # Close the file descriptor if it's open
        if self._fp == -1:
            return  # Already closed or never opened

        try:
            os.close(self._fp)
            self._fp = -1
        except OSError as e:
            raise RuntimeError(
                f"Failed to close channel file descriptor {self.directory_name}: {e}"
            ) from e
        finally:
            Channel._delete_recursive(self.directory_path)

    @staticmethod
    def _delete_recursive(dir: Path) -> None:
        """Recursively delete a directory and all its contents."""
        if not dir.exists():
            return
        for item in dir.iterdir():
            try:
                if item.is_dir():
                    Channel._delete_recursive(item)
                else:
                    item.unlink()
            except OSError as e:
                logging.warning(f"Failed to delete {item}: {e}")
        dir.rmdir()

    @staticmethod
    def cleanup_inactive() -> None:
        """
        Clean up all inactive channels in the pubsub base directory.

        Inactive channels are those where the associated process is no longer running.
        This method removes their directories and any unconsumed messages to free up
        resources.
        """
        for path in Channel.inactive_paths():
            try:
                Channel._delete_recursive(path)
                logging.info(f"Cleaned up inactive channel at {path}")
            except OSError as e:
                logging.warning(f"Failed to clean up inactive channel at {path}: {e}")


    @staticmethod
    def active_paths() -> list[Path]:
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
            parts = item.name.split("_")
            if len(parts) < 3:
                continue
            pid = int(parts[-1])
            if is_process_running(pid):
                channels.append(item)

        return sorted(channels)

    @staticmethod
    def inactive_paths() -> list[Path]:
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
            parts = item.name.split("_")
            if len(parts) < 3:
                continue
            pid = int(parts[-1])
            if not is_process_running(pid):
                channels.append(item)

        return sorted(channels)

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
