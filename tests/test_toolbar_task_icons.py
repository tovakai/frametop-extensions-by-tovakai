"""Running-app icon recovery when KWin and Start desktop identities disagree."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

DIR=Path(__file__).resolve().parents[1]/"plugins"/"spatial-toolbar"
sys.path.insert(0,str(DIR))
import task_icons
import ft_desktop
import ft_taskbar_model as model


class TaskIcons(unittest.TestCase):
    def test_hidden_desktop_entry_supplies_real_icon(self):
        # KWin publishes a desktop-file name but OnlyShowIn may have excluded
        # that app from the Start catalog. It still has a valid Icon= value.
        win={"id":"37", "desktop":"org.example.Inspector", "cls":"Inspector",
             "caption":"Inspector", "minimized":False}
        task=model.merge_tasks([], [win], [], "37")[0]
        enriched=task_icons.task_sources([task],[win],lambda desktop: {
            "icon":"org.example.Inspector-symbolic"
        })[0]
        self.assertEqual(enriched["id"],"org.example.inspector")
        self.assertEqual(enriched["icon_candidates"][0],"org.example.Inspector")
        self.assertIn("org.example.Inspector-symbolic",enriched["icon_candidates"])
        self.assertIn("Inspector",enriched["icon_candidates"])

    def test_existing_icon_remains_first_choice(self):
        win={"id":"1","desktop":"firefox", "cls":"firefox"}
        task={"id":"firefox","desktop_id":"firefox.desktop","icon":"firefox",
              "windows":[{"id":"1"}]}
        enriched=task_icons.task_sources([task],[win],lambda x:{"icon":"vendor-firefox"})[0]
        self.assertEqual(enriched["icon_candidates"][0],"firefox")
        self.assertIn("vendor-firefox",enriched["icon_candidates"])

    def test_window_class_used_for_appimage_without_desktop(self):
        win={"id":"3", "desktop":"", "cls":"AppImageTool",
             "caption":"AppImageTool"}
        task=model.merge_tasks([], [win], [])[0]
        enriched=task_icons.task_sources([task],[win])[0]
        self.assertIn("AppImageTool",enriched["icon_candidates"])
        self.assertEqual(len(enriched["windows"]),1)

    def test_bad_types_are_ignored_and_icon_names_deduplicated(self):
        task={"icon":None,"desktop_id":"demo.desktop"}
        icons=task_icons.icon_candidates(task,[{"desktop":"demo","cls":"demo"}])
        self.assertEqual(icons,["demo"])

    def test_absolute_icon_path_translated_when_inside_distrobox(self):
        with mock.patch.object(ft_desktop.os.path,"isfile",side_effect=lambda p: (
                p=="/run/host/var/lib/flatpak/app/org.example.Icon/icon.png")):
            translated=ft_desktop._host_icon_path(
                "/var/lib/flatpak/app/org.example.Icon/icon.png")
            self.assertEqual(translated,
                "/run/host/var/lib/flatpak/app/org.example.Icon/icon.png")

    def test_real_existing_absolute_icon_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as root:
            png=Path(root)/"local-icon.png"
            png.write_bytes(b"png")
            self.assertEqual(ft_desktop._host_icon_path(str(png)),str(png))


if __name__=="__main__":
    unittest.main()
