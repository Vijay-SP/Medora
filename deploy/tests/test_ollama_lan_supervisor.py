"""Exercise reconnect/crash recovery with real child processes, without toggling Wi-Fi."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ollama_lan_supervisor.py"


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), "Wi-Fi recovery supervisor is not implemented")
        spec = importlib.util.spec_from_file_location("lan_supervisor", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.events = Path(self.tmp.name) / "starts.txt"
        child = Path(self.tmp.name) / "fake_ollama.py"
        child.write_text(
            "import os, pathlib, time\n"
            f"with pathlib.Path({str(self.events)!r}).open('a') as f:\n"
            " f.write(os.environ['OLLAMA_HOST']+'\\n'); f.flush()\n"
            "while True: time.sleep(1)\n"
        )
        self.server = self.module.Supervisor([sys.executable, str(child)])
        self.addCleanup(self.server.stop)

    def wait_for_starts(self, count):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            lines = self.events.read_text().splitlines() if self.events.exists() else []
            if len(lines) >= count:
                return lines
            time.sleep(0.02)
        self.fail(f"Expected {count} server starts")

    def test_starts_after_offline_boot_then_rebinds_after_address_change(self):
        self.server.tick(None)
        self.assertFalse(self.events.exists())
        self.server.tick("192.168.1.20")
        first = self.server.process
        self.wait_for_starts(1)
        self.server.tick(None)
        self.assertIsNotNone(first.poll(), "old listener must stop while disconnected")
        self.server.tick("192.168.1.30")
        self.assertEqual(self.wait_for_starts(2), ["192.168.1.20:11434", "192.168.1.30:11434"])

    def test_same_address_reconnect_and_crashed_child_restart(self):
        self.server.tick("192.168.1.20")
        self.wait_for_starts(1)
        first = self.server.process
        self.server.tick("192.168.1.20", healthy=True)
        self.assertEqual(self.server.process.pid, first.pid)
        self.server.tick(None)
        self.server.tick("192.168.1.20")
        self.wait_for_starts(2)
        second = self.server.process
        second.kill()
        second.wait(timeout=3)
        self.server.tick("192.168.1.20")
        self.assertEqual(len(self.wait_for_starts(3)), 3)
        self.assertNotEqual(self.server.process.pid, second.pid)

    def test_transient_health_failure_does_not_restart_but_repeated_failure_does(self):
        self.server.tick("192.168.1.20")
        self.wait_for_starts(1)
        first = self.server.process
        self.server.tick("192.168.1.20", healthy=False)
        self.server.tick("192.168.1.20", healthy=True)
        self.assertEqual(self.server.process.pid, first.pid)
        for _ in range(self.module.HEALTH_FAILURE_LIMIT):
            self.server.tick("192.168.1.20", healthy=False)
        self.assertIsNotNone(first.poll())
        self.assertEqual(len(self.wait_for_starts(2)), 2)

    def test_only_private_lan_ipv4_addresses_are_accepted(self):
        for address in ["192.168.1.2", "10.1.2.3", "172.16.0.2"]:
            self.assertEqual(self.module.private_ipv4(address), address)
        for address in ["", "127.0.0.1", "169.254.1.1", "8.8.8.8", "::1", "invalid"]:
            self.assertIsNone(self.module.private_ipv4(address))


if __name__ == "__main__":
    unittest.main()
