from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/spatial-room"))

from editor import Editor  # noqa: E402
from room_model import Box, Room, save  # noqa: E402
from room_api import snapshot, wall_anchor, walls  # noqa: E402
from session import Session, box_at_point, segments_for_room  # noqa: E402


class RoomAPIAndEraseTest(unittest.TestCase):
    def setUp(self):
        self.room = Room("Living room", 73, corners=[(-2,-2), (2,-2), (2,2), (-2,2)], closed=True)
        self.box = Box("a"*32, "COUCH", 0, 0, .8, 45, 1.8, .9, .8)
        self.room.boxes.append(self.box)

    def test_wall_anchor_faces_room_and_is_offset_inside(self):
        w = walls(self.room)
        self.assertEqual(len(w), 4)
        pose = wall_anchor(self.room, 0, along=.5, height=1.2, inset=.05)
        self.assertEqual(pose["wall_id"], w[0]["id"])
        self.assertEqual(pose["position"][1], 1.2)
        self.assertAlmostEqual(sum(v*v for v in pose["normal"]), 1.0, places=6)
        with self.assertRaises(ValueError):
            wall_anchor(self.room, 99)

    def test_readonly_snapshot_requires_matching_tracking_universe(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"room.json"
            save(path, self.room)
            data = snapshot(path, universe=73)
            self.assertFalse(data["alignment_verified"])
            self.assertEqual(len(data["walls"]), 4)
            with self.assertRaisesRegex(ValueError, "mismatch"):
                snapshot(path, universe=74)
            with self.assertRaisesRegex(ValueError, "known"):
                snapshot(path, universe=0)

    def test_erase_mode_uses_ray_to_select_rotated_box(self):
        s = Session(Editor(self.room), path=Path("/unused"), export_dir=None)
        s.handle("ready 73")
        s.handle("mode")
        self.assertEqual(s.mode, "erase")
        # Ray origin directly above the furniture footprint.
        s.handle("place 0 2 0 0 -1 0")
        self.assertEqual(len(self.room.boxes), 0)
        s.handle("undo")
        self.assertEqual(len(s.editor.room.boxes), 1)
        self.assertIsNotNone(box_at_point(s.editor.room, (.4, .25)))

    def test_select_and_fine_rotate_existing_couch_with_undo(self):
        room = self.room
        s = Session(Editor(room), path=Path("/unused"), export_dir=None)
        s.handle("ready 73")
        # Point at the middle of an existing couch and select with right A.
        s.handle("aim 0 2 0 0 -1 0")
        s.handle("confirm")
        self.assertEqual(s.selected_id, self.box.id)
        self.assertIn("EDIT COUCH", s.display())
        self.assertIn("DRIGHT +1", s.display())
        self.assertEqual(sum(p == 3 for _, _, p in
                             segments_for_room(s.editor.room, selection_id=s.selected_id)), 12)
        # Right thumbstick click rotates +5 degrees; left D-pad adjusts by 1.
        s.handle("rotate")
        self.assertEqual(s.editor.room.boxes[0].yaw_deg, 50)
        s.handle("rotate_left")
        self.assertEqual(s.editor.room.boxes[0].yaw_deg, 49)
        s.handle("rotate_right")
        self.assertEqual(s.editor.room.boxes[0].yaw_deg, 50)
        s.handle("undo")
        self.assertEqual(s.editor.room.boxes[0].yaw_deg, 49)
        self.assertEqual(s.selected_id, self.box.id)

    def test_rotate_new_furniture_settings_in_one_degree_steps(self):
        s = Session(Editor(self.room), path=Path("/unused"), export_dir=None)
        s.handle("ready 73")
        s.handle("rotate")
        self.assertEqual(s.yaw, 5)
        s.handle("rotate_left")
        self.assertEqual(s.yaw, 4)
        s.handle("rotate_right")
        self.assertEqual(s.yaw, 5)
        s.handle("rotate_left")
        s.handle("rotate_left")
        self.assertEqual(s.yaw, 3)

    def test_selection_changes_couch_not_future_furniture_default(self):
        s = Session(Editor(self.room), path=Path("/unused"), export_dir=None)
        s.handle("ready 73")
        s.handle("aim 0 2 0 0 -1 0")
        s.handle("confirm")
        s.handle("rotate_left")
        self.assertEqual(s.editor.room.boxes[0].yaw_deg, 44)
        self.assertEqual(s.yaw, 0)
        s.handle("aim 1.5 2 1.5 0 -1 0")
        s.handle("confirm")
        self.assertIsNone(s.selected_id)
        s.handle("rotate")
        self.assertEqual(s.yaw, 5)
        self.assertEqual(s.editor.room.boxes[0].yaw_deg, 44)

    def test_dpad_height_resizes_selected_couch_and_undoes(self):
        session = Session(Editor(self.room), path=Path("/unused"), export_dir=None)
        session.handle("ready 73")
        session.handle("aim 0 2 0 0 -1 0")
        session.handle("confirm")
        self.assertEqual(session.selected_id, self.box.id)
        original_bottom = self.box.top_y - self.box.h

        session.handle("height_up")
        box = session.editor.room.boxes[0]
        self.assertAlmostEqual(box.h, 0.85)
        self.assertAlmostEqual(box.top_y, 0.85)
        self.assertAlmostEqual(box.top_y - box.h, original_bottom)
        self.assertIn("H 0.85M", session.display())

        session.handle("height_down")
        self.assertAlmostEqual(session.editor.room.boxes[0].h, 0.80)
        session.handle("undo")
        self.assertAlmostEqual(session.editor.room.boxes[0].h, 0.85)
        self.assertEqual(session.selected_id, self.box.id)

        # Right Y still advances through the height presets.
        session.handle("height")
        self.assertAlmostEqual(session.editor.room.boxes[0].h, 1.10)
        self.assertAlmostEqual(session.editor.room.boxes[0].top_y, 1.10)

    def test_dpad_height_edits_next_box_when_no_selection(self):
        session = Session(Editor(self.room), path=Path("/unused"), export_dir=None)
        session.handle("ready 73")
        session.handle("height_up")
        self.assertAlmostEqual(session.height, 0.80)
        self.assertAlmostEqual(session.editor.room.boxes[0].h, 0.8)
        session.handle("height_down")
        self.assertAlmostEqual(session.height, 0.75)
        session.handle("height")
        self.assertAlmostEqual(session.height, 1.10)

    def test_selected_height_respects_ceiling_and_minimum(self):
        session = Session(Editor(self.room), path=Path("/unused"), export_dir=None)
        session.handle("ready 73")
        session.handle("aim 0 2 0 0 -1 0")
        session.handle("confirm")
        session.editor.dispatch({"action": "resize_box", "id": self.box.id, "height": 2.5})
        history_length = len(session.editor.history)
        with self.assertRaisesRegex(ValueError, "ceiling"):
            session.handle("height_up")
        self.assertAlmostEqual(session.editor.room.boxes[0].h, 2.5)
        self.assertEqual(len(session.editor.history), history_length)
        session.editor.dispatch({"action": "resize_box", "id": self.box.id, "height": 0.05})
        with self.assertRaisesRegex(ValueError, "5 cm"):
            session.handle("height_down")
        self.assertAlmostEqual(session.editor.room.boxes[0].h, 0.05)

    def test_resize_keeps_nonzero_existing_bottom_height(self):
        self.box.top_y = 1.0
        session = Session(Editor(self.room), path=Path("/unused"), export_dir=None)
        session.handle("ready 73")
        session.handle("aim 0 2 0 0 -1 0")
        session.handle("confirm")
        session.handle("height_up")
        box = session.editor.room.boxes[0]
        self.assertAlmostEqual(box.h, 0.85)
        self.assertAlmostEqual(box.top_y, 1.05)
        self.assertAlmostEqual(box.top_y - box.h, 0.2)

    def test_erase_highlight(self):
        normal = segments_for_room(self.room)
        highlighted = segments_for_room(self.room, selection_id=self.box.id)
        self.assertEqual(len(normal), len(highlighted))
        self.assertEqual(sum(item[2] == 3 for item in highlighted), 12)

    def test_universe_change_event_fails_closed(self):
        s = Session(Editor(self.room), path=Path("/unused"), export_dir=None)
        with self.assertRaisesRegex(ValueError, "mismatch|!="):
            s.handle("universe 74")
        self.assertEqual(s.editor.room.universe, 73)


if __name__ == "__main__":
    unittest.main()
