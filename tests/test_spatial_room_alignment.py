"""Room registration regressions: existing saves, global poses and physical hit mapping."""
from pathlib import Path
import json
import math
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/spatial-room"))
from editor import Editor
from room_model import Alignment, Box, Room, load, save, to_frameport
from room_api import snapshot, wall_anchor, walls
from session import Session


MATRIX = (1.,0.,0.,0., 0.,1.,0.,0., 0.,0.,1.,0.)


def room():
    result = Room("Living Room", 73, corners=[(-2.,-2.),(2.,-2.),(2.,2.),(-2.,2.)],
                  closed=True)
    result.boxes = [Box("a"*32,"COUCH",0.,0.,.8,45.,1.8,.9,.8)]
    return result


class AlignmentTests(unittest.TestCase):
    def test_old_v1_save_uses_identity_and_preserves_layout(self):
        raw = room().to_dict()
        raw.pop("alignment")
        legacy = Room.from_dict(raw)
        self.assertEqual(legacy.alignment, Alignment())
        self.assertEqual(legacy.corners, room().corners)
        self.assertEqual(legacy.boxes[0].label, "COUCH")
        self.assertEqual(legacy.to_world((2, 3)), (2, 3))

    def test_forward_inverse_and_yaw_about_static_room_centre(self):
        r = room()
        r.alignment = Alignment(1.,2.,90.)
        self.assertAlmostEqual(r.to_world((2.,0.))[0], 1.)
        self.assertAlmostEqual(r.to_world((2.,0.))[1], 0.)
        for p in [(-2.,2.),(0.,0.),(3.,-4.),(8.,3.)]:
            mapped = r.to_world(p)
            back = r.to_local(mapped)
            self.assertAlmostEqual(back[0],p[0])
            self.assertAlmostEqual(back[1],p[1])
        world = r.world_copy()
        self.assertEqual(world.alignment, Alignment())
        self.assertEqual(world.corners[0], r.to_world(r.corners[0]))
        self.assertAlmostEqual(world.boxes[0].cx, 1.)
        self.assertAlmostEqual(world.boxes[0].cz, 2.)
        self.assertAlmostEqual(world.boxes[0].yaw_deg,135.)
        self.assertEqual(r.boxes[0].yaw_deg,45.)
        self.assertEqual(r.floor_y,0.)
        self.assertEqual(world.floor_y,0.)

    def test_frameport_export_and_wall_ids_preserve_originals(self):
        r = room()
        original_lines = to_frameport(r, now=1).splitlines()
        orig_ids = [line.split()[1] for line in original_lines if line.startswith("wall ")]
        r.alignment = Alignment(1.25,-.5,90.)
        transformed = to_frameport(r, now=1).splitlines()
        new_ids = [line.split()[1] for line in transformed if line.startswith("wall ")]
        self.assertEqual(orig_ids,new_ids)
        couch = next(line.split() for line in transformed if line.startswith("volume "))
        self.assertEqual(couch[1], "a"*32)
        self.assertAlmostEqual(float(couch[3]),1.25)
        self.assertAlmostEqual(float(couch[4]),-.5)
        self.assertAlmostEqual(float(couch[6]),135.)
        self.assertAlmostEqual(float(couch[7]),1.8)
        self.assertAlmostEqual(float(couch[8]),.9)
        self.assertEqual(original_lines[5],transformed[5]) # unchanged floor entity
        anchors = walls(r)
        self.assertEqual([item["id"] for item in anchors], orig_ids)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"r.json"
            save(path,r)
            data=snapshot(path,universe=73)
            self.assertEqual(data["space"],"steamvr-standing")
            self.assertAlmostEqual(data["boxes"][0]["cx"],1.25)
            self.assertEqual(data["walls"][0]["id"],orig_ids[0])
        anchor = wall_anchor(r,0,along=.5,height=1.0)
        self.assertEqual(anchor["wall_id"],orig_ids[0])
        self.assertAlmostEqual(anchor["position"][1],1.0)

    def test_alignment_drag_is_preview_only_until_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            original=room()
            s=Session(Editor(original),path=Path(temp)/"room.json",export_dir=None)
            s.handle("ready 73")
            s.handle("origin "+" ".join(map(str,MATRIX)))
            s.handle("align")
            s.handle("place 0 2 0 0 -1 0")
            s.handle("aim 1 2 0.5 0 -1 0")
            s.handle("place_up")
            s.handle("rotate_left")
            self.assertEqual(s.editor.room.alignment,Alignment())
            self.assertAlmostEqual(s.align_preview.dx,1.)
            self.assertAlmostEqual(s.align_preview.dz,.5)
            self.assertAlmostEqual(s.align_preview.yaw_deg,359.)
            self.assertIn("ALIGN",s.display())
            s.handle("confirm")
            self.assertIsNone(s.align_preview)
            self.assertTrue(s.origin_verified)
            self.assertAlmostEqual(s.editor.room.alignment.dx,1.)
            self.assertEqual(s.editor.room.alignment.origin,MATRIX)
            s.handle("save")
            saved=load(Path(temp)/"room.json")
            self.assertEqual(saved.boxes[0].cx,0.)
            self.assertEqual(saved.corners,room().corners)
            self.assertAlmostEqual(saved.alignment.dx,1.)
            s.handle("undo")
            self.assertEqual(s.editor.room.alignment,Alignment())

    def test_cancel_rolls_back_preview_and_hit_detection_uses_inverse(self):
        r=room()
        r.alignment=Alignment(1.,.5,30.)
        s=Session(Editor(r),path=Path("/unused"),export_dir=None)
        s.handle("ready 73")
        s.handle("aim 1 2 0.5 0 -1 0")
        self.assertAlmostEqual(s.aim[0],0.)
        self.assertAlmostEqual(s.aim[1],0.)
        s.handle("confirm")
        self.assertEqual(s.selected_id,r.boxes[0].id)
        s.handle("align")
        s.handle("place 0 2 0 0 -1 0")
        s.handle("aim 2 2 0 0 -1 0")
        s.handle("undo")
        self.assertIsNone(s.align_preview)
        self.assertEqual(r.alignment,Alignment(1.,.5,30.))
        s.handle("align")
        s.handle("rotate")
        s.handle("align") # also cancels
        self.assertEqual(r.alignment,Alignment(1.,.5,30.))

    def test_origin_calibration_change_marks_room_unverified_without_vertical_shift(self):
        r=room()
        r.alignment.origin=MATRIX
        s=Session(Editor(r),path=Path("/unused"),export_dir=None)
        s.handle("ready 73")
        s.handle("origin "+" ".join(map(str,MATRIX)))
        self.assertTrue(s.origin_verified)
        changed=list(MATRIX)
        changed[7]=0.15 # tracking origin floor recalibration
        s.handle("origin "+" ".join(map(str,changed)))
        self.assertFalse(s.origin_verified)
        self.assertAlmostEqual(s.editor.room.floor_y,0.)
        self.assertIn("UNVERIFIED",s.display())
        s.handle("align")
        s.handle("confirm")
        self.assertEqual(r.alignment.origin,tuple(changed))
        self.assertTrue(s.origin_verified)

    def test_reject_invalid_alignment_without_mutating_local_geometry(self):
        r=room()
        with self.assertRaises(ValueError):
            r.alignment = Alignment(100.,0.,0.)
            r.validate()
        r.alignment=Alignment()
        editor=Editor(r)
        with self.assertRaisesRegex(ValueError,"25"):
            editor.dispatch({"action":"set_alignment","dx":26.,"dz":0.,"yaw_deg":0.})
        self.assertEqual(r.alignment,Alignment())


if __name__ == "__main__":
    unittest.main()
