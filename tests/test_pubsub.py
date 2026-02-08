"""Tests for the PubSub module."""

import multiprocessing
import threading
import time
import unittest

from pubsub.channel import Channel
from pubsub.pubsub import fetch, publish, subscribe


class TestPublish(unittest.TestCase):
    """Test cases for publish function."""

    def test_publish_to_exact_match(self):
        """Test publishing to a channel with exact topic match."""
        topic = "test.publish.exact"
        channel = Channel(topic=topic)

        with channel:
            data = b"test message"
            count = publish(topic, data)

            assert count == 1

            # Verify message file was created
            files = list(channel.directory_path.glob("*"))
            message_files = [f for f in files if f.name != "queue"]
            assert len(message_files) == 1

    def test_publish_to_multiple_channels(self):
        """Test publishing to multiple channels with same topic."""
        topic = "test.publish.multi"
        channel1 = Channel(topic=topic)
        channel2 = Channel(topic=topic)
        channel3 = Channel(topic=topic)

        with channel1, channel2, channel3:
            data = b"broadcast message"
            count = publish(topic, data)

            assert count == 3

            # Each channel should have the message file
            for channel in [channel1, channel2, channel3]:
                files = list(channel.directory_path.glob("*"))
                message_files = [f for f in files if f.name != "queue"]
                assert len(message_files) == 1

    def test_publish_with_wildcard_match(self):
        """Test publishing with wildcard matching."""
        wildcard_topic = "test.+"
        channel = Channel(topic=wildcard_topic)

        with channel:
            data = b"wildcard message"
            count = publish("test.specific.topic", data)

        assert count >= 1

    def test_publish_no_matching_channels(self):
        """Test publishing when no channels match."""
        data = b"no one listening"
        count = publish("non.existent.topic", data)

        assert count == 0

    def test_publish_empty_data(self):
        """Test publishing empty data."""
        topic = "test.empty"
        channel = Channel(topic=topic)

        with channel:
            data = b""
            count = publish(topic, data)

        assert count == 1

    def test_publish_large_data(self):
        """Test publishing large data payload."""
        topic = "test.large"
        channel = Channel(topic=topic)

        with channel:
            data = b"x" * 1024 * 1024  # 1MB
            count = publish(topic, data)

        assert count == 1

    def test_publish_unicode_topic(self):
        """Test that unicode characters in topic raise ValueError."""
        topic = "test.unicode.тест"

        # Should raise ValueError due to invalid characters
        with self.assertRaises(ValueError) as context:
            _ = Channel(topic=topic)

        assert "invalid characters" in str(context.exception).lower()

    def test_publish_with_wildcard_equals(self):
        """Test that publishing to a topic with = wildcard raises ValueError."""
        topic = "test.=.invalid"

        with self.assertRaises(ValueError) as context:
            publish(topic, b"test data")

        # Verify error message mentions allowed characters
        assert "a-zA-Z0-9.-" in str(context.exception) or \
               "alphanumeric" in str(context.exception).lower()

    def test_publish_with_wildcard_plus(self):
        """Test that publishing to a topic with + wildcard raises ValueError."""
        topic = "test.+"

        with self.assertRaises(ValueError) as context:
            publish(topic, b"test data")

        # Verify error message mentions allowed characters
        assert "a-zA-Z0-9.-" in str(context.exception) or \
               "alphanumeric" in str(context.exception).lower()


class TestFetch(unittest.TestCase):
    """Test cases for fetch function."""

    def test_fetch_single_message(self):
        """Test fetching a single message."""
        topic = "test.fetch.single"
        channel = Channel(topic=topic)
        with channel:
            # Publish a message
            data = b"fetch me"
            count = publish(topic, data)
            assert count == 1

            # Fetch the message
            message = fetch(channel)

            assert message is not None
            assert message.topic == topic
            assert message.content == data

    def test_fetch_no_message(self):
        """Test fetching when no message is available."""
        topic = "test.fetch.empty"
        channel = Channel(topic=topic)

        with channel:
            # Don't publish anything
            message = fetch(channel)

            assert message is None

    def test_fetch_multiple_messages(self):
        """Test fetching multiple messages in sequence."""
        topic = "test.fetch.multiple"
        channel = Channel(topic=topic)

        with channel:
            # Publish multiple messages
            data1 = b"message 1"
            data2 = b"message 2"
            data3 = b"message 3"
            publish(topic, data1)
            publish(topic, data2)
            publish(topic, data3)

            # Fetch all messages
            message1 = fetch(channel)
            message2 = fetch(channel)
            message3 = fetch(channel)
            message4 = fetch(channel)

            assert message1 is not None
            assert message2 is not None
            assert message3 is not None
            assert message4 is None  # No more messages

            # Messages should have correct content
            assert message1.content == data1
            assert message2.content == data2
            assert message3.content == data3

    def test_fetch_removes_message_file(self):
        """Test that fetch removes the message file after reading."""
        topic = "test.fetch.cleanup"
        channel = Channel(topic=topic)

        with channel:
            # Publish a message
            data = b"cleanup test"
            publish(topic, data)

            # Check message file exists
            files_before = list(channel.directory_path.glob("*"))
            message_files_before = [f for f in files_before if f.name != "queue"]
            assert len(message_files_before) == 1

            # Fetch the message
            message = fetch(channel)
            assert message is not None

            # Check message file is removed
            files_after = list(channel.directory_path.glob("*"))
            message_files_after = [f for f in files_after if f.name != "queue"]
            assert len(message_files_after) == 0

    def test_fetch_preserves_message_attributes(self):
        """Test that fetched message preserves all attributes."""
        topic = "test.fetch.attrs"
        channel = Channel(topic=topic)

        with channel:
            # Publish a message
            data = b"attribute test"
            publish(topic, data)

            # Fetch the message
            message = fetch(channel)

            assert message is not None
            assert message.topic == topic
            assert message.content == data
            assert message.id > 0
            assert message.timestamp > 0

    def test_fetch_with_empty_content(self):
        """Test fetching message with empty content."""
        topic = "test.fetch.empty.content"
        channel = Channel(topic=topic)

        with channel:
            # Publish empty message
            publish(topic, b"")

            # Fetch it
            message = fetch(channel)

            assert message is not None
            assert message.content == b""


class TestSubscribe(unittest.TestCase):
    """Test cases for subscribe function."""

    def setUp(self):
        """Set up test fixtures."""
        self.received_messages = []

    def tearDown(self):
        """Clean up test fixtures."""
        self.received_messages.clear()

    def test_subscribe_receives_messages(self):
        """Test that subscribe receives published messages."""
        topic = "test.subscribe.receive"
        channel = Channel(topic=topic)

        with channel:
            # Publish messages in a separate thread
            def publisher():
                time.sleep(0.05)  # Small delay to ensure subscriber is ready
                publish(topic, b"message 1")
                publish(topic, b"message 2")
                publish(topic, b"message 3")

            pub_thread = threading.Thread(target=publisher)
            pub_thread.start()

            # Subscribe with a callback
            def callback(message):
                self.received_messages.append(message)

            count = subscribe(channel, callback, timeout_seconds=0.5)
            pub_thread.join()

            assert count == 3
            assert len(self.received_messages) == 3
            assert self.received_messages[0].content == b"message 1"
            assert self.received_messages[1].content == b"message 2"
            assert self.received_messages[2].content == b"message 3"

    def test_subscribe_timeout(self):
        """Test that subscribe respects timeout."""
        topic = "test.subscribe.timeout"
        channel = Channel(topic=topic)

        with channel:
            # Don't publish anything
            def callback(message):
                self.received_messages.append(message)

            start_time = time.time()
            count = subscribe(channel, callback, timeout_seconds=0.2)
            elapsed = time.time() - start_time

            assert count == 0
            assert 0.15 <= elapsed <= 0.3  # Allow some tolerance

    def test_subscribe_negative_timeout(self):
        """Test that subscribe raises error for negative timeout."""
        topic = "test.subscribe.negative"
        channel = Channel(topic=topic)

        def callback(message):
            pass

        with self.assertRaises(ValueError) as context:
            subscribe(channel, callback, timeout_seconds=-1)
        assert "non-negative" in str(context.exception)

    def test_subscribe_callback_exception(self):
        """Test that subscribe continues on callback exception."""
        topic = "test.subscribe.exception"
        channel = Channel(topic=topic)

        with channel:
            # Publish messages in a separate thread
            def publisher():
                time.sleep(0.05)
                publish(topic, b"message 1")
                publish(topic, b"message 2")

            pub_thread = threading.Thread(target=publisher)
            pub_thread.start()

            # Callback that raises exception on first message
            call_count = [0]
            def callback(message):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise RuntimeError("Test exception")
                self.received_messages.append(message)

            count = subscribe(channel, callback, timeout_seconds=0.5)
            pub_thread.join()

            # Should process both messages despite exception
            assert count == 2
            assert len(self.received_messages) == 1  # Only second message added

    def test_subscribe_zero_timeout_exits_quickly(self):
        """Test that timeout=0 means listen indefinitely (needs manual stop)."""
        topic = "test.subscribe.zero"

        def subscriber_process(topic, timeout):
            """Subprocess that subscribes with given timeout."""
            channel = Channel(topic=topic)
            received_messages = []

            with channel:
                def callback(message):
                    received_messages.append(message)

                subscribe(channel, callback, timeout_seconds=timeout)

            # Process will exit naturally when subscribe completes

        # Start subscriber in subprocess with short timeout
        proc = multiprocessing.Process(target=subscriber_process, args=(topic, 0.1))
        proc.start()
        proc.join(timeout=0.3)

        # Process should have completed
        assert not proc.is_alive()


class TestIntegration(unittest.TestCase):
    """Integration tests for publish-subscribe flow."""

    def test_pub_sub_flow(self):
        """Test complete publish-subscribe flow."""
        topic = "test.integration.flow"

        def subscriber_process(topic, result_queue):
            """Subprocess that subscribes and reports results."""
            channel = Channel(topic=topic)
            received = []

            with channel:
                def callback(message):
                    received.append({"content": message.content.decode(), "topic": message.topic})
                subscribe(channel, callback, timeout_seconds=1.0)

            # Send results back to parent
            result_queue.put(received)

        # Create queue for results
        result_queue = multiprocessing.Queue()

        # Start subscriber in subprocess
        sub_proc = multiprocessing.Process(target=subscriber_process, args=(topic, result_queue))
        sub_proc.start()

        # Publish messages
        time.sleep(0.1)  # Ensure subscriber is ready
        publish(topic, b"Hello")
        publish(topic, b"World")

        # Wait for subprocess to finish
        sub_proc.join()

        # Get results from queue
        received = result_queue.get(timeout=1)

        assert len(received) == 2
        assert received[0]["content"] == "Hello"
        assert received[1]["content"] == "World"

    def test_multiple_subscribers(self):
        """Test multiple subscribers to same topic."""
        topic = "test.integration.multi"

        def subscriber_process(topic, result_queue, subscriber_id):
            """Subprocess that subscribes and reports results."""
            channel = Channel(topic=topic)
            received = []

            with channel:
                def callback(message):
                    received.append(message.content.decode())
                subscribe(channel, callback, timeout_seconds=1.0)

            # Send results back to parent
            result_queue.put({"id": subscriber_id, "received": received})

        # Create queue for results
        result_queue = multiprocessing.Queue()

        # Start two subscribers in separate subprocesses
        sub1_proc = multiprocessing.Process(target=subscriber_process,
                                            args=(topic, result_queue, 1))
        sub2_proc = multiprocessing.Process(target=subscriber_process,
                                            args=(topic, result_queue, 2))
        sub1_proc.start()
        sub2_proc.start()

        # Publish messages
        time.sleep(0.1)
        data = b"Broadcast message"
        count = publish(topic, data)

        # Wait for subprocesses
        sub1_proc.join()
        sub2_proc.join()

        # Get results from queue
        results = [result_queue.get(timeout=1) for _ in range(2)]
        received1 = next(r["received"] for r in results if r["id"] == 1)
        received2 = next(r["received"] for r in results if r["id"] == 2)

        # Both should receive the message
        assert count == 2
        assert len(received1) >= 1
        assert len(received2) >= 1
        assert received1[0] == "Broadcast message"
        assert received2[0] == "Broadcast message"

    def test_message_order(self):
        """Test that messages are received in order."""
        topic = "test.integration.order"

        def subscriber_process(topic, result_queue):
            """Subprocess that subscribes and reports results in order."""
            channel = Channel(topic=topic)
            received = []

            with channel:
                def callback(message):
                    received.append(message.content.decode())
                subscribe(channel, callback, timeout_seconds=1.5)

            # Send results back to parent
            result_queue.put(received)

        # Create queue for results
        result_queue = multiprocessing.Queue()

        # Start subscriber in subprocess
        sub_proc = multiprocessing.Process(target=subscriber_process, args=(topic, result_queue))
        sub_proc.start()

        # Publish multiple messages
        time.sleep(0.1)
        for i in range(10):
            publish(topic, f"message {i}".encode())
            time.sleep(0.01)  # Small delay between publishes

        # Wait for subscriber
        sub_proc.join()

        # Get results from queue
        received = result_queue.get(timeout=1)

        # Check order
        assert len(received) == 10
        for i in range(10):
            assert received[i] == f"message {i}"

    def test_publish_before_subscribe(self):
        """Test that messages published before subscribe can be fetched."""
        topic = "test.integration.prebuffer"
        channel = Channel(topic=topic)

        with channel:
            # Publish messages BEFORE subscribing
            publish(topic, b"early message 1")
            publish(topic, b"early message 2")

            received = []

            def callback(message):
                received.append(message)

            # Now subscribe
            subscribe(channel, callback, timeout_seconds=0.3)

            # Should have received the buffered messages
            assert len(received) == 2
            assert received[0].content == b"early message 1"
            assert received[1].content == b"early message 2"

    def test_mixed_topics_no_crosstalk(self):
        """Test that messages don't leak between different topics."""
        topic1 = "test.integration.topic1"
        topic2 = "test.integration.topic2"

        def subscriber_process(topic, result_queue, topic_id):
            """Subprocess that subscribes and reports results."""
            channel = Channel(topic=topic)
            received = []

            with channel:
                def callback(message):
                    received.append({"content": message.content.decode(), "topic": message.topic})
                subscribe(channel, callback, timeout_seconds=0.5)

            # Send results back to parent
            result_queue.put({"topic_id": topic_id, "received": received})

        # Create queue for results
        result_queue = multiprocessing.Queue()

        # Start both subscribers in separate subprocesses
        sub1_proc = multiprocessing.Process(target=subscriber_process,
                                            args=(topic1, result_queue, 1))
        sub2_proc = multiprocessing.Process(target=subscriber_process,
                                            args=(topic2, result_queue, 2))
        sub1_proc.start()
        sub2_proc.start()

        time.sleep(0.1)

        # Publish to different topics
        publish(topic1, b"for topic 1")
        publish(topic2, b"for topic 2")

        sub1_proc.join()
        sub2_proc.join()

        # Get results from queue
        results = [result_queue.get(timeout=1) for _ in range(2)]
        received1 = next(r["received"] for r in results if r["topic_id"] == 1)
        received2 = next(r["received"] for r in results if r["topic_id"] == 2)

        # Each should only receive its own messages
        assert len(received1) == 1
        assert len(received2) == 1
        assert received1[0]["content"] == "for topic 1"
        assert received2[0]["content"] == "for topic 2"
if __name__ == "__main__":
    unittest.main()
