import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/spatial-room"
sys.path.insert(0, str(PLUGIN))

import session as spatial_session  # noqa: E402
from editor import Editor  # noqa: E402
from room_model import Room  # noqa: E402
from vr_input import BUTTON_ACTIONS, ButtonMapper  # noqa: E402


def update(side, path, value):
    return json.dumps({
        "type": "update_component_states", "device": f"/user/hand/{side}",
        "components": {f"/input/{path}/click": value}
    })


class ControllerInputTests(unittest.TestCase):
    def test_frame_specific_buttons_are_mapped_to_actual_hands(self):
        self.assertEqual(BUTTON_ACTIONS[("right", "trigger")], "place")
        self.assertEqual(BUTTON_ACTIONS[("left", "x")], "save")
        self.assertEqual(BUTTON_ACTIONS[("left", "y")], "height")
        self.assertNotIn(("right", "x"), BUTTON_ACTIONS)
        self.assertNotIn(("right", "y"), BUTTON_ACTIONS)

    def test_rising_edges_only(self):
        mapper = ButtonMapper()
        sides = {"/user/hand/right": "right", "/user/hand/left": "left"}
        self.assertEqual(mapper.feed(update("right", "trigger", True), sides), ["place"])
        self.assertEqual(mapper.feed(update("right", "trigger", True), sides), [])
        self.assertEqual(mapper.feed(update("right", "trigger", False), sides), [])
        self.assertEqual(mapper.feed(update("right", "trigger", True), sides), ["place"])
        self.assertEqual(mapper.feed(update("left", "x", True), sides), ["save"])
        self.assertEqual(mapper.feed(update("right", "x", True), sides), [])

    def test_controller_root_changes_and_bad_events_are_ignored(self):
        mapper = ButtonMapper()
        sides = {"/devices/cv/frame-controller-1": "right"}
        self.assertEqual(mapper.feed(
            json.dumps({"type": "update_component_states", "device": "/devices/cv/frame-controller-1",
                        "components": {"/input/a/click": True}}), sides), ["confirm"])
        for message in ["not-json", "{}", json.dumps({"type": "different"}),
                        json.dumps({"type": "update_component_states", "device": "unknown",
                                    "components": {"/input/a/click": True}})]:
            self.assertEqual(mapper.feed(message, sides), [])

    def test_actual_pipe_newline_reaches_room_editor(self):
        # A fake OpenVR executable tests the real subprocess/stdin/stdout bridge
        # without SteamVR. It reports a controller click only when it receives
        # a proper newline-delimited input command from the read-only watcher.
        fake = """#!/usr/bin/env python3
import signal
import sys
signal.alarm(3)
assert sys.argv[1] == "--read-only-input"
print("ready 123", flush=True)
for line in sys.stdin:
    if line.strip() == "input place":
        print("place 0 2 0 0 -1 0", flush=True)
        break
"""
        with tempfile.TemporaryDirectory() as folder:
            native = Path(folder) / "fake-room-vr"
            actions = Path(folder) / "actions.json"
            native.write_text(fake)
            native.chmod(native.stat().st_mode | stat.S_IXUSR)
            actions.write_text("{}")
            editor = Editor(Room("Test", 0))
            run = spatial_session.Session(editor, path=Path(folder) / "room.json", export_dir=None)

            def reader(stop, on_press, on_status, *, debug=False):
                on_status("test connected")
                on_press("place")

            with patch.object(spatial_session, "watch", reader):
                exit_code = spatial_session.run(native, actions, run)
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(editor.room.corners), 1)
            self.assertEqual(editor.room.universe, 123)


if __name__ == "__main__":
    unittest.main()
