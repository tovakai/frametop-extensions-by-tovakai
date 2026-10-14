"""Offline integration tests for the real Spatial Profiles runtime and CLI."""
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "plugins" / "spatial-profiles"
sys.path.insert(0, str(ROOT / "sdk"))
sys.path.insert(0, str(RUNTIME_DIR))
import spatial_runtime as spatial  # noqa: E402

CLI = RUNTIME_DIR / "profiles.py"


def screen_pose(x, y, z, yaw=0, pitch=0, roll=0, metres=1.6, curve=0, pin="none"):
    # OpenVR PanelPose: columns are right, up, front, with positive yaw to left.
    a, p, r = map(math.radians, (yaw, pitch, roll))
    front = [math.sin(a)*math.cos(p), -math.sin(p), math.cos(a)*math.cos(p)]
    right = [math.cos(a), 0, -math.sin(a)]
    up = [
        front[1]*right[2] - front[2]*right[1],
        front[2]*right[0] - front[0]*right[2],
        front[0]*right[1] - front[1]*right[0],
    ]
    axis_x = [right[i]*math.cos(r) + up[i]*math.sin(r) for i in range(3)]
    axis_y = [up[i]*math.cos(r) - right[i]*math.sin(r) for i in range(3)]
    nums = [x,y,z,*axis_x,*axis_y,*front,metres,metres*.5625,curve]
    tail = " ".join(["0"] * 12) if pin != "none" else ""
    return "ok " + " ".join(str(v) for v in nums) + " " + pin + (" " + tail if tail else "")


class FakeClient:
    def __init__(self, count=2):
        self.count = count
        self.head = (0, 1.65, 0, 0)
        self.poses = [screen_pose(-.8, 1.5, -1.5, 20, 5, 10),
                      screen_pose(.8, 1.5, -1.5, -20, -5, -10)][:count]
        self.alpha = [1.0] * count
        self.hidden = set()
        self.calls = []
        self.error_on = None
        self.capabilities = {"screen.move", "screen.opacity", "screen.status"}

    def api_version(self):
        return 1

    def screen_status(self, number):
        return {"opacity": str(self.alpha[number-1]), "moving": "0",
                "fading": "0", "pinned": "none"}

    def request(self, command):
        self.calls.append(command)
        if self.error_on is not None and command.startswith(self.error_on):
            self.error_on = None
            raise spatial.ExtensionError("simulated compositor error")
        items = command.split()
        if command == "head":
            return "ok " + " ".join(str(x) for x in self.head)
        if command == "screens":
            return "ok " + str(self.count) + " " + " ".join(
                f"{n}:1920x1080:1.600" for n in range(1,self.count+1))
        if command == "concealed":
            return "ok" + "".join(f" {i}" for i in sorted(self.hidden))
        if items[0] == "get":
            return self.poses[int(items[1])-1]
        if items[0] == "conceal":
            self.hidden.add(int(items[1]))
        if items[0] == "reveal":
            self.hidden.discard(int(items[1]))
        return "ok"

    def move(self, number, x, y, z, yaw, pitch, roll, duration_ms=0):
        self.request(f"ext move {number} {x:.4f} {y:.4f} {z:.4f} "
                     f"{yaw:.2f} {pitch:.2f} {roll:.2f} {duration_ms}")
        self.poses[number-1] = screen_pose(x, y, z, yaw, pitch, roll)

    def opacity(self, number, alpha, duration_ms=0):
        self.request(f"ext opacity {number} {alpha:.4f} {duration_ms}")
        self.alpha[number-1] = alpha


class SpatialRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "extension" / "profiles.json"
        self.client = FakeClient()

    def test_save_two_world_screens_and_six_slots(self):
        store = spatial.save_current(self.path, "Work", self.client)
        self.assertEqual(store["current"], "Work")
        self.assertEqual(len(store["slots"]), 6)
        self.assertEqual(len(store["profiles"]["Work"]["screens"]), 2)
        self.assertEqual(store["profiles"]["Work"]["screens"][0]["pos"],
                         [-.8, -.15, -1.5])
        self.assertAlmostEqual(store["profiles"]["Work"]["screens"][0]["face"][0], 20)
        self.assertAlmostEqual(store["profiles"]["Work"]["screens"][0]["roll"], 10)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_head_relative_targets_follow_head_yaw(self):
        original = spatial.snapshot(self.client)
        center, face, _ = spatial.targets(original, [1,1.65,2], 90)[0]
        # turn_yaw([-0.8,-0.15,-1.5], 90) = [-1.5,-0.15,0.8]
        self.assertAlmostEqual(center[0], -.5)
        self.assertAlmostEqual(center[1], 1.5)
        self.assertAlmostEqual(center[2], 2.8)
        self.assertAlmostEqual(face[0], 110)
        self.assertAlmostEqual(face[1], 5)

    def test_switch_uses_compositor_animation_and_dimensions(self):
        spatial.save_current(self.path, "Desk", self.client)
        original = spatial.read_store(self.path)["profiles"]["Desk"]
        spatial.bind_slot(self.path, 4, "Desk")
        self.client.calls.clear()
        name = spatial.use_slot(self.path, 4, self.client, 450)
        self.assertEqual(name, "Desk")
        self.assertTrue(any(c.startswith("ext move 1 ") and c.endswith(" 450")
                            for c in self.client.calls))
        self.assertTrue(any(c.startswith("ext opacity 2 ") and c.endswith(" 450")
                            for c in self.client.calls))
        self.assertIn("width 1 1.6000", self.client.calls)
        self.assertIn("curve 1 0.000", self.client.calls)
        self.assertIn("reveal 1", self.client.calls)
        self.assertEqual(spatial.read_store(self.path)["current"], "Desk")
        self.assertEqual(spatial.read_store(self.path)["profiles"]["Desk"], original)

    def test_hidden_persists_between_saves(self):
        self.client.hidden.add(2)
        saved = spatial.save_current(self.path, "Hidden", self.client)
        self.assertTrue(saved["profiles"]["Hidden"]["screens"][1]["hidden"])
        spatial.switch(self.path, "Hidden", self.client, 0)
        self.assertIn(2, self.client.hidden)
        self.assertIn("conceal 2", self.client.calls)

    def test_no_mutation_on_pinned_or_animating(self):
        self.client.poses[0] = screen_pose(0,1,-1,pin="head")
        with self.assertRaisesRegex(spatial.ProfileError, "pinned"):
            spatial.save_current(self.path, "NotSafe", self.client)
        self.assertFalse(self.path.exists())
        self.client.poses[0] = screen_pose(0,1,-1)
        self.client.screen_status = lambda n: {"opacity": "1", "moving": "1",
                                               "fading": "0", "pinned": "none"}
        with self.assertRaisesRegex(spatial.ProfileError, "animating"):
            spatial.save_current(self.path, "NotSafe", self.client)
        self.assertFalse(self.path.exists())

    def test_count_mismatch_raises_before_any_mutations(self):
        spatial.save_current(self.path, "Desk", self.client)
        self.client.count = 1
        self.client.calls.clear()
        with self.assertRaisesRegex(spatial.ProfileError, "screen count"):
            spatial.switch(self.path, "Desk", self.client)
        self.assertFalse(any(x.startswith(("ext move", "ext opacity", "width"))
                             for x in self.client.calls))

    def test_invalid_legacy_features_fail_closed(self):
        saved = spatial.snapshot(self.client)
        for invalid in (
            {**saved, "toolbar": {"enabled": True}},
            {"screens": [dict(saved["screens"][0], pin={"anchor": "yaw-follow"})]},
            {"screens": [dict(saved["screens"][0], opacity=1.5)]},
            {"screens": [dict(saved["screens"][0], roll=float("nan"))]},
            {"screens": [dict(saved["screens"][0], curve=.1)]},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(spatial.ProfileError):
                spatial.validate_profile(invalid)

    def test_partial_switch_failure_attempts_restore(self):
        spatial.save_current(self.path, "Saved", self.client)
        saved_state = spatial.read_store(self.path)
        modified = json.loads(json.dumps(saved_state))
        modified["profiles"]["Saved"]["screens"][0]["metres"] = 2.0
        modified["profiles"]["Saved"]["screens"][0]["opacity"] = .4
        modified["profiles"]["Saved"]["screens"][1]["hidden"] = True
        spatial._write_store(self.path, modified)
        self.client.error_on = "ext move 2 "
        with self.assertRaisesRegex(spatial.ProfileError, "restore"):
            spatial.switch(self.path, "Saved", self.client)
        self.assertEqual(spatial.read_store(self.path)["current"], "Saved")
        self.assertEqual(self.client.alpha[0], 1.0)
        self.assertEqual(self.client.hidden, set())
        self.assertTrue(any(c.startswith("ext move 1 ") and c.endswith(" 0")
                            for c in self.client.calls))

    def test_profile_store_invalid_never_overwritten(self):
        self.path.parent.mkdir(parents=True)
        original = '{"version":77,"profiles":{}}'
        self.path.write_text(original)
        with self.assertRaises(spatial.ProfileError):
            spatial.save_current(self.path, "New", self.client)
        self.assertEqual(self.path.read_text(), original)

    def test_bind_and_delete_clean_slots(self):
        spatial.save_current(self.path, "A", self.client)
        spatial.bind_slot(self.path, 1, "A")
        spatial.bind_slot(self.path, 6, "A")
        out = spatial.delete_profile(self.path, "A")
        self.assertEqual(out["slots"], [None]*6)
        self.assertIsNone(out["current"])


class SpatialCLITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "profiles.json"

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), "--store", str(self.path),
                               *args], capture_output=True, text=True)

    def test_saved_empty_without_writes(self):
        result = self.run_cli("saved", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["profiles"], [])
        self.assertFalse(self.path.exists())

    def test_slots_and_delete_offline(self):
        client = FakeClient()
        spatial.save_current(self.path, "Desk", client)
        slot = self.run_cli("slot", "3", "Desk")
        self.assertEqual(slot.returncode, 0, slot.stderr)
        self.assertEqual(spatial.read_store(self.path)["slots"][2], "Desk")
        listing = self.run_cli("saved", "--json")
        self.assertEqual(json.loads(listing.stdout)["slots"][2], "Desk")
        deleted = self.run_cli("delete", "Desk")
        self.assertEqual(deleted.returncode, 0, deleted.stderr)
        self.assertIsNone(spatial.read_store(self.path)["slots"][2])


if __name__ == "__main__":
    unittest.main()
