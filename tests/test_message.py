"""Tests for the Message class."""

import pytest
from datetime import datetime
from pubsub.message import Message


class TestMessage:
    """Test cases for Message class."""
    
    def test_message_creation(self):
        """Test basic message creation."""
        topic = "test.topic"
        data = {"key": "value"}
        
        message = Message(topic=topic, data=data)
        
        assert message.topic == topic
        assert message.data == data
        assert message.message_id is not None
        assert isinstance(message.timestamp, datetime)
        assert message.headers == {}
    
    def test_message_with_custom_fields(self):
        """Test message creation with custom fields."""
        topic = "test.topic"
        data = {"key": "value"}
        message_id = "custom-id-123"
        timestamp = datetime(2023, 1, 1, 12, 0, 0)
        headers = {"source": "test"}
        
        message = Message(
            topic=topic,
            data=data,
            message_id=message_id,
            timestamp=timestamp,
            headers=headers
        )
        
        assert message.topic == topic
        assert message.data == data
        assert message.message_id == message_id
        assert message.timestamp == timestamp
        assert message.headers == headers
    
    def test_to_dict(self):
        """Test message serialization to dict."""
        message = Message(
            topic="test.topic",
            data={"key": "value"},
            message_id="test-id",
            headers={"source": "test"}
        )
        
        result = message.to_dict()
        
        assert result["topic"] == "test.topic"
        assert result["data"] == {"key": "value"}
        assert result["message_id"] == "test-id"
        assert "timestamp" in result
        assert result["headers"] == {"source": "test"}
    
    def test_from_dict(self):
        """Test message creation from dict."""
        data = {
            "topic": "test.topic",
            "data": {"key": "value"},
            "message_id": "test-id",
            "timestamp": "2023-01-01T12:00:00",
            "headers": {"source": "test"}
        }
        
        message = Message.from_dict(data)
        
        assert message.topic == "test.topic"
        assert message.data == {"key": "value"}
        assert message.message_id == "test-id"
        assert message.timestamp == datetime(2023, 1, 1, 12, 0, 0)
        assert message.headers == {"source": "test"}
    
    def test_repr(self):
        """Test message string representation."""
        message = Message(
            topic="test.topic",
            data={"key": "value"},
            message_id="test-id-123456789"
        )
        
        repr_str = repr(message)
        
        assert "Message" in repr_str
        assert "test.topic" in repr_str
        assert "test-id-1" in repr_str  # First 8 chars of ID