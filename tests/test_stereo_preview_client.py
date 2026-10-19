import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))
from frametop_ext import ExtensionError, Frametop  # noqa: E402


class FakeFrametop(Frametop):
    def __init__(self, *, supported=True):
        self.commands = []
        self.supported = supported

    def api_version(self):
        self.commands.append("ext api")
        return 1

    def capabilities(self):
        self.commands.append("ext caps")
        return {"screen.stereo.preview"} if self.supported else {"screen.status"}

    def request(self, command):
        self.commands.append(command)
        if command.endswith(" state"):
            return "ok on strength 0.00600 convergence 0.50000 swap 1 mode luminance"
        return "ok"


class StereoPreviewClientTests(unittest.TestCase):
    def test_enable_and_disable(self):
        ft = FakeFrametop()
        ft.stereo_preview(1, 0.01, 0.4, True)
        self.assertEqual(ft.commands[-1], "ext stereo-preview 1 on 0.010000 0.400000 1")
        ft.stereo_preview_off(1)
        self.assertEqual(ft.commands[-1], "ext stereo-preview 1 off")

    def test_state(self):
        state = FakeFrametop().stereo_preview_state(1)
        self.assertEqual(state, {
            "enabled": True, "strength": 0.006, "convergence": 0.5,
            "swap": True, "mode": "luminance",
        })

    def test_old_core_fails_closed(self):
        ft = FakeFrametop(supported=False)
        with self.assertRaises(ExtensionError):
            ft.stereo_preview(1)
        self.assertNotIn("ext stereo-preview 1 on 0.006000 0.500000 0", ft.commands)

    def test_validate_before_contacting_compositor(self):
        for invalid in (-0.1, 0.031, float("nan"), float("inf")):
            ft = FakeFrametop()
            with self.assertRaises(ValueError):
                ft.stereo_preview(1, strength=invalid)
            self.assertEqual(ft.commands, [])
        with self.assertRaises(ValueError):
            FakeFrametop().stereo_preview(1, swap=1)
        with self.assertRaises(ValueError):
            FakeFrametop().stereo_preview(0)


if __name__ == "__main__":
    unittest.main()
