"""Reused legacy Displays-popup geometry connected to the new profile extension."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "spatial-toolbar"))
sys.path.insert(0, str(ROOT / "plugins" / "spatial-profiles"))
sys.path.insert(0, str(ROOT / "sdk"))
from test_spatial_runtime import FakeClient  # noqa: E402
import spatial_runtime as spatial  # noqa: E402
import toolbar_profiles  # noqa: E402
import ft_taskbar_model as original  # noqa: E402
import ft_toolbar as layout  # noqa: E402


class DisplaysPopupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "extensions" / "spatial-profiles.json"
        self.client = FakeClient()

    def test_empty_popup_keeps_legacy_layout_and_save_action(self):
        source = original.profiles_layout([], "", [None] * 6)
        popup = toolbar_profiles.displays_popup(self.path)
        self.assertEqual(popup["w"], source["w"])
        self.assertEqual(popup["h"], source["h"])
        self.assertEqual(popup["header"], "Displays")
        self.assertEqual(popup["items"][0]["enabled"], False)
        self.assertEqual(popup["items"][-1]["label"], "Save current arrangement")
        self.assertEqual(popup["items"][-1]["id"], "capture")
        self.assertFalse(self.path.exists(), "opening toolbar popup must be read-only")

    def test_saved_slot_badges_and_active_highlight(self):
        spatial.save_current(self.path, "Work", self.client)
        spatial.save_current(self.path, "Reading", self.client)
        spatial.bind_slot(self.path, 2, "Work")
        popup = toolbar_profiles.displays_popup(self.path)
        items = {item["id"]: item for item in popup["items"]}
        self.assertEqual(items["profile:Work"]["badge"], "2")
        self.assertFalse(items["profile:Work"]["active"])
        self.assertTrue(items["profile:Reading"]["active"])
        self.assertIn("popup:profiles", [x for _, x, _ in layout.button_local_x(layout.DEFAULT_GROUPS)])

    def test_click_profile_switches_using_450ms(self):
        spatial.save_current(self.path, "Work", self.client)
        self.client.calls.clear()
        result = toolbar_profiles.activate("profile:Work", self.path, lambda: self.client)
        self.assertEqual(result, "switched Work")
        self.assertTrue(any(x.startswith("ext move 1 ") and x.endswith(" 450")
                            for x in self.client.calls))

    def test_capture_action_creates_unique_extension_profiles(self):
        toolbar_profiles.activate("capture", self.path, lambda: self.client)
        toolbar_profiles.activate("capture", self.path, lambda: self.client)
        store = spatial.read_store(self.path)
        self.assertEqual(sorted(store["profiles"]), ["Arrangement 1", "Arrangement 2"])
        self.assertEqual(store["current"], "Arrangement 2")

    def test_no_arbitrary_command_or_upstream_settings_action(self):
        for key in ("settings", "", "none", "shell:rm -rf /", "slot:7", "profile:missing"):
            with self.subTest(key=key), self.assertRaises(spatial.ProfileError):
                toolbar_profiles.activate(key, self.path, lambda: self.client)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
