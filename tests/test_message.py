"""Tests for the Message class."""

import unittest
import time
from datetime import datetime, timezone
from pubsub.message import Message


class TestMessage(unittest.TestCase):
    """Test cases for Message class."""
    
    def test_message_creation(self):
        """Test basic message creation."""
        topic = "test.topic"
        data = b"Hello, World!"
        
        message = Message(topic=topic, content=data)
        
        assert message.topic == topic
        assert message.content == data
        assert message.id > 0
    
    def test_message_id_uniqueness(self):
        """Test that message IDs are unique."""
        message1 = Message(topic="test", content=b"data1")
        #time.sleep(0.001)  # Small delay to ensure different timestamps
        message2 = Message(topic="test", content=b"data2")
        
        assert message1.id != message2.id
        assert message1.id < message2.id  # Later message should have higher ID
    
    def test_binary_serialization(self):
        """Test message serialization to bytes."""
        topic = "test.topic"
        data = b"test data with \x00 null bytes"
        
        original_message = Message(topic=topic, content=data)
        
        # Serialize to bytes
        serialized = original_message.to_bytes()
        assert isinstance(serialized, bytes)
        assert len(serialized) > 0
        
        # Deserialize from bytes
        deserialized = Message.from_bytes(serialized)
        
        assert deserialized.topic == original_message.topic
        assert deserialized.content == original_message.content
        assert deserialized.id == original_message.id
    
    def test_empty_data(self):
        """Test message with empty data."""
        message = Message(topic="empty.test", content=b"")
        
        assert message.topic == "empty.test"
        assert message.content == b""
        assert len(message.content) == 0
        
        # Test serialization with empty data
        serialized = message.to_bytes()
        deserialized = Message.from_bytes(serialized)
        
        assert deserialized.content == b""
    
    def test_unicode_topic(self):
        """Test message with unicode characters in topic."""
        topic = "test.unicode.тест.🚀"
        data = b"unicode test data"
        
        message = Message(topic=topic, content=data)
        
        assert message.topic == topic
        
        # Test serialization with unicode topic
        serialized = message.to_bytes()
        deserialized = Message.from_bytes(serialized)
        
        assert deserialized.topic == topic
        assert deserialized.content == data
    
    def test_repr(self):
        """Test message string representation."""
        message = Message(topic="test.topic", content=b"Hello, World!")
        
        repr_str = repr(message)
        
        assert "Message" in repr_str
        assert "test.topic" in repr_str
        assert "content_length=13" in repr_str
    
    def test_timestamp(self):
        """Test message timestamp property."""
        # Create message and capture creation time with some tolerance
        before = time.time() - 0.01  # Add 10ms buffer before
        message = Message(topic="test", content=b"data")
        after = time.time() + 0.01  # Add 10ms buffer after
        
        # Get timestamp from property
        timestamp = message.timestamp
        
        # Verify it's a datetime object
        assert isinstance(timestamp, datetime)
        assert timestamp.tzinfo == timezone.utc
        
        # Verify timestamp is within the expected range
        timestamp_seconds = timestamp.timestamp()
        assert before <= timestamp_seconds <= after
        
        # Verify timestamp matches the id
        expected_timestamp = datetime.fromtimestamp(message.id / 1_000_000, tz=timezone.utc)
        assert timestamp == expected_timestamp
        
        # Test that timestamp is preserved through serialization
        serialized = message.to_bytes()
        deserialized = Message.from_bytes(serialized)
        
        assert deserialized.timestamp == message.timestamp
        assert deserialized.id == message.id