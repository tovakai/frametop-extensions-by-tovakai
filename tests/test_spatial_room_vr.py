import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/spatial-room"))

from editor import Editor  # noqa: E402
from room_model import Room, load  # noqa: E402
from session import Session, box_edges, frameport_snapshot, hud, render_commands, segments_for_room  # noqa: E402


def ray_at(x, z):
    import math
    n = math.sqrt(x*x+z*z+4)
    return f"0 2 0 {x/n} {-2/n} {z/n}"


class VRSessionTest(unittest.TestCase):
    def test_tracking_universe_initialization_and_guard(self):
        s = Session(Editor(Room("Room", 0)), path=Path("/unused"), export_dir=None)
        with self.assertRaisesRegex(ValueError, "unknown"):
            s.handle("ready 0")
        s.handle("ready 333")
        self.assertEqual(s.editor.room.universe, 333)
        room = Room("Old Room", 23, corners=[(-1,-1), (1,-1), (1,1), (-1,1)], closed=True)
        s = Session(Editor(room), path=Path("/unused"), export_dir=None)
        with self.assertRaisesRegex(ValueError, "!= current"):
            s.handle("ready 444")
        self.assertEqual(room.universe, 23)

    def test_enter_corners_close_and_furniture(self):
        s = Session(Editor(Room("Room", 0)), path=Path("/unused"), export_dir=None)
        s.handle("ready 200")
        for x, z in [(-2,-2), (2,-2), (2,2), (-2,2)]:
            s.handle("place " + ray_at(x,z))
        s.handle("confirm")
        self.assertTrue(s.editor.room.closed)
        self.assertEqual(s.mode, "box")
        s.handle("place " + ray_at(-1,-1))
        s.handle("place " + ray_at(0,0))
        self.assertEqual(len(s.editor.room.boxes), 1)
        self.assertEqual(s.editor.room.boxes[0].label, "TABLE")
        s.handle("undo")
        self.assertEqual(len(s.editor.room.boxes), 0)

    def test_box_edges_are_3d_and_yaw_aware(self):
        edges = box_edges(1,2,1,2,1,0.7,90,1)
        self.assertEqual(len(edges), 12)
        values = [v for a,b,_ in edges for p in (a,b) for v in p]
        self.assertTrue(all(-1 <= v <= 4 for v in values))
        self.assertTrue(any(a[0] == b[0] and a[1] != b[1] for a,b,_ in edges))

    def test_room_outline_and_aim_marker(self):
        room = Room("Room", 123, corners=[(-1,-1),(1,-1),(1,1),(-1,1)], closed=True)
        shapes = segments_for_room(room, aiming=(0,0))
        self.assertEqual(len(shapes), 14)  # four floor, ceiling, vertical + cursor cross
        self.assertTrue(all(0 <= item[2] <= 3 for item in shapes))

    def test_render_command_safety(self):
        text = render_commands([((0,0,0), (1,2,3), 1)], "Table 0.75m\nquit")
        self.assertIn("segment 0.000000", text)
        self.assertNotIn("\nquit\n", text)
        self.assertTrue(text.startswith("clear\n"))
        self.assertTrue(text.endswith("\n"))
        with self.assertRaises(ValueError):
            render_commands([((float("nan"),0,0),(1,2,3),0)], "no")

    def test_save_staged_export_only_with_user_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, exports = Path(tmp)/"room.json", Path(tmp)/"exports"
            room = Room("Room", 123, corners=[(-1,-1),(1,-1),(1,1),(-1,1)], closed=True)
            session = Session(Editor(room), path=path, export_dir=exports)
            session.handle("ready 123")
            session.handle("save")
            self.assertEqual(load(path).id, room.id)
            snaps = list(exports.iterdir())
            self.assertEqual(len(snaps), 1)
            self.assertIn("frameport-room 1", snaps[0].read_text())
            self.assertEqual(snaps[0].stat().st_mode & 0o777, 0o600)
            session.handle("save")
            self.assertEqual(len(list(exports.iterdir())), 2)

    def test_no_instant_frameport_install_or_export_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"room.json"
            s=Session(Editor(Room("Draft",100)),path=path,export_dir=None)
            s.handle("ready 100")
            s.handle("save")
            self.assertTrue(path.exists())
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_broken_or_unknown_native_events(self):
        s=Session(Editor(Room("Room",100)),path=Path("/unused"),export_dir=None)
        with self.assertRaises(ValueError):
            s.handle("place 1 2")
        with self.assertRaises(ValueError):
            s.handle("evil")
        with self.assertRaises(ValueError):
            s.handle("ready not-a-number")


if __name__ == "__main__":
    unittest.main()
