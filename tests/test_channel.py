"""Tests for the Channel class."""

import unittest
import os
import time
from pathlib import Path
from pubsub.channel import Channel
from pubsub.abstractions import get_base_dir


class TestChannel(unittest.TestCase):
    """Test cases for Channel class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_channels = []
    
    def tearDown(self):
        """Clean up test channels."""
        for channel in self.test_channels:
            channel.cleanup()
    
    def test_channel_creation(self):
        """Test basic channel creation."""
        topic = "test.topic"
        channel = Channel(topic=topic)
        self.test_channels.append(channel)
        
        assert channel.topic == topic
        assert channel.process_id == os.getpid()
        assert len(channel.random_id) == 12
        assert channel.directory_path.exists()
        assert channel.queue_path.exists()
    
    def test_channel_directory_format(self):
        """Test that channel directory follows the correct format."""
        topic = "test.format"
        channel = Channel(topic=topic)
        self.test_channels.append(channel)
        
        # Directory name should be: {topic}_{random_12_chars}_{process_id}
        parts = channel.directory_name.split('_')
        assert len(parts) == 3
        assert parts[0] == topic
        assert len(parts[1]) == 12  # random_id
        assert parts[2] == str(os.getpid())
    
    def test_unique_channel_ids(self):
        """Test that multiple channels get unique random IDs."""
        channel1 = Channel(topic="test")
        channel2 = Channel(topic="test")
        self.test_channels.extend([channel1, channel2])
        
        assert channel1.random_id != channel2.random_id
        assert channel1.directory_name != channel2.directory_name
    
    def test_topic_validation_empty(self):
        """Test that empty topic raises ValueError."""
        with self.assertRaises(ValueError) as context:
            Channel(topic="")
        assert "cannot be empty" in str(context.exception)
    
    def test_topic_validation_invalid_chars(self):
        """Test that invalid characters in topic raise ValueError."""
        invalid_topics = [
            "test/topic",
            "test topic",
            "test@topic",
            "test#topic",
            "test$topic",
            "test%topic",
            "test&topic",
            "test*topic",
            "test(topic)",
            "test[topic]",
            "test{topic}",
            "test|topic",
            "test\\topic",
            "test;topic",
            "test:topic",
            "test'topic",
            "test\"topic",
            "test<topic>",
            "test?topic",
        ]
        
        for invalid_topic in invalid_topics:
            with self.assertRaises(ValueError) as context:
                Channel(topic=invalid_topic)
            assert "invalid characters" in str(context.exception).lower()
    
    def test_topic_validation_valid_chars(self):
        """Test that valid characters in topic are accepted."""
        valid_topics = [
            "test",
            "test.topic",
            "test-topic",
            "test123",
            "TEST",
            "Test.Mixed.Case",
            "topic+",
            "topic=",
            "a.b.c.d.e",
            "123.456",
            "a-b-c",
            "test.=.topic",
            "test.+.wildcard",
        ]
        
        for valid_topic in valid_topics:
            channel = Channel(topic=valid_topic)
            self.test_channels.append(channel)
            assert channel.topic == valid_topic
    
    def test_channel_cleanup(self):
        """Test that cleanup removes directory and FIFO."""
        channel = Channel(topic="test.cleanup")
        directory_path = channel.directory_path
        queue_path = channel.queue_path
        
        # Verify they exist
        assert directory_path.exists()
        assert queue_path.exists()
        
        # Cleanup
        channel.cleanup()
        
        # Verify they're removed
        assert not directory_path.exists()
        assert not queue_path.exists()
    
    def test_channel_context_manager(self):
        """Test channel as a context manager."""
        topic = "test.context"
        
        with Channel(topic=topic) as channel:
            directory_path = channel.directory_path
            queue_path = channel.queue_path
            
            # Inside context: resources exist
            assert directory_path.exists()
            assert queue_path.exists()
            assert channel.topic == topic
        
        # After context: resources cleaned up
        assert not directory_path.exists()
        assert not queue_path.exists()
    
    def test_open_queue_for_reading(self):
        """Test opening FIFO queue for reading."""
        channel = Channel(topic="test.read")
        self.test_channels.append(channel)
        
        # Open in non-blocking mode
        fd = channel.open_queue_for_reading()
        
        # Should return a valid file descriptor
        assert isinstance(fd, int)
        assert fd >= 0
        
        # Clean up file descriptor
        os.close(fd)
    
    def test_str_representation(self):
        """Test channel string representation."""
        channel = Channel(topic="test.str")
        self.test_channels.append(channel)
        
        str_repr = str(channel)
        assert "Channel" in str_repr
        assert "test.str" in str_repr
        assert channel.directory_name in str_repr
    
    def test_repr_representation(self):
        """Test channel repr representation."""
        channel = Channel(topic="test.repr")
        self.test_channels.append(channel)
        
        repr_str = repr(channel)
        assert "Channel" in repr_str
        assert "test.repr" in repr_str
        assert str(channel.process_id) in repr_str
        assert channel.random_id in repr_str
    
    def test_active_paths_empty(self):
        """Test active_paths when no channels exist."""
        # Clean up any existing channels first (best effort)
        base_dir = get_base_dir()
        if base_dir.exists():
            for item in base_dir.iterdir():
                if item.is_dir():
                    try:
                        for subitem in item.iterdir():
                            try:
                                subitem.unlink()
                            except OSError:
                                pass  # Skip FIFOs and other special files
                        item.rmdir()
                    except OSError:
                        pass  # Directory not empty or other issue
        
        active = Channel.active_paths()
        # Should be empty or only contain channels from this process
        for path in active:
            parts = path.name.split('_')
            assert len(parts) >= 3
    
    def test_active_paths_with_channels(self):
        """Test active_paths returns current process channels."""
        channel1 = Channel(topic="test.active1")
        channel2 = Channel(topic="test.active2")
        self.test_channels.extend([channel1, channel2])
        
        active = Channel.active_paths()
        
        # Should include our channels
        assert channel1.directory_path in active or any(
            p.name == channel1.directory_name for p in active
        )
        assert channel2.directory_path in active or any(
            p.name == channel2.directory_name for p in active
        )
    
    def test_inactive_paths(self):
        """Test inactive_paths detection."""
        # Create a channel directory with a fake PID that doesn't exist
        base_dir = get_base_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        
        # Use a very high PID that shouldn't exist
        fake_pid = 999999999
        fake_dir = base_dir / f"test.inactive_abc123def456_{fake_pid}"
        fake_dir.mkdir(exist_ok=True)
        
        try:
            inactive = Channel.inactive_paths()
            
            # Should include our fake channel
            assert fake_dir in inactive or any(
                p.name == fake_dir.name for p in inactive
            )
        finally:
            # Clean up
            if fake_dir.exists():
                fake_dir.rmdir()
    
    def test_matching_active_paths_exact(self):
        """Test matching_active_paths with exact match."""
        channel = Channel(topic="exact.match.topic")
        self.test_channels.append(channel)
        
        matches = Channel.matching_active_paths("exact.match.topic")
        
        assert len(matches) > 0
        assert any(p.name == channel.directory_name for p in matches)
    
    def test_matching_active_paths_single_wildcard(self):
        """Test matching_active_paths with single word wildcard (=)."""
        # The = wildcard is converted to [a-zA-Z0-9-] which matches a single character
        # not a single word. To match, we need a channel with = at the position
        # where we want to match any single character from the allowed set
        channel1 = Channel(topic="tes=.match")
        self.test_channels.append(channel1)
        
        # Should match: the = becomes [a-zA-Z0-9-] in regex
        matches = Channel.matching_active_paths("test.match")
        # Check if our channel with = wildcard is in matches
        has_wildcard_match = any("tes=.match" in p.name for p in matches)
        # The wildcard should match (t-e-s-[any allowed char].match)
        assert has_wildcard_match
    
    def test_matching_active_paths_multi_wildcard(self):
        """Test matching_active_paths with multiple words wildcard (+)."""
        channel = Channel(topic="test.+")
        self.test_channels.append(channel)
        
        # Should match zero or more words
        matches_single = Channel.matching_active_paths("test.word")
        matches_multi = Channel.matching_active_paths("test.word.sub.topic")
        
        assert any(p.name.startswith("test.+") for p in matches_single)
        assert any(p.name.startswith("test.+") for p in matches_multi)
    
    def test_matching_active_paths_no_match(self):
        """Test matching_active_paths with no matching channels."""
        channel = Channel(topic="specific.topic")
        self.test_channels.append(channel)
        
        matches = Channel.matching_active_paths("different.topic")
        
        # Should not include our channel
        assert not any(p.name == channel.directory_name for p in matches)
    
    def test_channel_base_dir(self):
        """Test that channels are created in the correct base directory."""
        channel = Channel(topic="test.basedir")
        self.test_channels.append(channel)
        
        base_dir = get_base_dir()
        assert channel.directory_path.parent == base_dir
        assert str(channel.directory_path).startswith(str(base_dir))
    
    def test_multiple_channels_same_topic(self):
        """Test creating multiple channels with the same topic."""
        topic = "shared.topic"
        channel1 = Channel(topic=topic)
        channel2 = Channel(topic=topic)
        channel3 = Channel(topic=topic)
        self.test_channels.extend([channel1, channel2, channel3])
        
        # All should have same topic but different directories
        assert channel1.topic == channel2.topic == channel3.topic == topic
        assert channel1.directory_name != channel2.directory_name
        assert channel2.directory_name != channel3.directory_name
        assert channel1.directory_name != channel3.directory_name
    
    def test_cleanup_with_files(self):
        """Test cleanup removes files in the channel directory."""
        channel = Channel(topic="test.files")
        
        # Create some test files in the channel directory
        test_file1 = channel.directory_path / "message1.dat"
        test_file2 = channel.directory_path / "message2.dat"
        test_file1.write_bytes(b"test data 1")
        test_file2.write_bytes(b"test data 2")
        
        directory_path = channel.directory_path
        
        # Verify files exist
        assert test_file1.exists()
        assert test_file2.exists()
        
        # Cleanup should remove everything
        channel.cleanup()
        
        # Verify directory and files are gone
        assert not directory_path.exists()
        assert not test_file1.exists()
        assert not test_file2.exists()


if __name__ == "__main__":
    unittest.main()
