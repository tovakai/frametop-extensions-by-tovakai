"""The OpenVR host must talk to a persistent, private menu worker.

No Cairo/Pango imports needed for these headless protocol tests.
"""
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "spatial-toolbar"))
import menu_worker


class MenuWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Path(self.tmp.name)
        self.calls = []
        def fake_main(args):
            self.calls.append(tuple(args))
            return 0
        self.fake_menu = types.SimpleNamespace(main=fake_main)

    def run_worker(self):
        errors = []
        def serve():
            try:
                menu_worker.serve(self.runtime)
            except Exception as error:
                errors.append(error)
        with patch.dict(sys.modules, {"menu": self.fake_menu}):
            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            ready = False
            for _ in range(100):
                try:
                    menu_worker.request(self.runtime, "ping", timeout=.1)
                    ready = True
                    break
                except (OSError, RuntimeError):
                    time.sleep(.01)
            self.assertTrue(ready, "warm worker did not start")
            try:
                menu_worker.request(self.runtime, "render", "start")
                menu_worker.request(self.runtime, "activate", "start", "cat:Games")
                menu_worker.request(self.runtime, "render", "start")
                menu_worker.request(self.runtime, "render", "toolbar")
                self.assertEqual(self.calls, [
                    ("render","--dir",str(self.runtime),"--kind","start"),
                    ("activate","--dir",str(self.runtime),"--kind","start",
                     "--item","cat:Games"),
                    ("render","--dir",str(self.runtime),"--kind","start"),
                    ("render","--dir",str(self.runtime),"--kind","toolbar"),
                ])
                # Prove invalid/oversized or non-whitelisted commands cannot
                # execute arbitrary entrypoints through the helper protocol.
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
                    conn.settimeout(.5)
                    conn.connect(str(menu_worker.socket_path(self.runtime)))
                    conn.sendall(b"execute\tstart\trm -rf\n")
                    response=conn.recv(1024)
                    self.assertTrue(response.startswith(b"error "))
                self.assertEqual(len(self.calls), 4)
                mode = menu_worker.socket_path(self.runtime).stat().st_mode & 0o777
                self.assertEqual(mode, 0o600)
            finally:
                menu_worker.request(self.runtime, "stop", timeout=1)
                thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertFalse(menu_worker.socket_path(self.runtime).exists())
            self.assertEqual(errors, [])

    def test_persistent_worker_reuses_module_without_spawn(self):
        self.run_worker()

    def test_rejects_newlines_and_unsupported_methods(self):
        for method in ("exec","shell","import","refresh"):
            with self.assertRaises(ValueError):
                menu_worker.request(self.runtime, method)
        for item in ("foo\nstop", "a\tb", "a"*401):
            with self.assertRaises(ValueError):
                menu_worker.request(self.runtime, "activate", "start", item)
        for payload in (b"exec\tstart\t\n", b"render\tstart\tbad\tdata\n",
                        b"render\tstart\t" + b"x"*2050 + b"\n", b"bad"):
            with self.assertRaises(ValueError):
                menu_worker.parse_command(payload)

    def test_refuses_untrusted_runtime(self):
        p = self.runtime / "untrusted"
        p.mkdir(mode=0o755)
        with self.assertRaisesRegex(RuntimeError, "private"):
            menu_worker.serve(p)


if __name__ == "__main__":
    unittest.main()
