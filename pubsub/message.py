"""Message class for pubsub library."""

from datetime import datetime, timezone
from typing import BinaryIO
import struct
import io
import time
import random
import json


# Message serialization format version
MESSAGE_FORMAT_VERSION = 1
SUPPORTED_MESSAGE_VERSIONS = [MESSAGE_FORMAT_VERSION]

# Magic number to identify message format ("PMSG" in ASCII)
MESSAGE_MAGIC_NUMBER = 0x504D5347


class Message:
    """Represents a message in the pubsub system."""
    
    def __init__(
        self,
        topic: str,
        content: bytes,
        headers: dict | None = None
    ):
        """
        Initialize a new message.
        
        Args:
            topic: The topic this message belongs to
            content: The message payload as bytes
            headers: Optional dictionary of string key-value pairs for metadata
        """
        self.id = self._next_id()
        self.timestamp = int(time.time() * 1_000_000)  # microseconds since epoch
        self.topic = topic
        self.content = content
        self.headers = headers if headers is not None else {}


    @staticmethod
    def _next_id() -> int:
        """
        Generate a unique message ID based on current time in microseconds
        with the least significant 16 bits replaced by random bits.
        
        This provides both time-based ordering and uniqueness even when
        multiple messages are created within the same microsecond.
        
        Returns:
            A 64-bit integer ID
        """
        time_micros = int(time.time() * 1_000_000)
        high_bits = (time_micros >> 16) << 16
        random_bits = random.randint(0, 0xFFFF)
        return high_bits | random_bits


    def write(self, stream: BinaryIO) -> None:
        """
        Write the message to a binary stream.
        
        Binary format:
        - 4 bytes: magic number (0x504D5347 - "PMSG")
        - 1 byte: format version (uint8)
        - 8 bytes: id (uint64)
        - 8 bytes: timestamp (uint64, microseconds since epoch)
        - 4 bytes: topic length (uint32)
        - N bytes: topic (UTF-8 encoded)
        - 4 bytes: headers JSON length (uint32)
        - N bytes: headers as JSON string (UTF-8 encoded)
        - 4 bytes: content length (uint32) 
        - N bytes: content
        
        Args:
            stream: Binary stream to write to
        """
        # Encode strings as UTF-8
        topic_bytes = self.topic.encode('utf-8')
        headers_json = json.dumps(self.headers, ensure_ascii=False)
        headers_bytes = headers_json.encode('utf-8')
        
        # Write each component to stream
        stream.write(struct.pack('!I', MESSAGE_MAGIC_NUMBER))
        stream.write(struct.pack('!B', MESSAGE_FORMAT_VERSION))
        stream.write(struct.pack('!Q', self.id))
        stream.write(struct.pack('!Q', self.timestamp))
        stream.write(struct.pack('!I', len(topic_bytes)))
        stream.write(topic_bytes)
        stream.write(struct.pack('!I', len(headers_bytes)))
        stream.write(headers_bytes)
        stream.write(struct.pack('!I', len(self.content)))
        stream.write(self.content)
    
    
    @staticmethod
    def _read_exact(stream: BinaryIO, n: int) -> bytes:
        """
        Read exactly n bytes from stream, handling partial reads gracefully.
        
        Continues reading until all requested bytes are received or EOF is encountered.
        This handles cases where streams (sockets, pipes) return data in chunks.
        
        Args:
            stream: Stream to read from
            n: Number of bytes to read
            
        Returns:
            Exactly n bytes
            
        Raises:
            ValueError: If EOF is reached before reading all bytes
        """
        chunks = []
        bytes_read = 0
        while bytes_read < n:
            chunk = stream.read(n - bytes_read)
            if not chunk:
                # EOF reached - no more data available
                raise ValueError(f"Expected {n} bytes, but only read {bytes_read} bytes (EOF)")
            chunks.append(chunk)
            bytes_read += len(chunk)
        
        return b''.join(chunks)    
    
    @classmethod
    def read(cls, stream: BinaryIO) -> 'Message':
        """
        Read and deserialize a message from a binary stream.
        
        Args:
            stream: Binary stream to read from
            
        Returns:
            A new Message instance
        """
        # Read and validate magic number
        magic_data = cls._read_exact(stream, 4)
        magic = struct.unpack('!I', magic_data)[0]
        
        if magic != MESSAGE_MAGIC_NUMBER:
            raise ValueError(f"Invalid magic number 0x{magic:08X}, expected 0x{MESSAGE_MAGIC_NUMBER:08X}. This data is not a valid message.")
        
        # Read and validate format version
        version_data = cls._read_exact(stream, 1)
        version = struct.unpack('!B', version_data)[0]
        
        if version not in SUPPORTED_MESSAGE_VERSIONS:
            raise ValueError(f"Unsupported message format version {version}, expected one of {SUPPORTED_MESSAGE_VERSIONS}.")
        
        # Read id
        id_data = cls._read_exact(stream, 8)
        message_id = struct.unpack('!Q', id_data)[0]
        
        # Read timestamp
        timestamp_data = cls._read_exact(stream, 8)
        message_timestamp = struct.unpack('!Q', timestamp_data)[0]
        
        # Read topic
        topic_length_data = cls._read_exact(stream, 4)
        topic_length = struct.unpack('!I', topic_length_data)[0]
        topic_data = cls._read_exact(stream, topic_length)
        topic = topic_data.decode('utf-8')
        
        # Read headers
        headers_length_data = cls._read_exact(stream, 4)
        headers_length = struct.unpack('!I', headers_length_data)[0]
        headers_data = cls._read_exact(stream, headers_length)
        headers_json = headers_data.decode('utf-8')
        headers = json.loads(headers_json) if headers_json else {}
        
        # Read data
        data_length_data = cls._read_exact(stream, 4)
        data_length = struct.unpack('!I', data_length_data)[0]
        message_content = cls._read_exact(stream, data_length)
        
        # Create new instance and set the id and timestamp directly
        message = cls(
            topic=topic,
            content=message_content,
            headers=headers
        )
        message.id = message_id
        message.timestamp = message_timestamp
        return message


    def to_bytes(self) -> bytes:
        """
        Convenience method to serialize message to bytes.
        
        Returns:
            The serialized message as bytes
        """
        stream = io.BytesIO()
        self.write(stream)
        return stream.getvalue()
    
    @classmethod
    def from_bytes(cls, data: bytes) -> 'Message':
        """
        Convenience method to deserialize message from bytes.
        
        Args:
            data: The serialized message bytes
            
        Returns:
            A new Message instance
        """
        stream = io.BytesIO(data)
        return cls.read(stream)
    

    def __repr__(self) -> str:
        return f"Message(id={self.id}, topic='{self.topic}', content_length={len(self.content)})"
