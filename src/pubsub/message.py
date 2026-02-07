"""Message class for pubsub library."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, BinaryIO
import uuid
import struct
import json
import io


# Message serialization format version
MESSAGE_FORMAT_VERSION = 1

# Magic number to identify message format ("PMSG" in ASCII)
MESSAGE_MAGIC_NUMBER = 0x504D5347


class Message:
    """Represents a message in the pubsub system."""
    
    def __init__(
        self,
        topic: str,
        data: bytes,
        message_id: Optional[uuid.UUID] = None,
        timestamp: Optional[datetime] = None,
        headers: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize a new message.
        
        Args:
            topic: The topic this message belongs to
            data: The message payload as bytes
            message_id: Unique GUID identifier for this message (auto-generated if not provided)
            timestamp: When the message was created
            headers: Optional metadata headers
        """
        self.topic = topic
        self.data = data
        self.message_id = message_id or uuid.uuid4()
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.headers = headers or {}
    
    def __repr__(self) -> str:
        return f"Message(topic='{self.topic}', data_length={len(self.data)})"
    
    def write(self, stream: BinaryIO) -> None:
        """
        Write the message to a binary stream.
        
        Binary format:
        - 4 bytes: magic number (0x504D5347 - "PMSG")
        - 1 byte: format version (uint8)
        - 4 bytes: topic length (uint32)
        - N bytes: topic (UTF-8 encoded)
        - 4 bytes: data length (uint32) 
        - N bytes: data
        - 16 bytes: message_id (UUID as binary)
        - 8 bytes: timestamp (uint64, microseconds since epoch)
        - 4 bytes: headers length (uint32)
        - N bytes: headers (JSON encoded as UTF-8)
        
        Args:
            stream: Binary stream to write to
        """
        # Encode strings as UTF-8
        topic_bytes = self.topic.encode('utf-8')
        
        # Convert timestamp to microseconds since epoch
        timestamp_microseconds = int(self.timestamp.timestamp() * 1_000_000)
        
        # Encode headers as JSON
        headers_json = json.dumps(self.headers, default=str).encode('utf-8')
        
        # Write each component to stream
        stream.write(struct.pack('!I', MESSAGE_MAGIC_NUMBER))
        stream.write(struct.pack('!B', MESSAGE_FORMAT_VERSION))
        stream.write(struct.pack('!I', len(topic_bytes)))
        stream.write(topic_bytes)
        stream.write(struct.pack('!I', len(self.data)))
        stream.write(self.data)
        stream.write(self.message_id.bytes)
        stream.write(struct.pack('!Q', timestamp_microseconds))
        stream.write(struct.pack('!I', len(headers_json)))
        stream.write(headers_json)
    
    @staticmethod
    def _read_exact(stream: BinaryIO, n: int) -> bytes:
        """
        Read exactly n bytes from stream, raising ValueError if EOF is reached.
        
        Args:
            stream: Stream to read from
            n: Number of bytes to read
            
        Returns:
            Exactly n bytes
            
        Raises:
            ValueError: If unable to read n bytes (EOF or stream error)
        """
        data = stream.read(n)
        if len(data) != n:
            raise ValueError(f"Expected {n} bytes, but only read {len(data)} bytes (EOF?)")
        return data
    
    @classmethod
    def read(cls, stream: BinaryIO) -> 'Message':
        """
        Read and deserialize a message from a binary stream.
        
        Args:
            stream: Binary stream to read from
            
        Returns:
            A new Message instance
            
        Raises:
            ValueError: If the stream data is corrupted, incomplete, or has wrong format
            UnicodeDecodeError: If string data cannot be decoded
        """
        try:
            # Read and validate magic number
            magic_data = cls._read_exact(stream, 4)
            magic = struct.unpack('!I', magic_data)[0]
            
            if magic != MESSAGE_MAGIC_NUMBER:
                raise ValueError(f"Invalid magic number 0x{magic:08X}, expected 0x{MESSAGE_MAGIC_NUMBER:08X}. This data is not a valid message.")
            
            # Read and validate format version
            version_data = cls._read_exact(stream, 1)
            version = struct.unpack('!B', version_data)[0]
            
            if version != MESSAGE_FORMAT_VERSION:
                raise ValueError(f"Unsupported message format version {version}, expected {MESSAGE_FORMAT_VERSION}")
            
            # Read topic
            topic_length_data = cls._read_exact(stream, 4)
            topic_length = struct.unpack('!I', topic_length_data)[0]
            topic_data = cls._read_exact(stream, topic_length)
            topic = topic_data.decode('utf-8')
            
            # Read data
            data_length_data = cls._read_exact(stream, 4)
            data_length = struct.unpack('!I', data_length_data)[0]
            message_data = cls._read_exact(stream, data_length)
            
            # Read message_id
            message_id_data = cls._read_exact(stream, 16)
            message_id = uuid.UUID(bytes=message_id_data)
            
            # Read timestamp
            timestamp_data = cls._read_exact(stream, 8)
            timestamp_microseconds = struct.unpack('!Q', timestamp_data)[0]
            timestamp = datetime.fromtimestamp(
                timestamp_microseconds / 1_000_000, tz=timezone.utc
            )
            
            # Read headers
            headers_length_data = cls._read_exact(stream, 4)
            headers_length = struct.unpack('!I', headers_length_data)[0]
            headers_json_data = cls._read_exact(stream, headers_length)
            headers_json = headers_json_data.decode('utf-8')
            headers = json.loads(headers_json)
            
            return cls(
                topic=topic,
                data=message_data,
                message_id=message_id,
                timestamp=timestamp,
                headers=headers
            )
            
        except (struct.error, json.JSONDecodeError) as e:
            raise ValueError(f"Invalid message format: {e}") from e
    
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