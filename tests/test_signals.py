"""Tests for the graceful shutdown of a subscriber process."""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SUBSCRIBER = """
import sys
from pubsub import Channel, subscribe

channel = Channel("signals.shutdown")
with channel:
    print("ready", flush=True)
    count = subscribe(channel, lambda message: None)
    print(f"returned {count}", flush=True)
"""

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


class TestGracefulShutdown(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="pubsub-signals-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def run_subscriber_and_signal(self, signal_to_send):
        env = dict(os.environ, PUBSUB_HOME=str(self.home))
        env["PYTHONPATH"] = PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        process = subprocess.Popen(
            [sys.executable, "-c", SUBSCRIBER],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            creationflags=flags,
        )
        try:
            assert process.stdout.readline().strip() == "ready"
            process.send_signal(signal_to_send)
            output, errors = process.communicate(timeout=20)
        except BaseException:
            process.kill()
            process.communicate()
            raise
        return process.returncode, output, errors

    def assert_channel_cleaned_up(self):
        """The channel directory is gone and nothing is left to purge."""
        leftovers = [
            entry.name
            for entry in self.home.iterdir()
            if entry.name not in ("tmp", "purge")
        ]
        assert leftovers == []
        purge = self.home / "purge"
        assert not purge.exists() or list(purge.iterdir()) == []

    def assert_returns_minus_one(self, signal_to_send):
        """The signal ends the loop and subscribe returns -1."""
        code, output, errors = self.run_subscriber_and_signal(signal_to_send)
        assert "returned -1" in output, (output, errors)
        assert code == 0, (code, errors)
        self.assert_channel_cleaned_up()

    def test_sigint_stops_the_loop_then_hands_over_to_the_original_handler(self):
        """The loop ends cleanly, then Python's own SIGINT handler raises KeyboardInterrupt."""
        if sys.platform == "win32":
            self.skipTest("Ctrl+C cannot be sent to a single process on Windows")
        code, output, errors = self.run_subscriber_and_signal(signal.SIGINT)
        assert "KeyboardInterrupt" in errors, (output, errors)
        assert code != 0
        # The with block still closed the channel while the exception went through
        self.assert_channel_cleaned_up()

    @unittest.skipIf(sys.platform == "win32", "SIGTERM is never delivered on Windows")
    def test_sigterm_stops_the_subscriber_gracefully(self):
        self.assert_returns_minus_one(signal.SIGTERM)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_ctrl_break_stops_the_subscriber_gracefully(self):
        self.assert_returns_minus_one(signal.CTRL_BREAK_EVENT)


if __name__ == "__main__":
    unittest.main()
