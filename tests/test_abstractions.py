"""Tests for the platform abstractions."""

import errno
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from pubsub import abstractions
from pubsub.abstractions import (
    WINDOWS_MAX_PATH,
    _is_process_running_windows,
    check_windows_path_length,
    get_purge_dir,
    get_tmp_dir,
    is_process_running,
    longest_channel_path_length,
    raise_if_path_too_long,
    retry_fs,
    windows_long_paths_enabled,
)
from pubsub.channel import Channel


class FakeKernel32:
    """Stands in for kernel32 to run the Windows process check on any platform."""

    def __init__(self, handle=1, exit_code=259, exit_code_ok=True):
        self.handle = handle
        self.exit_code = exit_code
        self.exit_code_ok = exit_code_ok
        self.closed = False
        self.access = None

    def OpenProcess(self, access, inherit, pid):
        self.access = access
        return self.handle

    def GetExitCodeProcess(self, handle, reference):
        reference._obj.value = self.exit_code
        return self.exit_code_ok

    def CloseHandle(self, handle):
        self.closed = True
        return 1


class TestIsProcessRunning(unittest.TestCase):
    def test_current_process_is_running(self):
        assert is_process_running(os.getpid())

    def test_invalid_pids(self):
        assert not is_process_running(0)
        assert not is_process_running(-5)
        assert not is_process_running(10**30)

    @unittest.skipIf(sys.platform == "win32", "POSIX only")
    def test_missing_process_is_not_running(self):
        assert not is_process_running(999999999)

    @unittest.skipIf(sys.platform == "win32", "POSIX only")
    def test_permission_error_means_running(self):
        with mock.patch("pubsub.abstractions.os.kill", side_effect=PermissionError):
            assert is_process_running(12345)

    @unittest.skipIf(sys.platform == "win32", "POSIX only")
    def test_other_os_errors_mean_not_running(self):
        with mock.patch("pubsub.abstractions.os.kill", side_effect=OSError(errno.EINVAL, "x")):
            assert not is_process_running(12345)

    def test_windows_running_process(self):
        kernel32 = FakeKernel32(exit_code=259)
        assert _is_process_running_windows(10, kernel32, lambda: 0)
        assert kernel32.closed
        assert kernel32.access == 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION

    def test_windows_exited_process_with_open_handle(self):
        kernel32 = FakeKernel32(exit_code=0)
        assert not _is_process_running_windows(10, kernel32, lambda: 0)
        assert kernel32.closed

    def test_windows_exit_code_unreadable_assumes_running(self):
        kernel32 = FakeKernel32(exit_code_ok=False)
        assert _is_process_running_windows(10, kernel32, lambda: 0)
        assert kernel32.closed

    def test_windows_access_denied_means_running(self):
        kernel32 = FakeKernel32(handle=0)
        assert _is_process_running_windows(10, kernel32, lambda: 5)

    def test_windows_missing_process(self):
        kernel32 = FakeKernel32(handle=0)
        assert not _is_process_running_windows(10, kernel32, lambda: 87)  # invalid parameter

    def test_windows_branch_is_used_on_windows(self):
        with mock.patch("pubsub.abstractions._is_windows", return_value=True), mock.patch(
            "pubsub.abstractions._is_process_running_windows", return_value=True
        ) as windows_check:
            assert is_process_running(42)
        windows_check.assert_called_once_with(42)


class TestRetryFs(unittest.TestCase):
    def test_runs_once_on_posix(self):
        calls = []

        def operation():
            calls.append(1)
            raise PermissionError

        with mock.patch("pubsub.abstractions._is_windows", return_value=False):
            with self.assertRaises(PermissionError):
                retry_fs(operation)
        assert len(calls) == 1

    def test_retries_on_windows_until_success(self):
        calls = []

        def operation():
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError
            return "done"

        with mock.patch("pubsub.abstractions._is_windows", return_value=True), mock.patch(
            "pubsub.abstractions.time.sleep"
        ):
            assert retry_fs(operation) == "done"
        assert len(calls) == 3

    def test_gives_up_after_the_last_attempt(self):
        calls = []

        def operation():
            calls.append(1)
            raise PermissionError

        with mock.patch("pubsub.abstractions._is_windows", return_value=True), mock.patch(
            "pubsub.abstractions.time.sleep"
        ):
            with self.assertRaises(PermissionError):
                retry_fs(operation, attempts=4)
        assert len(calls) == 4

    def test_other_errors_are_not_retried(self):
        calls = []

        def operation():
            calls.append(1)
            raise FileNotFoundError

        with mock.patch("pubsub.abstractions._is_windows", return_value=True):
            with self.assertRaises(FileNotFoundError):
                retry_fs(operation)
        assert len(calls) == 1


class TestWindowsPathLength(unittest.TestCase):
    BASE = Path("C:\\pubsub")  # 9 characters

    def name_of_length(self, directory_name_length):
        return "a" * directory_name_length

    def test_formula(self):
        # base + "\purge\" (7) + token and "_" (9) + name + "\" (1) + longest entry (27)
        assert longest_channel_path_length("C:\\pubsub", "abc") == 9 + 7 + 9 + 3 + 1 + 27

    def test_259_characters_is_accepted(self):
        name = self.name_of_length(WINDOWS_MAX_PATH - 1 - 53)
        assert longest_channel_path_length(self.BASE, name) == 259
        check_windows_path_length(self.BASE, name, windows=True, long_paths=False)

    def test_260_characters_raises(self):
        name = self.name_of_length(WINDOWS_MAX_PATH - 53)
        assert longest_channel_path_length(self.BASE, name) == 260
        with self.assertRaises(OSError) as context:
            check_windows_path_length(self.BASE, name, windows=True, long_paths=False)
        error = context.exception
        assert error.errno == errno.ENAMETOOLONG
        text = str(error)
        assert "260" in text and "259" in text
        assert "Disable path length limit" in text
        assert "LongPathsEnabled" in text
        assert "PUBSUB_HOME" in text

    def test_long_paths_enabled_skips_the_check(self):
        name = self.name_of_length(500)
        check_windows_path_length(self.BASE, name, windows=True, long_paths=True)

    def test_other_platforms_skip_the_check(self):
        name = self.name_of_length(500)
        check_windows_path_length(self.BASE, name, windows=False, long_paths=False)

    def test_long_base_dir_is_reported_too(self):
        base = Path("C:\\" + "x" * 300)
        with self.assertRaises(OSError):
            check_windows_path_length(base, "t_abc_1", windows=True, long_paths=False)

    def test_setting_is_read_once_and_cached(self):
        with mock.patch.object(abstractions, "_long_paths_cache", None), mock.patch(
            "pubsub.abstractions._read_long_paths_setting", return_value=True
        ) as read:
            assert windows_long_paths_enabled()
            assert windows_long_paths_enabled()
            assert read.call_count == 1

    def test_unreadable_setting_counts_as_disabled(self):
        with mock.patch("pubsub.abstractions._is_windows", return_value=True):
            with mock.patch.dict(sys.modules, {"winreg": None}):  # import fails
                assert abstractions._read_long_paths_setting() is False

    def test_windows_error_206_is_translated(self):
        error = OSError(3, "The system cannot find the path specified")
        error.winerror = 206
        with self.assertRaises(OSError) as context:
            raise_if_path_too_long(error)
        assert context.exception.errno == errno.ENAMETOOLONG
        assert "LongPathsEnabled" in str(context.exception)

    def test_other_errors_are_left_alone(self):
        raise_if_path_too_long(OSError(errno.EPERM, "denied"))
        error = OSError(5, "denied")
        error.winerror = 5
        raise_if_path_too_long(error)

    def test_channel_constructor_raises_before_touching_the_disk(self):
        base = Path("/" + "x" * 300)
        with mock.patch.object(abstractions, "_base_dir_cache", base), mock.patch(
            "pubsub.abstractions._is_windows", return_value=True
        ), mock.patch.object(abstractions, "_long_paths_cache", False):
            with self.assertRaises(OSError) as context:
                Channel("some.topic")
        assert context.exception.errno == errno.ENAMETOOLONG
        assert not base.exists()

    def test_channel_constructor_ignores_the_limit_without_windows(self):
        base = Path("/" + "x" * 300)
        with mock.patch.object(abstractions, "_base_dir_cache", base):
            channel = Channel("some.topic")
        assert not channel.is_open


class TestDirectories(unittest.TestCase):
    def test_tmp_and_purge_are_under_the_base_dir(self):
        base = abstractions.get_base_dir()
        assert get_tmp_dir() == base / "tmp"
        assert get_purge_dir() == base / "purge"


if __name__ == "__main__":
    unittest.main()
