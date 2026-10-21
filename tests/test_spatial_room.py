import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/spatial-room"
sys.path.insert(0, str(PLUGIN))
from editor import Editor, box_between, floor_hit  # noqa: E402
from room_model import Room, load, save, signed_area, to_frameport, validate_outline  # noqa: E402


def ray(x, z, y=1.5):
    import math
    l = math.sqrt(x*x + y*y + z*z)
    return {"origin": [0, y, 0], "direction": [x/l, -y/l, z/l]}


class SpatialRoomTest(unittest.TestCase):
    def test_manual_room_vr_events_export_without_mesh(self):
        room = Room("Living room", 123)
        editor = Editor(room)
        for x, z in [(-2, -2), (2, -2), (2, 2), (-2, 2)]:
            editor.dispatch({"action": "corner", **ray(x, z)})
        editor.dispatch({"action": "close"})
        editor.dispatch({"action": "box_start", **ray(-1, 0)})
        editor.dispatch({"action": "box_finish", **ray(1, 1), "label": "TABLE", "height": 0.75})
        out = to_frameport(room, now=10)
        self.assertIn("frameport-room 1\n", out)
        self.assertIn("universe 123\nsource manual\ntime 10\n", out)
        self.assertIn("outline 4 ", out)
        self.assertEqual(out.count("\nwall "), 4)
        self.assertEqual(out.count("\nvolume "), 1)
        self.assertNotIn("\nmesh ", out)
        self.assertEqual(len(out.strip().splitlines()[-1].split()), 10)
        self.assertGreater(signed_area(room.corners), 0)
        self.assertEqual(out, to_frameport(room, now=10))

    def test_clockwise_outline_is_exported_counterclockwise(self):
        room = Room("Reverse", 0, corners=[(-1,-1), (-1,1), (1,1), (1,-1)], closed=True)
        txt = to_frameport(room, now=1)
        outline = txt.split("outline 4 ")[1].splitlines()[0].split()
        coords = list(map(float, outline))
        self.assertGreater(signed_area(list(zip(coords[::2], coords[1::2]))), 0)

    def test_rejects_self_intersecting_outline(self):
        for pts in [[(0,0), (3,3), (0,3), (3,0)],
                    [(0,0), (3,0), (1,0), (3,3), (0,3)]]:
            with self.subTest(points=pts), self.assertRaises(ValueError):
                validate_outline(pts)

    def test_invalid_rays(self):
        for origin, direction in [([0,1,0], [0,1,0]), ([0,1,0], [0,0,1]),
                                  ([0,1,0], [0,-2,0]), ([0,20,0], [0,-1,0]),
                                  ([0,float("nan"),0], [0,-1,0])]:
            with self.subTest(origin=origin, direction=direction), self.assertRaises(ValueError):
                floor_hit(origin, direction, 0)

    def test_undo_box_placement(self):
        editor = Editor(Room("Test", 12, corners=[(-2,-2),(2,-2),(2,2),(-2,2)], closed=True))
        editor.dispatch({"action": "box_start", **ray(0,0.5)})
        editor.dispatch({"action": "box_finish", **ray(1,1), "label": "COUCH"})
        self.assertEqual(len(editor.room.boxes), 1)
        editor.dispatch({"action": "undo"})
        self.assertEqual(len(editor.room.boxes), 0)
        self.assertIsNotNone(editor.pending)
        editor.dispatch({"action": "undo"})
        self.assertIsNone(editor.pending)

    def test_rotated_footprint_and_label_validation(self):
        box = box_between((-1,-2), (1,1), "SCREEN", 1, 0, 45)
        self.assertGreater(box.w, 0.05)
        self.assertGreater(box.d, 0.05)
        with self.assertRaises(ValueError):
            box_between((0,0), (1,1), "EVIL", 1, 0)

    def test_roundtrip_and_overwrite_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"room.json"
            room = Room("Room", 0, corners=[(-1,-1),(1,-1),(1,1),(-1,1)], closed=True)
            save(path, room, replace=False)
            self.assertEqual(load(path).to_dict(), room.to_dict())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                save(path, room, replace=False)
            data = json.loads(path.read_text())
            data["universe"] = -1
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load(path)

    def test_cli_export_and_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            room, output = Path(tmp)/"room.json", Path(tmp)/"room.txt"
            cmd = [sys.executable, str(PLUGIN/"room.py")]
            self.assertEqual(subprocess.run(cmd+["new",str(room),"--name","Room","--universe","0"],
                                            capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(cmd+["export",str(room),str(output)],
                                            capture_output=True).returncode, 1)
            self.assertFalse(output.exists())
            draft = load(room)
            draft.corners = [(-1,-1),(1,-1),(1,1),(-1,1)]
            draft.closed = True
            save(room, draft)
            self.assertEqual(subprocess.run(cmd+["export",str(room),str(output)],
                                            capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run(cmd+["export",str(room),str(output)],
                                            capture_output=True).returncode, 1)

    def test_edit_protocol_errors_are_nonfatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)/"room.json"
            save(room, Room("Room", 123))
            result = subprocess.run([sys.executable, str(PLUGIN/"room.py"),"edit",str(room)],
                input='{"action":"close"}\n{"action":"status"}\n{"action":"save"}\n',
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual([r["ok"] for r in rows], [False, True, True])
            self.assertFalse(load(room).closed)


if __name__ == "__main__":
    unittest.main()
