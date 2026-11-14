"""Tests for the directory-based message spool: ordering, exclusion, cleanup, fallbacks."""

import errno
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from pubsub import abstractions
from pubsub import pubsub as pubsub_module
from pubsub.abstractions import get_purge_dir, get_tmp_dir
from pubsub.channel import LOCKED_SUFFIX, POISON_DIRECTORY, Channel
from pubsub.message import Message, message_file_name
from pubsub.pubsub import ack, fetch, nack, publish, subscribe

DEAD_PID = 999999999


class IsolatedBaseTestCase(unittest.TestCase):
    """Runs each test in its own empty pubsub base directory."""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="pubsub-test-"))
        patcher = mock.patch.object(abstractions, "_base_dir_cache", self.base)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        pubsub_module._hardlinks_supported = None
        self.addCleanup(setattr, pubsub_module, "_hardlinks_supported", None)

    def put_message(self, channel, message_id, content=b"x"):
        """Drop a message file straight into a channel directory."""
        message = Message(topic="t", content=content)
        message.id = message_id
        with open(channel.directory_path / message_file_name(message_id), "wb") as stream:
            message.write(stream)


class TestFetchOrdering(IsolatedBaseTestCase):
    def test_fetch_delivers_by_numeric_id_whatever_the_digit_count(self):
        ids = [100, 9, (1 << 64) - 1, 10, 1_000_000_000_000_000]
        with Channel("t") as channel:
            for message_id in ids:
                self.put_message(channel, message_id)
            received = [fetch(channel).id for _ in ids]
            assert fetch(channel) is None
        assert received == sorted(ids)

    def test_messages_published_by_one_publisher_arrive_in_order(self):
        with Channel("order.test") as channel:
            for number in range(200):
                assert publish("order.test", str(number).encode()) == 1
            received = []
            message = fetch(channel)
            while message is not None:
                received.append(int(message.content))
                message = fetch(channel)
        assert received == list(range(200))

    def test_directory_is_listed_only_when_the_known_messages_are_used_up(self):
        with Channel("t") as channel:
            for message_id in (1, 2, 3):
                self.put_message(channel, message_id)
            with mock.patch("pubsub.channel.os.scandir", wraps=os.scandir) as listing:
                assert fetch(channel).id == 1
                self.put_message(channel, 0)  # smaller id, arrives after the listing
                assert fetch(channel).id == 2
                assert fetch(channel).id == 3
                assert listing.call_count == 1
                # The late message is found by the next listing, and nothing is lost
                assert fetch(channel).id == 0
                assert listing.call_count == 2
                assert fetch(channel) is None

    def test_a_file_deleted_after_the_listing_is_skipped(self):
        with Channel("t") as channel:
            for message_id in (1, 2, 3):
                self.put_message(channel, message_id)
            assert fetch(channel).id == 1
            (channel.directory_path / message_file_name(2)).unlink()
            assert fetch(channel).id == 3
            assert fetch(channel) is None

    def test_names_that_are_not_message_names_are_ignored(self):
        with Channel("t") as channel:
            (channel.directory_path / "5").write_bytes(b"unpadded")
            (channel.directory_path / f".{message_file_name(7)}.part").write_bytes(b"half")
            (channel.directory_path / "queue").write_bytes(b"")
            self.put_message(channel, 9)
            assert fetch(channel).id == 9
            assert fetch(channel) is None

    def test_fetch_consumes_the_message_file(self):
        with Channel("t") as channel:
            self.put_message(channel, 4)
            fetch(channel)
            assert list(channel.directory_path.iterdir()) == []

    def test_fetch_on_a_closed_directory_returns_none(self):
        with Channel("t") as channel:
            shutil.rmtree(channel.directory_path)
            assert fetch(channel) is None


class TestReadMessagePair(IsolatedBaseTestCase):
    """The channel owns its message files: begin_read_message / ack."""

    def test_the_file_is_locked_until_end_read_message(self):
        with Channel("pair.test") as channel:
            publish("pair.test", b"payload")
            message = channel.begin_read_message()
            assert message.content == b"payload"
            # The file was renamed, so it can no longer be taken by anybody else
            assert [e.name for e in channel.directory_path.iterdir()] == [
                message.file_name + LOCKED_SUFFIX
            ]

            channel.end_read_message(message)

            assert list(channel.directory_path.iterdir()) == []

    def test_a_locked_file_is_not_handed_out_by_a_new_listing(self):
        with Channel("pair.relist") as channel:
            publish("pair.relist", b"one")
            first = channel.begin_read_message()  # not ended: still locked
            assert channel.begin_read_message() is None  # the listing skips the locked file
            channel.end_read_message(first)

    def test_a_message_claimed_by_another_reader_is_skipped(self):
        with Channel("pair.claimed") as channel:
            for message_id in (1, 2):
                self.put_message(channel, message_id)
            real_rename = os.rename
            calls = []

            def rename(source, target):
                calls.append(source)
                if len(calls) == 1:  # another reader renamed the file just before us
                    real_rename(source, str(source) + "-taken")
                return real_rename(source, target)

            with mock.patch("pubsub.channel.os.rename", rename):
                message = channel.begin_read_message()
            assert message.id == 2

    def test_a_file_that_cannot_be_claimed_raises_instead_of_looping(self):
        with Channel("pair.stuck") as channel:
            publish("pair.stuck", b"x")
            with mock.patch(
                "pubsub.channel.os.rename", side_effect=PermissionError("locked elsewhere")
            ):
                with self.assertRaises(PermissionError):
                    channel.begin_read_message()

    def test_locked_files_are_deleted_with_the_channel(self):
        channel = Channel("pair.leftover")
        channel.open()
        publish("pair.leftover", b"x")
        message = channel.begin_read_message()
        directory = channel.directory_path
        assert message is not None

        channel.close()  # ack was never called

        assert not directory.exists()

    def test_begin_returns_none_when_nothing_waits(self):
        with Channel("pair.empty") as channel:
            assert channel.begin_read_message() is None

    def test_messages_are_handed_out_in_id_order_and_only_once(self):
        with Channel("pair.order") as channel:
            for message_id in (30, 10, 20):
                self.put_message(channel, message_id)
            first = channel.begin_read_message()
            second = channel.begin_read_message()  # without ending the first
            third = channel.begin_read_message()
            assert [first.id, second.id, third.id] == [10, 20, 30]
            assert channel.begin_read_message() is None

    def test_end_read_message_twice_or_after_deletion_is_harmless(self):
        with Channel("pair.twice") as channel:
            publish("pair.twice", b"x")
            message = channel.begin_read_message()
            channel.end_read_message(message)
            channel.end_read_message(message)

    def test_end_read_message_after_the_channel_closed_is_harmless(self):
        channel = Channel("pair.closed")
        channel.open()
        publish("pair.closed", b"x")
        message = channel.begin_read_message()
        channel.close()
        channel.end_read_message(message)

    def test_a_file_that_cannot_be_deleted_is_logged_not_raised(self):
        with Channel("pair.locked") as channel:
            publish("pair.locked", b"x")
            message = channel.begin_read_message()
            with mock.patch.object(
                Path, "unlink", side_effect=PermissionError("still open")
            ), self.assertLogs(level="WARNING"):
                channel.end_read_message(message)

    def test_a_vanished_file_is_skipped_by_begin(self):
        with Channel("pair.vanished") as channel:
            for message_id in (1, 2, 3):
                self.put_message(channel, message_id)
            first = channel.begin_read_message()
            (channel.directory_path / message_file_name(2)).unlink()
            assert first.id == 1
            assert channel.begin_read_message().id == 3

    def test_an_invalid_message_file_raises_and_the_next_call_moves_on(self):
        with Channel("pair.corrupt") as channel:
            (channel.directory_path / message_file_name(1)).write_bytes(b"not a message")
            self.put_message(channel, 2)
            with self.assertRaises(ValueError):
                channel.begin_read_message()
            assert channel.begin_read_message().id == 2
            # The invalid file stays, locked, and is never handed out again
            assert (channel.directory_path / (message_file_name(1) + LOCKED_SUFFIX)).exists()
            assert channel.begin_read_message() is None

    def test_direct_use_is_refused_while_subscribed_and_the_other_way_round(self):
        with Channel("pair.modes") as channel:
            with self.assertRaises(RuntimeError):
                channel.begin_read_message(subscribed=True)  # nobody is subscribed
            channel.begin_subscription()
            try:
                assert channel.is_subscribed
                with self.assertRaises(RuntimeError):
                    channel.begin_read_message()  # a direct fetch while subscribed
                with self.assertRaises(RuntimeError):
                    channel.begin_subscription()  # a second listener
                assert channel.begin_read_message(subscribed=True) is None
            finally:
                channel.end_subscription()
            assert not channel.is_subscribed
            assert channel.begin_read_message() is None

    def test_begin_read_message_needs_an_open_channel(self):
        channel = Channel("pair.notopen")
        with self.assertRaises(RuntimeError):
            channel.begin_read_message()
        with self.assertRaises(RuntimeError):
            channel.begin_subscription()

    def test_the_file_is_still_there_while_the_subscriber_callback_runs(self):
        seen = {}

        def callback(message):
            path = channel.directory_path / (message.file_name + LOCKED_SUFFIX)
            seen["during"] = path.exists()
            seen["path"] = path

        with Channel("pair.callback") as channel:
            publish("pair.callback", b"x")
            assert subscribe(channel, callback, timeout_seconds=0.3) == 1
        assert seen["during"] is True
        assert not seen["path"].exists()

    def test_the_file_is_deleted_even_if_the_callback_raises(self):
        def callback(message):
            raise RuntimeError("boom")

        with Channel("pair.raises") as channel:
            publish("pair.raises", b"x")
            assert subscribe(channel, callback, timeout_seconds=0.3) == 1
            assert list(channel.directory_path.iterdir()) == []


class TestAcknowledgement(IsolatedBaseTestCase):
    """fetch(auto_ack=False) leaves the disposal of the message to ack and nack."""

    def names(self, channel):
        return sorted(entry.name for entry in channel.directory_path.iterdir())

    def test_auto_ack_is_the_default_and_deletes_the_message(self):
        with Channel("ack.default") as channel:
            publish("ack.default", b"x")
            assert fetch(channel) is not None
            assert self.names(channel) == []

    def test_without_auto_ack_the_message_stays_locked(self):
        with Channel("ack.manual") as channel:
            publish("ack.manual", b"x")
            message = fetch(channel, auto_ack=False)
            assert message.content == b"x"
            assert self.names(channel) == [message.file_name + LOCKED_SUFFIX]

    def test_ack_deletes_the_message(self):
        with Channel("ack.ack") as channel:
            publish("ack.ack", b"x")
            message = fetch(channel, auto_ack=False)

            ack(channel, message)

            assert self.names(channel) == []
            assert fetch(channel) is None

    def test_nack_makes_the_message_available_again_under_its_own_name(self):
        with Channel("ack.nack") as channel:
            publish("ack.nack", b"again")
            message = fetch(channel, auto_ack=False)

            nack(channel, message)

            assert self.names(channel) == [message.file_name]
            again = fetch(channel)
            assert again.id == message.id
            assert again.content == b"again"
            assert fetch(channel) is None

    def test_nack_is_delivered_after_the_messages_already_listed(self):
        with Channel("ack.order") as channel:
            for message_id in (1, 2, 3):
                self.put_message(channel, message_id)
            first = fetch(channel, auto_ack=False)  # lists 1, 2, 3 and hands out 1
            nack(channel, first)
            # 2 and 3 are already listed: they come first, then the listing finds 1 again
            assert [fetch(channel).id for _ in range(3)] == [2, 3, 1]
            assert fetch(channel) is None

    def test_nack_with_nothing_else_waiting_is_delivered_at_once(self):
        with Channel("ack.alone") as channel:
            publish("ack.alone", b"x")
            message = fetch(channel, auto_ack=False)
            nack(channel, message)
            assert fetch(channel).id == message.id

    def test_a_message_nacked_many_times_is_delivered_each_time(self):
        with Channel("ack.loop") as channel:
            publish("ack.loop", b"x")
            for _ in range(5):
                message = fetch(channel, auto_ack=False)
                assert message is not None
                nack(channel, message)
            ack(channel, fetch(channel, auto_ack=False))
            assert fetch(channel) is None

    def test_ack_and_nack_twice_are_harmless(self):
        with Channel("ack.twice") as channel:
            publish("ack.twice", b"x")
            message = fetch(channel, auto_ack=False)
            ack(channel, message)
            ack(channel, message)
            nack(channel, message)  # nothing left to give back
            assert fetch(channel) is None

    def test_ack_and_nack_after_the_channel_closed_are_harmless(self):
        channel = Channel("ack.closed")
        channel.open()
        publish("ack.closed", b"x")
        message = fetch(channel, auto_ack=False)
        channel.close()
        ack(channel, message)
        nack(channel, message)

    def test_a_message_not_disposed_of_is_deleted_with_the_channel(self):
        channel = Channel("ack.forgotten")
        channel.open()
        publish("ack.forgotten", b"x")
        fetch(channel, auto_ack=False)
        directory = channel.directory_path
        channel.close()
        assert not directory.exists()

    def test_a_nack_that_cannot_rename_is_logged_not_raised(self):
        with Channel("ack.stuck") as channel:
            publish("ack.stuck", b"x")
            message = fetch(channel, auto_ack=False)
            with mock.patch(
                "pubsub.channel.os.rename", side_effect=PermissionError("locked elsewhere")
            ), self.assertLogs(level="WARNING"):
                nack(channel, message)

    def test_fetch_without_auto_ack_is_refused_while_subscribed(self):
        with Channel("ack.sub") as channel:
            channel.begin_subscription()
            try:
                with self.assertRaises(RuntimeError):
                    fetch(channel, auto_ack=False)
            finally:
                channel.end_subscription()

    def test_two_consumers_never_get_the_same_unacknowledged_message(self):
        with Channel("ack.two") as channel:
            for message_id in (1, 2):
                self.put_message(channel, message_id)
            first = fetch(channel, auto_ack=False)
            second = fetch(channel, auto_ack=False)
            assert {first.id, second.id} == {1, 2}
            assert fetch(channel, auto_ack=False) is None


class TestNackLogging(IsolatedBaseTestCase):
    """Every nack leaves a trace: INFO when the message goes back, WARNING when poison."""

    def fetched(self, channel, topic):
        publish(topic, b"x")
        return fetch(channel, auto_ack=False)

    def test_nack_logs_an_information(self):
        with Channel("log.info") as channel:
            message = self.fetched(channel, "log.info")
            with self.assertLogs(level="INFO") as logs:
                nack(channel, message)
        assert [record.levelname for record in logs.records] == ["INFO"]
        assert str(message.id) in logs.output[0] and "log.info" in logs.output[0]

    def test_poison_nack_logs_a_warning(self):
        with Channel("log.warning") as channel:
            message = self.fetched(channel, "log.warning")
            with self.assertLogs(level="INFO") as logs:
                nack(channel, message, poison=True)
        assert [record.levelname for record in logs.records] == ["WARNING"]
        assert str(message.id) in logs.output[0] and "poison" in logs.output[0].lower()

    def test_nack_is_logged_even_when_the_message_is_already_gone(self):
        with Channel("log.gone") as channel:
            message = self.fetched(channel, "log.gone")
            ack(channel, message)
            with self.assertLogs(level="INFO") as logs:
                nack(channel, message)
            assert [r.levelname for r in logs.records] == ["INFO"]
            with self.assertLogs(level="INFO") as logs:
                nack(channel, message, poison=True)
            assert [r.levelname for r in logs.records] == ["WARNING"]


class TestPoison(IsolatedBaseTestCase):
    """nack(poison=True) moves the message to the poison folder of the channel."""

    def test_poison_path_is_a_sub_directory_of_the_channel(self):
        channel = Channel("poison.path")
        assert channel.poison_path == channel.directory_path / POISON_DIRECTORY

    def test_the_poison_folder_is_created_when_needed(self):
        with Channel("poison.lazy") as channel:
            assert not channel.poison_path.exists()
            publish("poison.lazy", b"x")
            nack(channel, fetch(channel, auto_ack=False), poison=True)
            assert channel.poison_path.is_dir()

    def test_a_poison_message_is_moved_under_its_own_name(self):
        with Channel("poison.move") as channel:
            publish("poison.move", b"bad payload", headers={"k": "v"})
            message = fetch(channel, auto_ack=False)

            nack(channel, message, poison=True)

            assert sorted(e.name for e in channel.directory_path.iterdir()) == [POISON_DIRECTORY]
            assert [e.name for e in channel.poison_path.iterdir()] == [message.file_name]
            with open(channel.poison_path / message.file_name, "rb") as stream:
                stored = Message.read(stream)
            assert stored.id == message.id
            assert stored.content == b"bad payload"
            assert stored.headers == {"k": "v"}

    def test_a_poison_message_is_never_delivered_again(self):
        with Channel("poison.never") as channel:
            publish("poison.never", b"bad")
            nack(channel, fetch(channel, auto_ack=False), poison=True)
            assert fetch(channel) is None
            assert subscribe(channel, lambda message: None, timeout_seconds=0.2) == 0
            assert len(list(channel.poison_path.iterdir())) == 1

    def test_the_other_messages_are_not_affected(self):
        with Channel("poison.others") as channel:
            for message_id in (1, 2, 3):
                self.put_message(channel, message_id)
            first = fetch(channel, auto_ack=False)
            nack(channel, first, poison=True)
            assert [fetch(channel).id, fetch(channel).id] == [2, 3]
            assert fetch(channel) is None

    def test_several_poison_messages_share_the_folder(self):
        with Channel("poison.many") as channel:
            for message_id in (1, 2):
                self.put_message(channel, message_id)
            nack(channel, fetch(channel, auto_ack=False), poison=True)
            nack(channel, fetch(channel, auto_ack=False), poison=True)
            assert sorted(e.name for e in channel.poison_path.iterdir()) == [
                message_file_name(1),
                message_file_name(2),
            ]

    def test_poison_messages_are_deleted_with_the_channel(self):
        channel = Channel("poison.close")
        channel.open()
        publish("poison.close", b"x")
        nack(channel, fetch(channel, auto_ack=False), poison=True)
        directory = channel.directory_path
        channel.close()
        assert not directory.exists()
        assert not any(
            channel.directory_name in entry.name for entry in os.scandir(get_purge_dir())
        )

    def test_poison_nack_twice_or_after_the_channel_closed_is_harmless(self):
        channel = Channel("poison.twice")
        channel.open()
        publish("poison.twice", b"x")
        message = fetch(channel, auto_ack=False)
        nack(channel, message, poison=True)
        nack(channel, message, poison=True)
        channel.close()
        nack(channel, message, poison=True)
        assert not channel.poison_path.exists()  # not recreated after the close

    def test_a_poison_move_that_fails_is_logged_and_leaves_the_message_locked(self):
        with Channel("poison.fail") as channel:
            publish("poison.fail", b"x")
            message = fetch(channel, auto_ack=False)
            with mock.patch(
                "pubsub.channel.os.rename", side_effect=PermissionError("locked elsewhere")
            ), self.assertLogs(level="WARNING") as logs:
                nack(channel, message, poison=True)
            assert len(logs.records) == 2  # the poison warning, then the failure
            assert (channel.directory_path / (message.file_name + LOCKED_SUFFIX)).exists()

    def test_a_callback_can_send_a_message_to_the_poison_folder(self):
        def callback(message):
            if message.content == b"bad":
                nack(channel, message, poison=True)
            else:
                ack(channel, message)

        with Channel("poison.callback") as channel:
            publish("poison.callback", b"good")
            publish("poison.callback", b"bad")
            publish("poison.callback", b"good too")
            assert subscribe(channel, callback, timeout_seconds=0.5, auto_ack=False) == 3
            assert len(list(channel.poison_path.iterdir())) == 1
            names = [e.name for e in channel.directory_path.iterdir()]
            assert names == [POISON_DIRECTORY]


class TestSubscribeAcknowledgement(IsolatedBaseTestCase):
    def test_auto_ack_deletes_each_message_after_the_callback(self):
        with Channel("suback.auto") as channel:
            publish("suback.auto", b"x")
            assert subscribe(channel, lambda message: None, timeout_seconds=0.3) == 1
            assert list(channel.directory_path.iterdir()) == []

    def test_without_auto_ack_the_callback_acknowledges(self):
        with Channel("suback.ack") as channel:
            publish("suback.ack", b"x")
            received = []

            def callback(message):
                received.append(message)
                ack(channel, message)

            assert subscribe(channel, callback, timeout_seconds=0.3, auto_ack=False) == 1
            assert list(channel.directory_path.iterdir()) == []

    def test_without_auto_ack_a_message_left_alone_stays_locked(self):
        with Channel("suback.left") as channel:
            publish("suback.left", b"x")
            received = []
            subscribe(channel, received.append, timeout_seconds=0.3, auto_ack=False)
            assert [e.name for e in channel.directory_path.iterdir()] == [
                received[0].file_name + LOCKED_SUFFIX
            ]

    def test_without_auto_ack_a_raising_callback_leaves_the_message_locked(self):
        received = []

        def callback(message):
            received.append(message)
            raise RuntimeError("boom")

        with Channel("suback.raises") as channel:
            publish("suback.raises", b"x")
            assert subscribe(channel, callback, timeout_seconds=0.3, auto_ack=False) == 1
            assert [e.name for e in channel.directory_path.iterdir()] == [
                received[0].file_name + LOCKED_SUFFIX
            ]

    def test_a_nack_from_the_callback_is_delivered_again(self):
        attempts = []

        def callback(message):
            attempts.append(message.id)
            if len(attempts) < 3:
                nack(channel, message)
            else:
                ack(channel, message)

        with Channel("suback.retry") as channel:
            publish("suback.retry", b"x")
            assert subscribe(channel, callback, timeout_seconds=1, auto_ack=False) == 3
            assert len(set(attempts)) == 1  # always the same message
            assert list(channel.directory_path.iterdir()) == []


class TestPublishSpool(IsolatedBaseTestCase):
    def test_messages_published_before_open_are_not_delivered(self):
        channel = Channel("early.topic")
        assert publish("early.topic", b"too early") == 0
        with channel:
            assert fetch(channel) is None

    def test_publish_creates_the_base_directory(self):
        shutil.rmtree(self.base)
        assert publish("nobody.listens", b"x") == 0
        assert get_tmp_dir().is_dir()

    def test_message_files_have_zero_padded_names(self):
        with Channel("names.test") as channel:
            publish("names.test", b"x")
            names = [entry.name for entry in channel.directory_path.iterdir()]
        assert len(names) == 1 and len(names[0]) == 20 and names[0].isdigit()

    def test_publish_leaves_nothing_in_tmp(self):
        with Channel("tmp.test"):
            publish("tmp.test", b"x")
        assert list(get_tmp_dir().iterdir()) == []

    def test_channel_closed_while_publishing_is_skipped(self):
        with Channel("gone.test"):
            with mock.patch("pubsub.pubsub._link_message", side_effect=FileNotFoundError):
                assert publish("gone.test", b"x") == 0

    def test_other_link_errors_are_logged_and_not_counted(self):
        with Channel("err.test"):
            with mock.patch(
                "pubsub.pubsub._link_message", side_effect=OSError(errno.EIO, "io")
            ), self.assertLogs(level="WARNING"):
                assert publish("err.test", b"x") == 0

    def test_windows_path_too_long_error_is_not_swallowed(self):
        error = OSError(3, "path not found")
        error.winerror = 206
        with Channel("long.test"):
            with mock.patch("pubsub.pubsub._link_message", side_effect=error):
                with self.assertRaises(OSError) as context:
                    publish("long.test", b"x")
        assert context.exception.errno == errno.ENAMETOOLONG

    def test_permission_error_removing_the_temporary_file_does_not_fail_publish(self):
        with Channel("perm.test") as channel:
            real_unlink = Path.unlink

            def unlink(path, *args, **kwargs):
                if path.parent == get_tmp_dir():
                    raise PermissionError("still open")
                return real_unlink(path, *args, **kwargs)

            with mock.patch.object(Path, "unlink", unlink), self.assertLogs(level="WARNING"):
                assert publish("perm.test", b"x") == 1
            assert fetch(channel).content == b"x"
        assert len(list(get_tmp_dir().iterdir())) == 1  # left for the stale sweep


class TestHardlinkFallback(IsolatedBaseTestCase):
    def no_hardlinks(self, code=errno.EPERM):
        return mock.patch("pubsub.pubsub.os.link", side_effect=OSError(code, "no links here"))

    def test_messages_are_copied_when_hard_links_are_not_supported(self):
        with Channel("copy.test") as channel, self.no_hardlinks():
            assert publish("copy.test", b"one") == 1
            assert publish("copy.test", b"two") == 1
            assert pubsub_module._hardlinks_supported is False
            assert [fetch(channel).content, fetch(channel).content] == [b"one", b"two"]
            assert fetch(channel) is None
            assert list(channel.directory_path.iterdir()) == []  # no .part left over

    def test_each_unsupported_error_code_triggers_the_fallback(self):
        for code in (errno.EPERM, errno.ENOSYS, errno.EMLINK):
            pubsub_module._hardlinks_supported = None
            with Channel("copy.codes") as channel, self.no_hardlinks(code):
                assert publish("copy.codes", b"x") == 1, code
                assert fetch(channel) is not None

    def test_windows_error_codes_trigger_the_fallback(self):
        error = OSError(22, "invalid function")
        error.winerror = 1
        with Channel("copy.win") as channel, mock.patch(
            "pubsub.pubsub.os.link", side_effect=error
        ):
            assert publish("copy.win", b"x") == 1
            assert fetch(channel) is not None

    def test_other_link_errors_do_not_switch_to_copying(self):
        with Channel("nocopy.test"), mock.patch(
            "pubsub.pubsub.os.link", side_effect=OSError(errno.EIO, "io")
        ), self.assertLogs(level="WARNING"):
            assert publish("nocopy.test", b"x") == 0
        assert pubsub_module._hardlinks_supported is None

    def test_collision_is_still_detected_when_copying(self):
        fixed_id = 1_000_000_000_000_000
        with Channel("copy.collision") as channel, self.no_hardlinks():
            with mock.patch.object(Message, "_next_id", return_value=fixed_id):
                assert publish("copy.collision", b"first") == 1
                with self.assertRaises(RuntimeError) as context:
                    publish("copy.collision", b"second")
            assert "collision" in str(context.exception).lower()
            assert fetch(channel).content == b"first"
            assert list(channel.directory_path.iterdir()) == []

    def test_a_channel_closed_while_copying_is_skipped(self):
        with Channel("copy.gone"), self.no_hardlinks():
            with mock.patch("pubsub.pubsub.shutil.copyfile", side_effect=FileNotFoundError):
                assert publish("copy.gone", b"x") == 0


class TestSingleConsumer(IsolatedBaseTestCase):
    def start_subscriber(self, channel, **kwargs):
        """Run subscribe in a thread and wait until it is listening."""
        results = {}
        received = kwargs.pop("received", [])

        def run():
            try:
                results["count"] = subscribe(channel, received.append, **kwargs)
            except BaseException as e:  # reported to the test
                results["error"] = e

        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.monotonic() + 5
        while not channel.is_subscribed and time.monotonic() < deadline:
            time.sleep(0.005)
        assert channel.is_subscribed, results
        return thread, results

    def test_second_subscribe_raises(self):
        with Channel("single.test") as channel:
            thread, results = self.start_subscriber(channel, timeout_seconds=2)
            try:
                with self.assertRaises(RuntimeError) as context:
                    subscribe(channel, lambda message: None, timeout_seconds=0.1)
                assert "already" in str(context.exception)
            finally:
                thread.join()
            assert results["count"] == 0

    def test_fetch_raises_while_a_subscribe_listens(self):
        with Channel("single.fetch") as channel:
            thread, _ = self.start_subscriber(channel, timeout_seconds=1)
            try:
                with self.assertRaises(RuntimeError) as context:
                    fetch(channel)
                assert "subscribe" in str(context.exception)
            finally:
                thread.join()

    def test_fetch_works_again_after_subscribe_ends(self):
        with Channel("single.after") as channel:
            thread, _ = self.start_subscriber(channel, timeout_seconds=0.3)
            thread.join()
            assert not channel.is_subscribed
            publish("single.after", b"later")
            assert fetch(channel).content == b"later"

    def test_second_subscribe_works_after_the_first_ends(self):
        with Channel("single.again") as channel:
            assert subscribe(channel, lambda message: None, timeout_seconds=0.05) == 0
            publish("single.again", b"x")
            received = []
            assert subscribe(channel, received.append, timeout_seconds=0.3) == 1
            assert len(received) == 1

    def test_flag_is_cleared_when_subscribe_ends_with_an_error(self):
        with Channel("single.error") as channel:
            with mock.patch(
                "pubsub.pubsub.create_watcher", side_effect=RuntimeError("boom")
            ):
                with self.assertRaises(RuntimeError):
                    subscribe(channel, lambda message: None, timeout_seconds=0.1)
            assert not channel.is_subscribed
            assert subscribe(channel, lambda message: None, timeout_seconds=0.05) == 0

    def test_fetch_from_the_callback_raises_instead_of_deadlocking(self):
        outcome = []

        def callback(message):
            try:
                fetch(channel)
            except RuntimeError as e:
                outcome.append(e)

        with Channel("single.callback") as channel:
            publish("single.callback", b"x")
            assert subscribe(channel, callback, timeout_seconds=0.5) == 1
        assert len(outcome) == 1 and "subscribe" in str(outcome[0])

    def test_concurrent_fetches_deliver_each_message_once(self):
        total = 300
        with Channel("single.fetchers") as channel:
            for number in range(total):
                publish("single.fetchers", str(number).encode())
            received, errors = [], []

            def worker():
                try:
                    message = fetch(channel)
                    while message is not None:
                        received.append(int(message.content))
                        message = fetch(channel)
                except BaseException as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        assert not errors
        assert sorted(received) == list(range(total))

    def test_subscribe_from_a_thread_runs_without_signal_handling(self):
        with Channel("thread.test") as channel:
            received = []
            thread, results = self.start_subscriber(
                channel, timeout_seconds=1, received=received
            )
            publish("thread.test", b"hello")
            thread.join()
        assert results == {"count": 1}
        assert [m.content for m in received] == [b"hello"]


class TestSubscribeWakeUp(IsolatedBaseTestCase):
    def deliver_one_message_and_time_it(self):
        latencies = []

        with Channel("wake.test") as channel:
            def callback(message):
                latencies.append(time.time() - float(message.headers["sent"]))

            def run():
                subscribe(channel, callback, timeout_seconds=1.5)

            thread = threading.Thread(target=run)
            thread.start()
            time.sleep(0.4)  # let the subscriber go idle
            publish("wake.test", b"x", headers={"sent": time.time()})
            thread.join()
        return latencies

    def test_message_is_delivered_quickly_with_the_native_watcher(self):
        with mock.patch.dict(os.environ, {"PUBSUB_WATCHER": ""}):
            latencies = self.deliver_one_message_and_time_it()
        assert len(latencies) == 1
        assert latencies[0] < 0.25, latencies

    def test_message_is_delivered_with_the_polling_fallback(self):
        with mock.patch.dict(os.environ, {"PUBSUB_WATCHER": "poll"}):
            latencies = self.deliver_one_message_and_time_it()
        assert len(latencies) == 1
        assert latencies[0] < 0.25, latencies

    def test_messages_in_a_burst_are_not_delayed_by_sleeps(self):
        total = 500
        with Channel("burst.test") as channel:
            for _ in range(total):
                publish("burst.test", b"x")
            received = []
            started = time.monotonic()
            assert subscribe(channel, received.append, timeout_seconds=1) == total
            first_batch_done = received and time.monotonic() - started
        # A 10 ms sleep per message would have needed 5 s: the whole timeout is not needed
        assert len(received) == total
        assert first_batch_done is not None

    def test_timeout_is_respected(self):
        with Channel("timeout.test") as channel:
            started = time.monotonic()
            assert subscribe(channel, lambda message: None, timeout_seconds=0.3) == 0
            elapsed = time.monotonic() - started
        assert 0.28 <= elapsed < 1.0

    def test_subscribe_restores_the_signal_handlers(self):
        import signal

        before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        with Channel("signals.test") as channel:
            subscribe(channel, lambda message: None, timeout_seconds=0.05)
        after = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        assert before == after


class TestCleanup(IsolatedBaseTestCase):
    def make_dir(self, directory, name, with_file=True):
        path = directory / name
        path.mkdir(parents=True)
        if with_file:
            (path / message_file_name(1)).write_bytes(b"x")
        return path

    def test_purge_and_tmp_are_not_taken_for_channels(self):
        get_tmp_dir().mkdir(parents=True)
        get_purge_dir().mkdir(parents=True)
        self.make_dir(get_purge_dir(), f"abcdefgh_t.x_aaaaaaaaaaaa_{os.getpid()}")
        assert Channel.active_paths() == []
        assert Channel.inactive_paths() == []

    def test_unrelated_entries_in_the_base_directory_are_skipped(self):
        self.base.mkdir(parents=True, exist_ok=True)
        (self.base / "a_b_notapid").mkdir()
        (self.base / "a_b_123").write_bytes(b"a file, not a channel")
        assert Channel.active_paths() == []
        assert Channel.inactive_paths() == []

    def test_missing_base_directory(self):
        shutil.rmtree(self.base)
        assert Channel.active_paths() == []
        assert Channel.inactive_paths() == []
        Channel.cleanup_inactive()  # nothing to do, and no error

    def test_abandoned_purge_of_a_dead_process_is_removed(self):
        abandoned = self.make_dir(
            get_purge_dir(), f"abcdefgh_t.x_aaaaaaaaaaaa_{DEAD_PID}"
        )
        Channel.cleanup_inactive()
        assert not abandoned.exists()

    def test_purge_in_progress_of_a_live_process_is_left_alone(self):
        running = self.make_dir(get_purge_dir(), f"abcdefgh_t.x_aaaaaaaaaaaa_{os.getpid()}")
        Channel.cleanup_inactive()
        assert running.exists()

    def test_malformed_purge_entries_are_left_alone(self):
        odd_dir = self.make_dir(get_purge_dir(), "no-pid-in-this-name")
        odd_file = get_purge_dir() / f"abcdefgh_t_a_{DEAD_PID}"
        odd_file.write_bytes(b"a file")
        Channel.cleanup_inactive()
        assert odd_dir.exists() and odd_file.exists()

    def test_inactive_channels_are_removed(self):
        dead = self.make_dir(self.base, f"t.x_aaaaaaaaaaaa_{DEAD_PID}")
        with Channel("live.channel") as channel:
            Channel.cleanup_inactive()
            assert channel.directory_path.exists()
        assert not dead.exists()

    def stale_name(self, age_seconds):
        message_id = int((time.time() - age_seconds) * 1000) << 22
        return message_file_name(message_id)

    def test_stale_temporary_messages_are_removed_and_recent_ones_kept(self):
        get_tmp_dir().mkdir(parents=True)
        stale = get_tmp_dir() / self.stale_name(2 * 3600)
        recent = get_tmp_dir() / self.stale_name(5)
        just_inside = get_tmp_dir() / self.stale_name(3600 - 60)
        for path in (stale, recent, just_inside):
            path.write_bytes(b"x")
        Channel.cleanup_inactive()
        assert not stale.exists()
        assert recent.exists() and just_inside.exists()

    def test_entries_that_are_not_message_files_are_never_touched_in_tmp(self):
        get_tmp_dir().mkdir(parents=True)
        old_id = int((time.time() - 10 * 3600) * 1000) << 22
        unpadded = get_tmp_dir() / str(old_id)
        other = get_tmp_dir() / "notes.txt"
        folder = self.make_dir(get_tmp_dir(), self.stale_name(10 * 3600) + "d")
        unpadded.write_bytes(b"x")
        other.write_bytes(b"x")
        Channel.cleanup_inactive()
        assert unpadded.exists() and other.exists() and folder.exists()

    def test_sweep_uses_the_clock(self):
        get_tmp_dir().mkdir(parents=True)
        path = get_tmp_dir() / self.stale_name(5)
        path.write_bytes(b"x")
        with mock.patch("pubsub.channel.time.time", return_value=time.time() + 7200):
            Channel.cleanup_inactive()
        assert not path.exists()

    def test_sweep_ignores_a_vanished_file(self):
        get_tmp_dir().mkdir(parents=True)
        path = get_tmp_dir() / self.stale_name(2 * 3600)
        path.write_bytes(b"x")
        with mock.patch("pubsub.channel.os.unlink", side_effect=FileNotFoundError):
            Channel.cleanup_inactive()

    def test_permission_error_on_a_stale_file_does_not_abort_the_sweep(self):
        get_tmp_dir().mkdir(parents=True)
        locked = get_tmp_dir() / self.stale_name(3 * 3600)
        other = get_tmp_dir() / self.stale_name(2 * 3600)
        locked.write_bytes(b"x")
        other.write_bytes(b"x")
        real_unlink = os.unlink

        def unlink(path, *args, **kwargs):
            if str(path) == str(locked):
                raise PermissionError("still open")
            return real_unlink(path, *args, **kwargs)

        with mock.patch("pubsub.channel.os.unlink", unlink):
            Channel.cleanup_inactive()
        assert locked.exists()
        assert not other.exists()

    def test_ids_produced_by_messages_are_old_enough_to_sweep_later(self):
        # The age used by the sweep matches the ids Message really produces
        get_tmp_dir().mkdir(parents=True)
        path = get_tmp_dir() / Message("t", b"x").file_name
        path.write_bytes(b"x")
        Channel.cleanup_inactive()
        assert path.exists()  # brand new: not stale
        with mock.patch("pubsub.channel.time.time", return_value=time.time() + 7200):
            Channel.cleanup_inactive()
        assert not path.exists()


if __name__ == "__main__":
    unittest.main()
