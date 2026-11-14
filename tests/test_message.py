"""Tests for the Message class."""

import os
import threading
import time
import unittest
from unittest import mock

from pubsub.message import Header, Message


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

        # IDs should be unique even when created within the same millisecond
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

    def test_headers_empty(self):
        """Test message with no headers."""
        message = Message(topic="test", content=b"data")

        assert message.headers == {}
        assert isinstance(message.headers, dict)

        # Verify serialization preserves empty headers
        serialized = message.to_bytes()
        deserialized = Message.from_bytes(serialized)

        assert deserialized.headers == {}

    def test_headers_with_values(self):
        """Test message with headers."""
        headers : Header = {
            "content-type": "application/json",
            "priority": "high",
            "correlation-id": "12345"
        }
        message = Message(topic="test", content=b"data", headers=headers)

        assert message.headers == headers
        assert message.headers["content-type"] == "application/json"
        assert message.headers["priority"] == "high"

        # Verify serialization preserves headers
        serialized = message.to_bytes()
        deserialized = Message.from_bytes(serialized)

        assert deserialized.headers == headers
        assert deserialized.headers["content-type"] == "application/json"
        assert deserialized.headers["priority"] == "high"
        assert deserialized.headers["correlation-id"] == "12345"

    def test_headers_unicode_values(self):
        """Test message headers with unicode values."""
        headers : Header = {
            "user": "José García",
            "message": "Hello 世界 🌍"
        }
        message = Message(topic="test", content=b"data", headers=headers)

        # Verify serialization handles unicode in headers
        serialized = message.to_bytes()
        deserialized = Message.from_bytes(serialized)

        assert deserialized.headers == headers
        assert deserialized.headers["user"] == "José García"
        assert deserialized.headers["message"] == "Hello 世界 🌍"
        assert deserialized.id == message.id


class TestMessageId(unittest.TestCase):
    """Test cases for the message id generator."""

    SEQUENCE_BITS = 12
    PROCESS_BITS = 10

    def test_ids_are_unique_and_increasing_in_generation_order(self):
        ids = [Message._next_id() for _ in range(20_000)]  # many per millisecond

        assert len(set(ids)) == len(ids)
        assert ids == sorted(ids)

    def test_id_layout(self):
        before_ms = time.time_ns() // 1_000_000
        message_id = Message._next_id()
        after_ms = time.time_ns() // 1_000_000 + 1  # a burst may borrow the next millisecond

        id_ms = message_id >> (self.PROCESS_BITS + self.SEQUENCE_BITS)
        id_process = (message_id >> self.SEQUENCE_BITS) & ((1 << self.PROCESS_BITS) - 1)

        assert before_ms <= id_ms <= after_ms + 1
        assert id_process == os.getpid() & ((1 << self.PROCESS_BITS) - 1)
        assert 0 < message_id < 1 << 64

    def test_ids_are_unique_across_threads(self):
        results: list[list[int]] = []

        def generate():
            results.append([Message._next_id() for _ in range(5_000)])

        threads = [threading.Thread(target=generate) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        all_ids = [i for ids in results for i in ids]
        assert len(all_ids) == 8 * 5_000
        assert len(set(all_ids)) == len(all_ids)
        for ids in results:  # each thread sees increasing ids
            assert ids == sorted(ids)

    def test_ids_keep_increasing_when_the_clock_goes_backwards(self):
        first = Message._next_id()
        first_ms = first >> (self.PROCESS_BITS + self.SEQUENCE_BITS)

        with mock.patch("pubsub.message.time.time_ns", return_value=(first_ms - 5_000) * 1_000_000):
            second = Message._next_id()
            third = Message._next_id()

        assert first < second < third

    def test_sequence_overflow_moves_to_the_next_millisecond(self):
        frozen_ns = (time.time_ns() // 1_000_000 + 60_000) * 1_000_000  # a fresh millisecond

        with mock.patch("pubsub.message.time.time_ns", return_value=frozen_ns):
            ids = [Message._next_id() for _ in range((1 << self.SEQUENCE_BITS) * 2 + 10)]

        assert len(set(ids)) == len(ids)
        assert ids == sorted(ids)
        id_ms = {i >> (self.PROCESS_BITS + self.SEQUENCE_BITS) for i in ids}
        assert len(id_ms) == 3  # 4096 ids per millisecond, so 8202 ids span 3 milliseconds



class TestMessageFileName(unittest.TestCase):
    """Test cases for the zero-padded message file names."""

    def test_file_name_is_padded_to_20_digits(self):
        from pubsub.message import message_file_name

        assert message_file_name(1) == "00000000000000000001"
        assert message_file_name(0) == "0" * 20
        assert message_file_name((1 << 64) - 1) == "18446744073709551615"
        assert len(message_file_name(123456789)) == 20

    def test_string_order_is_numeric_order(self):
        from pubsub.message import message_file_name

        ids = [9, 10, 100, 1_000_000_000_000_000, (1 << 64) - 1, 2, 99]
        names = sorted(message_file_name(i) for i in ids)
        assert names == [message_file_name(i) for i in sorted(ids)]

    def test_round_trip(self):
        from pubsub.message import message_file_name, message_id_from_file_name

        for message_id in (0, 7, 10**15, (1 << 64) - 1):
            assert message_id_from_file_name(message_file_name(message_id)) == message_id

    def test_is_message_file_name(self):
        from pubsub.message import is_message_file_name, message_file_name

        assert is_message_file_name(message_file_name(5))
        assert not is_message_file_name("5")  # not padded
        assert not is_message_file_name("0" * 19)
        assert not is_message_file_name("0" * 21)
        assert not is_message_file_name("0" * 19 + "x")
        assert not is_message_file_name("." + "0" * 19)
        assert not is_message_file_name("queue")
        assert not is_message_file_name("٠" * 20)  # non-ASCII digits

    def test_invalid_ids_and_names(self):
        from pubsub.message import message_file_name, message_id_from_file_name

        with self.assertRaises(ValueError):
            message_file_name(-1)
        with self.assertRaises(ValueError):
            message_file_name(1 << 64)
        with self.assertRaises(ValueError):
            message_id_from_file_name("12")

    def test_message_file_name_property(self):
        from pubsub.message import message_file_name

        message = Message(topic="a.b", content=b"x")
        assert message.file_name == message_file_name(message.id)

    def test_id_time_is_in_the_upper_bits(self):
        from pubsub import message as message_module
        from pubsub.message import message_id_time_ms

        # Other tests may have pushed the generator ahead of the clock: start it afresh
        with mock.patch.object(message_module, "_last_id_ms", 0), mock.patch.object(
            message_module, "_id_sequence", 0
        ):
            before = int(time.time() * 1000)
            message = Message(topic="a.b", content=b"x")
            after = int(time.time() * 1000)
        assert before <= message_id_time_ms(message.id) <= after + 1
