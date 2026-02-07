#!/usr/bin/env python3
"""Test script for binary serialization/deserialization."""

import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from pubsub.message import Message
from datetime import datetime, timezone

def test_basic_serialization():
    """Test basic serialization and deserialization."""
    print("Testing basic serialization...")
    
    # Create a test message
    original_message = Message(
        topic="test.topic",
        data=b"Hello, World!",
        headers={"priority": "high", "version": 1.0}
    )
    
    print(f"Original message: {original_message}")
    print(f"Topic: {original_message.topic}")
    print(f"Data: {original_message.data}")
    print(f"Headers: {original_message.headers}")
    print(f"Message ID: {original_message.message_id}")
    print(f"Timestamp: {original_message.timestamp}")
    
    # Serialize to bytes
    serialized = original_message.to_bytes()
    print(f"Serialized size: {len(serialized)} bytes")
    
    # Deserialize from bytes
    deserialized_message = Message.from_bytes(serialized)
    
    print(f"\nDeserialized message: {deserialized_message}")
    print(f"Topic: {deserialized_message.topic}")
    print(f"Data: {deserialized_message.data}")
    print(f"Headers: {deserialized_message.headers}")
    print(f"Message ID: {deserialized_message.message_id}")
    print(f"Timestamp: {deserialized_message.timestamp}")
    
    # Verify they match
    assert original_message.topic == deserialized_message.topic
    assert original_message.data == deserialized_message.data
    assert original_message.headers == deserialized_message.headers
    assert original_message.message_id == deserialized_message.message_id
    # Compare timestamps with some tolerance for precision
    timestamp_diff = abs((original_message.timestamp - deserialized_message.timestamp).total_seconds())
    assert timestamp_diff < 0.001  # Less than 1ms difference
    
    print("\n✅ Basic serialization test passed!")

def test_edge_cases():
    """Test edge cases."""
    print("\nTesting edge cases...")
    
    # Empty data
    msg1 = Message("empty.topic", b"")
    serialized1 = msg1.to_bytes()
    deserialized1 = Message.from_bytes(serialized1)
    assert msg1.data == deserialized1.data
    print("✅ Empty data test passed!")
    
    # Binary data
    msg2 = Message("binary.topic", b"\x00\x01\x02\xff\xfe\xfd")
    serialized2 = msg2.to_bytes()
    deserialized2 = Message.from_bytes(serialized2)
    assert msg2.data == deserialized2.data
    print("✅ Binary data test passed!")
    
    # Unicode topic
    msg3 = Message("unicode.测试.topic", b"test data")
    serialized3 = msg3.to_bytes()
    deserialized3 = Message.from_bytes(serialized3)
    assert msg3.topic == deserialized3.topic
    print("✅ Unicode topic test passed!")
    
    # Complex headers
    msg4 = Message("complex.topic", b"data", headers={
        "nested": {"key": "value"},
        "list": [1, 2, 3],
        "special_chars": "特殊字符"
    })
    serialized4 = msg4.to_bytes()
    deserialized4 = Message.from_bytes(serialized4)
    assert msg4.headers == deserialized4.headers
    print("✅ Complex headers test passed!")

if __name__ == "__main__":
    try:
        test_basic_serialization()
        test_edge_cases()
        print("\n🎉 All tests passed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)