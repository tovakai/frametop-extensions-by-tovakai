import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "plugins/spatial-profiles/profiles.py"


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "profiles.json"
        self.store = {
            "current": "Desk",
            "profiles": {
                "Desk": {
                    "screens": [{
                        "pos": [0, 0, -1],
                        "face": [0, 0],
                        "roll": 0,
                        "metres": 1.6,
                        "curve": 0,
                        "pin": {"anchor": "yaw-follow", "rel": [0] * 12},
                        "active_opacity": 1.0,
                        "idle_opacity": 0.6,
                        "attention": {"enabled": True},
                        "hidden": False,
                    }],
                    "instruments": [{"type": "clock"}],
                    "toolbar": {"enabled": True},
                },
            },
            "slots": ["Desk", None, None, None, None, None],
        }
        self.path.write_text(json.dumps(self.store), encoding="utf-8")

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(CLI), "--file", str(self.path), *args],
            capture_output=True, text=True, check=False,
        )

    def test_list_and_show_read_only(self):
        before = self.path.read_bytes()
        result = self.run_cli("list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["slots"][0], "Desk")
        show = self.run_cli("show", "Desk")
        self.assertEqual(show.returncode, 0, show.stderr)
        data = json.loads(show.stdout)
        self.assertEqual(data["screens"][0]["anchor"], "yaw-follow")
        self.assertEqual(data["screens"][0]["idle_opacity"], 0.6)
        self.assertEqual(data["transition_default_ms"], 450)
        self.assertEqual(self.path.read_bytes(), before)

    def test_plan_is_explicit_about_unsupported_behavior(self):
        report = self.run_cli("plan", "Desk")
        self.assertEqual(report.returncode, 0, report.stderr)
        data = json.loads(report.stdout)
        self.assertFalse(data["ready_to_apply"])
        self.assertIn("screen.move", data["api_capabilities"])
        self.assertTrue(any("anchoring API" in issue for issue in data["migration_blockers"]))
        self.assertTrue(any("gaze" in issue for issue in data["migration_blockers"]))
        self.assertTrue(any("toolbar" in issue for issue in data["migration_blockers"]))

    def test_malformed_store_errors_without_mutation(self):
        for bad in (
            {"profiles": {},"slots": []},
            {"profiles": {"Desk": {"screens": []}},"current": None},
            {"profiles": {"Desk": {"screens": [{}]}},"slots": ["Unknown"] + [None]*5},
        ):
            text = json.dumps(bad)
            self.path.write_text(text)
            out = self.run_cli("list")
            self.assertNotEqual(out.returncode, 0)
            self.assertEqual(self.path.read_text(), text)

    def test_missing_profiles_errors_without_writing(self):
        self.path.unlink()
        result = self.run_cli("list")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
