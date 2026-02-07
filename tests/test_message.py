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
        message2 = Message(topic="test", content=b"data2")
        
        # IDs should be unique (random bits ensure this even in same microsecond)
        assert message1.id != message2.id
        
        # IDs should generally increase over time (high bits are time-based)
        # Note: Due to random low bits, exact ordering within same microsecond is not guaranteed
    
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
        """Test message timestamp field."""
        # Create message and capture creation time with some tolerance
        before = time.time() - 0.01  # Add 10ms buffer before
        message = Message(topic="test", content=b"data")
        after = time.time() + 0.01  # Add 10ms buffer after
        
        # Get timestamp (now an integer in microseconds)
        timestamp = message.timestamp
        
        # Verify it's an integer
        assert isinstance(timestamp, int)
        assert timestamp > 0
        
        # Convert to seconds for comparison
        timestamp_seconds = timestamp / 1_000_000
        assert before <= timestamp_seconds <= after
        
        # Test that timestamp is preserved through serialization
        serialized = message.to_bytes()
        deserialized = Message.from_bytes(serialized)
        
        assert deserialized.timestamp == message.timestamp
        assert isinstance(deserialized.timestamp, int)
        
        assert deserialized.timestamp == message.timestamp
        assert deserialized.id == message.id