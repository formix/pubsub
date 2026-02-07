"""Tests for the Message class."""

import unittest
import time
from pubsub.message import Message


class TestMessage(unittest.TestCase):
    """Test cases for Message class."""
    
    def test_message_creation(self):
        """Test basic message creation."""
        topic = "test.topic"
        data = b"Hello, World!"
        
        message = Message(topic=topic, data=data)
        
        assert message.topic == topic
        assert message.data == data
        assert message.id is not None
        assert isinstance(message.id, int)
        assert message.headers == {}
    
    def test_message_with_headers(self):
        """Test message creation with headers."""
        topic = "test.topic"
        data = b"test data"
        headers = {"source": "test", "priority": "high"}
        
        message = Message(
            topic=topic,
            data=data,
            headers=headers
        )
        
        assert message.topic == topic
        assert message.data == data
        assert message.id is not None
        assert message.headers == headers
    
    def test_message_id_uniqueness(self):
        """Test that message IDs are unique."""
        message1 = Message(topic="test", data=b"data1")
        time.sleep(0.001)  # Small delay to ensure different timestamps
        message2 = Message(topic="test", data=b"data2")
        
        assert message1.id != message2.id
        assert message1.id < message2.id  # Later message should have higher ID
    
    def test_binary_serialization(self):
        """Test message serialization to bytes."""
        topic = "test.topic"
        data = b"test data with \x00 null bytes"
        headers = {"key": "value", "number": 42}
        
        original_message = Message(topic=topic, data=data, headers=headers)
        
        # Serialize to bytes
        serialized = original_message.to_bytes()
        assert isinstance(serialized, bytes)
        assert len(serialized) > 0
        
        # Deserialize from bytes
        deserialized = Message.from_bytes(serialized)
        
        assert deserialized.topic == original_message.topic
        assert deserialized.data == original_message.data
        assert deserialized.id == original_message.id
        assert deserialized.headers == original_message.headers
    
    def test_empty_data(self):
        """Test message with empty data."""
        message = Message(topic="empty.test", data=b"")
        
        assert message.topic == "empty.test"
        assert message.data == b""
        assert len(message.data) == 0
        
        # Test serialization with empty data
        serialized = message.to_bytes()
        deserialized = Message.from_bytes(serialized)
        
        assert deserialized.data == b""
    
    def test_unicode_topic(self):
        """Test message with unicode characters in topic."""
        topic = "test.unicode.тест.🚀"
        data = b"unicode test data"
        
        message = Message(topic=topic, data=data)
        
        assert message.topic == topic
        
        # Test serialization with unicode topic
        serialized = message.to_bytes()
        deserialized = Message.from_bytes(serialized)
        
        assert deserialized.topic == topic
        assert deserialized.data == data
    
    def test_complex_headers(self):
        """Test message with complex headers."""
        headers = {
            "string": "value",
            "number": 42,
            "float": 3.14,
            "bool": True,
            "list": [1, 2, 3],
            "nested": {"key": "value"}
        }
        
        message = Message(topic="test", data=b"data", headers=headers)
        
        # Test serialization with complex headers
        serialized = message.to_bytes()
        deserialized = Message.from_bytes(serialized)
        
        assert deserialized.headers == headers
    
    def test_repr(self):
        """Test message string representation."""
        message = Message(topic="test.topic", data=b"Hello, World!")
        
        repr_str = repr(message)
        
        assert "Message" in repr_str
        assert "test.topic" in repr_str
        assert "data_length=13" in repr_str