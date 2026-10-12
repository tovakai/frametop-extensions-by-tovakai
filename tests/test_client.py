import secrets
import socket
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))
from frametop_ext import ExtensionError, Frametop  # noqa: E402


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.name = "ft-ext-test-" + secrets.token_hex(8)
        self.srv.bind("\0" + self.name)
        self.srv.settimeout(1.5)
        self.addCleanup(self.srv.close)

    def reply(self, expected, answer, invoke):
        seen = []
        def serve():
            command, address = self.srv.recvfrom(4096)
            seen.append(command.decode())
            self.srv.sendto(answer.encode(), address)
        thread = threading.Thread(target=serve)
        thread.start()
        try:
            result = invoke(Frametop(self.name))
            self.assertEqual(seen, [expected])
            return result
        finally:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    def test_negotiation(self):
        self.assertEqual(self.reply("ext api", "ok 1", lambda ft: ft.api_version()), 1)
        caps = self.reply("ext caps", "ok screen.move screen.opacity",
                          lambda ft: ft.capabilities())
        self.assertEqual(caps, {"screen.move", "screen.opacity"})

    def test_controls_and_errors(self):
        self.reply("ext opacity 1 0.600000 250", "ok",
                   lambda ft: ft.opacity(1, 0.6, 250))
        self.reply("ext move 1 0.000000 1.500000 -1.000000 0.000000 0.000000 0.000000 450",
                   "ok", lambda ft: ft.move(1, 0, 1.5, -1, 0, 0, 0, 450))
        with self.assertRaises(ExtensionError):
            self.reply("ext status 1", "error no desktop screen 1",
                       lambda ft: ft.screen_status(1))
        with self.assertRaises(ValueError):
            Frametop(self.name).opacity(1, float("nan"))


if __name__ == "__main__":
    unittest.main()
