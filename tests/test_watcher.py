"""Tests for the directory watchers."""

import os
import select
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from pubsub import watcher as watcher_module
from pubsub.watcher import DirWatcher, PollingWatcher, create_watcher


def create_file_later(path, delay):
    """Create a file after a delay, from another thread."""

    def create():
        time.sleep(delay)
        path.write_bytes(b"x")

    thread = threading.Thread(target=create)
    thread.start()
    return thread


class WatcherTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="pubsub-watcher-"))
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)


class TestPollingWatcher(unittest.TestCase):
    def test_wait_interval_grows_then_stays_at_the_maximum(self):
        polling = PollingWatcher()
        with mock.patch("pubsub.watcher.time.sleep") as sleep:
            for _ in range(9):
                polling.wait(10)
        waits = [call.args[0] for call in sleep.call_args_list]
        assert waits == [0.001, 0.002, 0.005, 0.010, 0.025, 0.050, 0.050, 0.050, 0.050]

    def test_activity_resets_the_interval(self):
        polling = PollingWatcher()
        with mock.patch("pubsub.watcher.time.sleep") as sleep:
            polling.wait(10)
            polling.wait(10)
            polling.activity()
            polling.wait(10)
        assert [call.args[0] for call in sleep.call_args_list] == [0.001, 0.002, 0.001]

    def test_wait_never_exceeds_the_timeout(self):
        polling = PollingWatcher()
        polling._step = 5
        with mock.patch("pubsub.watcher.time.sleep") as sleep:
            polling.wait(0.003)
        sleep.assert_called_once_with(0.003)

    def test_max_wait_is_the_largest_interval(self):
        assert PollingWatcher().max_wait == 0.050


class TestCreateWatcher(WatcherTestCase):
    def test_environment_variable_forces_polling(self):
        with mock.patch.dict(os.environ, {"PUBSUB_WATCHER": "poll"}):
            assert isinstance(create_watcher(self.directory), PollingWatcher)

    def test_native_failure_falls_back_to_polling(self):
        with mock.patch.dict(os.environ, {"PUBSUB_WATCHER": ""}), mock.patch.object(
            watcher_module, "InotifyWatcher", side_effect=OSError("watch limit reached")
        ), mock.patch.object(watcher_module, "KqueueWatcher", side_effect=OSError("no")), (
            mock.patch.object(watcher_module, "WindowsChangeWatcher", side_effect=OSError("no"))
        ):
            assert isinstance(create_watcher(self.directory), PollingWatcher)

    def test_missing_directory_falls_back_to_polling(self):
        with mock.patch.dict(os.environ, {"PUBSUB_WATCHER": ""}):
            assert isinstance(create_watcher(self.directory / "missing"), DirWatcher)

    def test_native_watcher_is_used_by_default(self):
        with mock.patch.dict(os.environ, {"PUBSUB_WATCHER": ""}):
            watcher = create_watcher(self.directory)
        try:
            if sys.platform.startswith("linux"):
                assert isinstance(watcher, watcher_module.InotifyWatcher)
            elif hasattr(select, "kqueue"):
                assert isinstance(watcher, watcher_module.KqueueWatcher)
            elif sys.platform == "win32":
                assert isinstance(watcher, watcher_module.WindowsChangeWatcher)
        finally:
            watcher.close()


class NativeWatcherTests:
    """Behaviour every native watcher must have. Mixed into one TestCase per platform."""

    def make_watcher(self, path):
        raise NotImplementedError

    def test_wakes_up_when_a_file_is_created(self):
        watcher = self.make_watcher(self.directory)
        self.addCleanup(watcher.close)
        thread = create_file_later(self.directory / "a", 0.1)
        started = time.monotonic()
        watcher.wait(5)
        elapsed = time.monotonic() - started
        thread.join()
        assert elapsed < 2, f"woke up after {elapsed:.2f}s"
        assert elapsed >= 0.05

    def test_times_out_when_nothing_happens(self):
        watcher = self.make_watcher(self.directory)
        self.addCleanup(watcher.close)
        started = time.monotonic()
        watcher.wait(0.2)
        elapsed = time.monotonic() - started
        assert 0.15 <= elapsed < 1.5

    def test_file_created_before_wait_is_not_lost(self):
        watcher = self.make_watcher(self.directory)
        self.addCleanup(watcher.close)
        (self.directory / "early").write_bytes(b"x")  # after the watcher exists, before wait
        started = time.monotonic()
        watcher.wait(5)
        assert time.monotonic() - started < 2

    def test_wait_after_close_does_not_fail(self):
        watcher = self.make_watcher(self.directory)
        watcher.close()
        watcher.close()  # closing twice is harmless
        watcher.wait(0.01)


@unittest.skipUnless(sys.platform.startswith("linux"), "inotify is Linux only")
class TestInotifyWatcher(NativeWatcherTests, WatcherTestCase):
    def make_watcher(self, path):
        return watcher_module.InotifyWatcher(path)

    def test_watchers_in_one_process_share_a_single_instance(self):
        first = self.make_watcher(self.directory)
        other_directory = self.directory / "other"
        other_directory.mkdir()
        second = self.make_watcher(other_directory)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        assert first._hub is second._hub

    def test_only_the_watcher_of_the_changed_directory_wakes_up(self):
        other_directory = self.directory / "other"
        other_directory.mkdir()
        first = self.make_watcher(self.directory)
        second = self.make_watcher(other_directory)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        durations = {}

        def wait_on(name, watcher):
            started = time.monotonic()
            watcher.wait(1.0)
            durations[name] = time.monotonic() - started

        threads = [
            threading.Thread(target=wait_on, args=("first", first)),
            threading.Thread(target=wait_on, args=("second", second)),
        ]
        for thread in threads:
            thread.start()
        time.sleep(0.2)
        (self.directory / "event").write_bytes(b"x")  # only the first directory changes
        for thread in threads:
            thread.join()
        assert durations["first"] < 0.8
        assert durations["second"] >= 0.9

    def test_unwatched_missing_directory_raises(self):
        with self.assertRaises(OSError):
            self.make_watcher(self.directory / "missing")

    def test_hub_is_recreated_after_a_fork(self):
        first = watcher_module._get_hub()
        with mock.patch("pubsub.watcher.os.getpid", return_value=first.pid + 1):
            second = watcher_module._get_hub()
        assert second is not first
        assert second.pid == first.pid + 1
        # leave a hub that belongs to this process for the other tests
        watcher_module._hub = None
        watcher_module._get_hub()


@unittest.skipUnless(hasattr(select, "kqueue"), "kqueue is macOS and BSD only")
class TestKqueueWatcher(NativeWatcherTests, WatcherTestCase):
    def make_watcher(self, path):
        return watcher_module.KqueueWatcher(path)


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class TestWindowsChangeWatcher(NativeWatcherTests, WatcherTestCase):
    def make_watcher(self, path):
        return watcher_module.WindowsChangeWatcher(path)


if __name__ == "__main__":
    unittest.main()
