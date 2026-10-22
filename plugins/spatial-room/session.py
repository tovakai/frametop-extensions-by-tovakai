#!/usr/bin/env python3
"""Steam Frame manual room editing session.

Python owns model, save and export. Native OpenVR frontend owns only temporary
overlays/controller input. Neither module edits Frametop/SteamVR configuration.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from vr_input import watch

from editor import Editor, box_between, floor_hit
from room_model import Alignment, Room, load, save, to_frameport

LABELS = ("TABLE", "COUCH", "BED", "STORAGE", "SCREEN", "LAMP", "PLANT", "OTHER")
HEIGHTS = (0.45, 0.75, 1.1, 1.8, 2.3)
MAX_SEGMENTS = 240
ROOT = Path(__file__).resolve().parent
DEFAULT_ROOM = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / \
    "frametop-extensions" / "spatial-room" / "room.json"


def segments_for_room(room: Room, pending=None, aiming=None, height=0.75, yaw=0.0, selection_id=None):
    """World-space edges (a,b,palette). Same -Z and yaw convention as FramePort."""
    result = []
    cs = room.corners
    n = len(cs)
    edges = list(zip(cs, cs[1:]))
    if room.closed:
        edges.append((cs[-1], cs[0]))
    for a, b in edges:
        for yy in (room.floor_y, room.ceiling_y):
            result.append(((a[0], yy, a[1]), (b[0], yy, b[1]), 0))
    for p in cs:
        result.append(((p[0], room.floor_y, p[1]), (p[0], room.ceiling_y, p[1]), 0))
    for obj in room.boxes:
        result.extend(box_edges(obj.cx, obj.cz, obj.top_y, obj.w, obj.d, obj.h, obj.yaw_deg,
                                3 if obj.id == selection_id else 1))
    if pending is not None and aiming is not None:
        try:
            preview = box_between(pending, aiming, "OTHER", height, room.floor_y, yaw)
            result.extend(box_edges(preview.cx, preview.cz, preview.top_y,
                                    preview.w, preview.d, preview.h, preview.yaw_deg, 2))
        except ValueError:
            pass
    if aiming is not None:
        x, z = aiming
        y = room.floor_y + 0.01
        result.extend([((x-0.08, y, z), (x+0.08, y, z), 2),
                       ((x, y, z-0.08), (x, y, z+0.08), 2)])
    return result[:MAX_SEGMENTS]


def box_edges(cx, cz, top_y, w, d, h, yaw, palette):
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    def corner(i, j, yy):
        x, z = i*w/2, j*d/2
        return (cx+c*x+s*z, yy, cz-s*x+c*z)
    points = [(corner(i, j, top_y-h), corner(i, j, top_y))
              for i, j in ((-1,-1), (1,-1), (1,1), (-1,1))]
    out = [(a, b, palette) for a, b in points]
    for level in (0, 1):
        ring = [p[level] for p in points]
        out.extend((a, b, palette) for a, b in zip(ring, ring[1:]+ring[:1]))
    return out



def box_at_point(room: Room, point: tuple[float, float], tolerance: float = 0.10) -> str | None:
    """Hit-test yawed furniture footprints. Returns topmost (latest) suitable box."""
    x, z = point
    for box in reversed(room.boxes):
        c, s = math.cos(math.radians(box.yaw_deg)), math.sin(math.radians(box.yaw_deg))
        dx, dz = x - box.cx, z - box.cz
        local_x, local_z = c*dx - s*dz, s*dx + c*dz
        if abs(local_x) <= box.w/2 + tolerance and abs(local_z) <= box.d/2 + tolerance:
            return box.id
    return None


def hud(editor: Editor, mode: str, label: str, height: float, yaw: float, error="", selected_id=None) -> str:
    if error:
        return ("ERROR " + error.upper())[:56]
    room = editor.room
    if not room.closed:
        return f"WALLS {len(room.corners)} CORNERS  A TO CLOSE  X SAVE"
    if selected_id:
        box = next((b for b in room.boxes if b.id == selected_id), None)
        if box is not None:
            return f"EDIT {box.label} H {box.h:.2f}M YAW {box.yaw_deg:.0f}  UP/DN 1CM"
    if mode == "erase":
        return "ERASE MODE  TRIGGER DELETE  GRIP ADD"
    if mode == "box":
        pending = " SECOND CORNER" if editor.pending else ""
        return f"BOX {label} {height:.2f}M {yaw:.0f} DEG{pending}"
    return f"WALLS {len(room.corners)}  GRIP FOR BOX MODE"


def render_commands(lines, header: str) -> str:
    """Only numeric geometry and safe one-line HUD strings cross into native."""
    chunks = ["clear\n"]
    for a, b, palette in lines:
        if not all(math.isfinite(v) and abs(v) <= 100 for v in (*a, *b)):
            raise ValueError("geometry escaped working area")
        chunks.append("segment " + " ".join(format(v, ".6f") for v in (*a, *b)) +
                      f" {palette}\n")
    chunks.append("commit\n")
    clean = "".join(ch for ch in header.upper() if ch.isalnum() or ch in " :+-./?")
    chunks.append("hud " + clean[:56] + "\n")
    return "".join(chunks)


def frameport_snapshot(folder: Path, room: Room) -> Path:
    """Explicit staging export, not a write to FramePort's live room directory."""
    folder.mkdir(parents=True, exist_ok=True)
    text = to_frameport(room)
    for n in range(1000):
        name = f"room-{room.id[:8]}-{int(time.time())}-{n:03}.txt"
        path = folder / name
        try:
            with path.open("x", encoding="utf-8") as file:
                os.fchmod(file.fileno(), 0o600)
                file.write(text)
                file.flush()
                os.fsync(file.fileno())
            return path
        except FileExistsError:
            continue
    raise RuntimeError("couldn't choose a unique export filename")


def backup_old_universe(path: Path, universe: int) -> Path:
    """Create a lossless owner-only backup before replacing the old room file.

    This only runs after the user explicitly confirms a cross-universe recovery,
    then explicitly presses Save. Never overwrite an existing backup.
    """
    path = Path(path)
    data = path.read_bytes()
    if len(data) > 1024 * 1024:
        raise ValueError("saved room is too large to back up")
    for index in range(1000):
        suffix = f".universe-{universe}" + (f"-{index:03d}" if index else "") + ".bak"
        backup = path.with_name(path.name + suffix)
        try:
            with backup.open("xb") as file:
                os.fchmod(file.fileno(), 0o600)
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            print(f"Spatial Room: original-universe backup: {backup}", file=sys.stderr)
            return backup
        except FileExistsError:
            # A fresh backup for every explicitly accepted recovery.
            continue
    raise RuntimeError("couldn't create a unique original-universe backup")


class Session:
    def __init__(self, editor: Editor, *, path: Path, export_dir: Path | None,
                 recover_universe: bool = False):
        self.editor = editor
        self.path = path
        self.export_dir = export_dir
        self.mode = "walls" if not editor.room.closed else "box"
        self.label = "TABLE"
        self.height = 0.75
        self.yaw = 0.0
        self.selected_id: str | None = None
        self.aim = None  # current room-local pointer coordinate
        self.aim_world = None  # standing-space pointer coordinate
        self.align_preview: Alignment | None = None
        self.align_drag = None  # pointer start and starting dx,dz
        self.current_origin: tuple[float, ...] | None = None
        self.origin_verified = False
        self.error = ""
        self.last_render = ""
        self.universe_known = False  # wait for the current headset universe on every launch
        self.recover_universe = recover_universe
        self.recovery_pending = False
        self.recovery_confirmed = False
        self.original_universe = editor.room.universe
        self.active_universe: int | None = None

    def handle_ready(self, universe: int) -> None:
        if not 0 < universe < 2**64:
            raise ValueError("SteamVR tracking universe is unknown or invalid")
        # The native process exits if the universe changes while running.
        # Always reject a mid-session change even when recovery is enabled.
        if self.active_universe is not None and universe != self.active_universe:
            raise ValueError("SteamVR universe changed during editing; exit and recover explicitly")
        room = self.editor.room
        if room.universe not in (0, universe):
            if not self.recover_universe or not room.closed:
                raise ValueError(f"saved room universe {room.universe} != current SteamVR universe {universe}; "
                                 "launch with --recover-universe to realign explicitly")
            self.recovery_pending = True
            self.origin_verified = False
            print(f"Spatial Room: recovery requested; saved universe {room.universe}, "
                  f"current {universe}. Geometry hidden until left-trigger preview. "
                  "Nothing will be rewritten before alignment confirmation and Save.",
                  file=sys.stderr)
        elif room.universe == 0:
            room.universe = universe
        self.active_universe = universe
        self.universe_known = True

    def _effective_room(self) -> Room:
        if self.align_preview is None:
            return self.editor.room
        room = copy.copy(self.editor.room)
        room.alignment = self.align_preview
        return room

    def _aligning(self) -> bool:
        return self.align_preview is not None

    def handle(self, line: str) -> None:
        """Process one event from the native client, raising only for invalid commands."""
        parts = line.split()
        if not parts:
            return
        cmd = parts[0]
        if cmd in ("ready", "universe"):
            if len(parts) != 2:
                raise ValueError("malformed tracking universe event")
            self.handle_ready(int(parts[1]))
            return
        if not self.universe_known:
            raise ValueError("editing disabled until headset tracking universe is verified")
        if cmd == "origin":
            if len(parts) != 13:
                raise ValueError("expected a 3x4 tracking origin matrix")
            current = tuple(float(v) for v in parts[1:])
            if any(not math.isfinite(v) or abs(v) > 10000 for v in current):
                raise ValueError("invalid tracking origin pose")
            if self.current_origin is not None and any(
                abs(a-b) > 0.003 for a,b in zip(self.current_origin,current)
            ):
                # An origin change invalidates uncommitted alignment drags.
                self.align_preview = None
                self.align_drag = None
                print("Spatial Room: standing origin changed; please realign before trusting outlines",
                      file=sys.stderr)
            self.current_origin = current
            saved = self.editor.room.alignment.origin
            self.origin_verified = saved is not None and all(
                abs(a-b) <= 0.003 for a,b in zip(saved,current))
            return
        if self.recovery_pending and cmd not in (
            "origin", "align", "aim", "place", "place_up",
            "height_up", "height_down", "rotate", "rotate_left",
            "rotate_right", "confirm", "undo"
        ):
            raise ValueError("recovering room: only alignment controls are allowed")
        if self.recovery_pending and self.align_preview is None and cmd not in ("origin","align"):
            raise ValueError("press left trigger to preview old room before recovery")
        if cmd == "align":
            if not self.editor.room.closed:
                raise ValueError("close the room outline before alignment")
            if self._aligning():
                # Exiting without pressing A discards all preview changes.
                self.align_preview = None
                self.align_drag = None
            else:
                if self.editor.pending is not None:
                    raise ValueError("finish the pending furniture box first")
                self.align_preview = copy.deepcopy(self.editor.room.alignment)
                self.align_drag = None
                self.selected_id = None
            return
        if cmd == "place_up":
            self.align_drag = None
            return
        if cmd in ("aim", "place"):
            if len(parts) != 7:
                raise ValueError("malformed controller ray")
            numbers = [float(v) for v in parts[1:]]
            raw_ray = {"origin": numbers[:3], "direction": numbers[3:]}
            if cmd == "aim":
                try:
                    self.aim_world = floor_hit(**raw_ray, floor_y=self.editor.room.floor_y)
                    if self._aligning() and self.align_drag is not None:
                        start_x, start_z, dx, dz = self.align_drag
                        self.align_preview.dx = max(-25.0, min(25.0, dx + self.aim_world[0]-start_x))
                        self.align_preview.dz = max(-25.0, min(25.0, dz + self.aim_world[1]-start_z))
                    self.aim = self._effective_room().to_local(self.aim_world)
                except ValueError:
                    self.aim = None
                    self.aim_world = None
                return
            world_hit = floor_hit(**raw_ray, floor_y=self.editor.room.floor_y)
            self.aim_world = world_hit
            if self._aligning():
                self.align_drag = (world_hit[0],world_hit[1],
                                   self.align_preview.dx,self.align_preview.dz)
                return
            local_hit = self.editor.room.to_local(world_hit)
            # The headless editor accepts rays; feed it a safe synthetic
            # downward ray representing the correctly inverse-transformed hit.
            evt = {"origin": [local_hit[0],self.editor.room.floor_y+1,local_hit[1]],
                   "direction":[0,-1,0]}
            if self.mode == "erase":
                ident = box_at_point(self.editor.room, local_hit)
                if ident is None:
                    raise ValueError("point inside a furniture box to erase it")
                self.editor.dispatch({"action": "delete_box", "id": ident})
                if self.selected_id == ident:
                    self.selected_id = None
                self.aim = None
                return
            action = ("corner" if self.mode == "walls" else
                      "box_finish" if self.editor.pending else "box_start")
            evt["action"] = action
            self.selected_id = None
            if action == "box_finish":
                evt.update(label=self.label, height=self.height, yaw_deg=self.yaw)
            self.editor.dispatch(evt)
            self.aim = None
            self.aim_world = None
        elif cmd == "mode":
            if self._aligning():
                return
            if self.editor.room.closed:
                if self.editor.pending is not None:
                    raise ValueError("finish or cancel the current box before switching tools")
                self.mode = "erase" if self.mode == "box" else "box"
                self.selected_id = None
            else:
                self.mode = "walls"
        elif cmd == "confirm":
            if self._aligning():
                if self.current_origin is None:
                    raise ValueError("cannot confirm alignment until SteamVR reports standing origin")
                candidate = self.align_preview
                action = "recover_universe" if self.recovery_pending else "set_alignment"
                event = {"action": action, "dx": candidate.dx,
                         "dz": candidate.dz, "yaw_deg": candidate.yaw_deg,
                         "origin": self.current_origin}
                if self.recovery_pending:
                    event["universe"] = self.active_universe
                self.editor.dispatch(event)
                if self.recovery_pending:
                    print(f"Spatial Room: manually aligned room now targets universe "
                          f"{self.active_universe}; right X saves, no file changed yet.",
                          file=sys.stderr)
                    self.recovery_pending = False
                    self.recovery_confirmed = True
                self.origin_verified = True
                self.align_preview = None
                self.align_drag = None
                self.aim = None
                self.aim_world = None
                return
            if not self.editor.room.closed:
                self.editor.dispatch({"action": "close"})
                self.mode = "box"
            elif self.editor.pending is not None:
                # Keep in place, trigger makes the actual second corner.
                self.editor.dispatch({"action": "undo"})
            elif self.mode == "box":
                # A selects the existing furniture under the cross-marker, or
                # deselects when pointing at empty floor.
                hit = box_at_point(self.editor.room, self.aim) if self.aim is not None else None
                self.selected_id = None if hit == self.selected_id else hit
        elif cmd == "undo":
            if self._aligning():
                self.align_preview = None
                self.align_drag = None
                return
            self.editor.dispatch({"action": "undo"})
            if (self.active_universe is not None and
                    self.editor.room.universe != self.active_universe):
                self.recovery_pending = True
                self.recovery_confirmed = False
                self.origin_verified = False
                self.selected_id = None
                return
            saved = self.editor.room.alignment.origin
            self.origin_verified = (self.current_origin is not None and saved is not None
                                    and all(abs(a-b) <= 0.003 for a,b in zip(saved,self.current_origin)))
            if not any(b.id == self.selected_id for b in self.editor.room.boxes):
                self.selected_id = None
        elif cmd == "label":
            if self._aligning():
                return
            box = next((b for b in self.editor.room.boxes if b.id == self.selected_id), None)
            if box is not None:
                label = LABELS[(LABELS.index(box.label)+1) % len(LABELS)]
                self.editor.dispatch({"action": "set_box_label", "id": box.id, "label": label})
            else:
                self.label = LABELS[(LABELS.index(self.label)+1) % len(LABELS)]
        elif cmd in ("height", "height_up", "height_down"):
            if self._aligning():
                # In alignment mode the D-pad moves the *whole room* in Z, not
                # furniture height. Floor Y is always SteamVR's standing floor.
                if cmd == "height":
                    return
                direction = -1 if cmd == "height_up" else 1
                self.align_preview.dz = max(-25.0, min(25.0,
                    round(self.align_preview.dz + direction*0.01, 2)))
                return
            # Right Y: advance to the next coarse preset. Left D-pad up/down:
            # nudge 1 cm. Selected furniture updates immediately; otherwise
            # the setting applies to the next placed box.
            box = next((b for b in self.editor.room.boxes if b.id == self.selected_id), None)
            current = box.h if box is not None else self.height
            if cmd == "height":
                next_height = next((h for h in HEIGHTS if h > current + 1e-8), HEIGHTS[0])
            else:
                step = 0.01 if cmd == "height_up" else -0.01
                next_height = round(current + step, 2)
            if not 0.05 <= next_height <= 10:
                raise ValueError("furniture height must stay between 5 cm and 10 m")
            if box is not None:
                self.editor.dispatch({"action": "resize_box", "id": box.id, "height": next_height})
            else:
                if next_height > self.editor.room.ceiling_y - self.editor.room.floor_y + 1e-9:
                    raise ValueError("furniture height exceeds room ceiling")
                self.height = next_height
        elif cmd in ("rotate", "rotate_left", "rotate_right"):
            # Thumbstick click: +5 degrees. Left D-pad: -1 / +1 degrees.
            delta = {"rotate": 5, "rotate_left": -1, "rotate_right": 1}[cmd]
            if self._aligning():
                self.align_preview.yaw_deg = (self.align_preview.yaw_deg + delta) % 360
                return
            if self.selected_id is not None:
                self.editor.dispatch({"action": "rotate_box", "id": self.selected_id, "delta_deg": delta})
            else:
                self.yaw = (self.yaw + delta) % 360
        elif cmd == "save":
            if self.recovery_pending:
                raise ValueError("cannot save old-universe room until recovery is confirmed")
            if self._aligning():
                raise ValueError("press A to accept alignment or B to cancel before saving")
            if self.recovery_confirmed and self.original_universe != self.editor.room.universe:
                backup_old_universe(self.path, self.original_universe)
            save(self.path, self.editor.room)
            self.recovery_confirmed = False  # Back up the original only once.
            print(f"Saved room: {self.path}", file=sys.stderr)
            if self.export_dir is not None:
                if self.current_origin is not None and not self.origin_verified:
                    print("Alignment unverified: JSON saved; FramePort export skipped until "
                          "Align Room is confirmed with right A", file=sys.stderr)
                elif self.editor.room.closed:
                    file = frameport_snapshot(self.export_dir, self.editor.room)
                    print(f"FramePort export staged: {file}", file=sys.stderr)
                else:
                    print("Outline unfinished: JSON saved; FramePort export skipped", file=sys.stderr)
        else:
            raise ValueError(f"unexpected native event: {cmd}")

    def display(self) -> str:
        room = self._effective_room()
        header = hud(self.editor, self.mode, self.label, self.height, self.yaw, self.error,
                     selected_id=self.selected_id)
        if self._aligning():
            a = self.align_preview
            prefix = "RECOVER" if self.recovery_pending else "ALIGN"
            header = f"{prefix} X {a.dx:+.2f} Z {a.dz:+.2f} YAW {a.yaw_deg:.0f} A OK B CANCEL"
        elif self.recovery_pending:
            header = "UNIVERSE MISMATCH  LEFT TRIGGER TO PREVIEW"
        elif self.current_origin is not None and not self.origin_verified:
            header = "ALIGNMENT UNVERIFIED  L TRIGGER ALIGN  A CONFIRM"
        selection = self.selected_id
        if selection is None and self.aim is not None and self.mode == "erase":
            selection = box_at_point(self.editor.room, self.aim)
        world = room.world_copy()
        pending = room.to_world(self.editor.pending) if self.editor.pending is not None and self.mode=="box" else None
        # Before opt-in preview the old universe's geometry is not projected.
        if self.recovery_pending and not self._aligning():
            return render_commands([], header)
        geom = segments_for_room(world, pending=pending, aiming=self.aim_world,
                                 height=self.height, yaw=self.yaw+room.alignment.yaw_deg,
                                 selection_id=selection)
        if self.recovery_pending:
            # Render the entire untrusted assembly in the warning palette.
            geom = [(a,b,3) for a,b,_ in geom]
        return render_commands(geom, header)


def run(native: Path, actions: Path, session: Session, *,
        input_mode: str = "readonly", input_debug: bool = False) -> int:
    if not native.is_file():
        raise RuntimeError(f"native frontend missing: {native}; build it first")
    if not actions.is_file():
        raise RuntimeError(f"SteamVR action manifest missing: {actions}")
    native, actions = native.resolve(), actions.resolve()
    command = [str(native), "--read-only-input" if input_mode == "readonly" else str(actions)]
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          text=True, bufsize=1) as process:
        hard_failure = False
        writer_lock = threading.Lock()
        stop_input = threading.Event()
        watcher = None

        def send_native(payload: str) -> bool:
            with writer_lock:
                if process.poll() is not None or not process.stdin:
                    return False
                try:
                    process.stdin.write(payload)
                    process.stdin.flush()
                    return True
                except (BrokenPipeError, OSError, ValueError):
                    return False

        if input_mode == "readonly":
            watcher = threading.Thread(
                target=watch,
                args=(stop_input, lambda action: send_native(f"input {action}\n"),
                      lambda message: print("Spatial Room input:", message, file=sys.stderr)),
                kwargs={"debug": input_debug}, name="spatial-room-input", daemon=True)
            watcher.start()
        try:
            for line in process.stdout:
                try:
                    session.handle(line.strip())
                    session.error = ""
                except (ValueError, TypeError, OSError) as exc:
                    session.error = str(exc)
                    print("Spatial Room:", exc, file=sys.stderr)
                    if line.startswith(("ready", "universe")):
                        # Universe mismatch is a hard stop, never render old room.
                        hard_failure = True
                        break
                frame = session.display()
                if frame != session.last_render:
                    if not send_native(frame):
                        break
                    session.last_render = frame
        except KeyboardInterrupt:
            print("\nSpatial Room interrupted; unsaved edits are not written.", file=sys.stderr)
        finally:
            stop_input.set()
            if process.poll() is None:
                send_native("quit\n")
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            if watcher is not None:
                watcher.join(timeout=1.0)
    return 1 if hard_failure or process.returncode not in (0, None) else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Edit a spatial room inside Steam Frame")
    parser.add_argument("--file", type=Path, default=DEFAULT_ROOM)
    parser.add_argument("--name", default="Living Room", help="name for new room")
    parser.add_argument("--native", type=Path, default=ROOT/"native/build/ft-room-vr")
    parser.add_argument("--export-frameport", type=Path,
                        help="stage room.txt snapshots here on Save; NEVER installs them to FramePort")
    parser.add_argument("--input-mode", choices=("readonly", "global"), default="readonly",
                        help="controller source; readonly (default) requires no SteamVR global bindings")
    parser.add_argument("--recover-universe", action="store_true",
                        help="explicitly preview and manually realign an older tracking universe; "
                             "requires left-trigger preview, right-A confirmation and right-X save")
    parser.add_argument("--input-debug", action="store_true",
                        help="print decoded controller presses to stderr for testing")
    args = parser.parse_args(argv)
    try:
        if args.recover_universe and not args.file.is_file():
            raise ValueError("--recover-universe requires an existing saved room JSON")
        room = load(args.file) if args.file.exists() else Room(name=args.name, universe=0)
        session = Session(Editor(room), path=args.file, export_dir=args.export_frameport,
                          recover_universe=args.recover_universe)
        return run(args.native, ROOT/"native/actions/room_actions.json", session,
                   input_mode=args.input_mode, input_debug=args.input_debug)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Spatial Room: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
