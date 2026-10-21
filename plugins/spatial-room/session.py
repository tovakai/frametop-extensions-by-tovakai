#!/usr/bin/env python3
"""Steam Frame manual room editing session.

Python owns model, save and export. Native OpenVR frontend owns only temporary
overlays/controller input. Neither module edits Frametop/SteamVR configuration.
"""
from __future__ import annotations

import argparse
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
from room_model import Room, load, save, to_frameport

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


def hud(editor: Editor, mode: str, label: str, height: float, yaw: float, error="") -> str:
    if error:
        return ("ERROR " + error.upper())[:56]
    room = editor.room
    if not room.closed:
        return f"WALLS {len(room.corners)} CORNERS  A TO CLOSE  X SAVE"
    if mode == "erase":
        return "ERASE MODE  TRIGGER BOX TO DELETE  GRIP ADD"
    if mode == "box":
        pending = " SECOND CORNER" if editor.pending else ""
        return f"BOX {label} {height:.2f}M {int(yaw)} DEG{pending}"
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
    clean = "".join(ch for ch in header.upper() if ch.isalnum() or ch in " :-./?")
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


class Session:
    def __init__(self, editor: Editor, *, path: Path, export_dir: Path | None):
        self.editor = editor
        self.path = path
        self.export_dir = export_dir
        self.mode = "walls" if not editor.room.closed else "box"
        self.label = "TABLE"
        self.height = 0.75
        self.yaw = 0.0
        self.aim = None
        self.error = ""
        self.last_render = ""
        self.universe_known = False  # wait for the current headset universe on every launch

    def handle_ready(self, universe: int) -> None:
        if not 0 <= universe < 2**64:
            raise ValueError("SteamVR returned invalid tracking universe")
        room = self.editor.room
        if not universe:
            raise ValueError("SteamVR tracking universe is unknown: refusing to place physical geometry")
        if room.universe not in (0, universe):
            raise ValueError(f"saved room universe {room.universe} != current SteamVR universe {universe}; "
                             "do not apply geometry with the wrong alignment")
        if room.universe == 0:
            room.universe = universe
        self.universe_known = True

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
        if cmd in ("aim", "place"):
            if len(parts) != 7:
                raise ValueError("malformed controller ray")
            numbers = [float(v) for v in parts[1:]]
            evt = {"origin": numbers[:3], "direction": numbers[3:]}
            if cmd == "aim":
                try:
                    self.aim = floor_hit(**evt, floor_y=self.editor.room.floor_y)
                except ValueError:
                    self.aim = None
                return
            if self.mode == "erase":
                hit = floor_hit(**evt, floor_y=self.editor.room.floor_y)
                ident = box_at_point(self.editor.room, hit)
                if ident is None:
                    raise ValueError("point inside a furniture box to erase it")
                self.editor.dispatch({"action": "delete_box", "id": ident})
                self.aim = None
                return
            action = ("corner" if self.mode == "walls" else
                      "box_finish" if self.editor.pending else "box_start")
            evt["action"] = action
            if action == "box_finish":
                evt.update(label=self.label, height=self.height, yaw_deg=self.yaw)
            self.editor.dispatch(evt)
            self.aim = None
        elif cmd == "mode":
            if self.editor.room.closed:
                if self.editor.pending is not None:
                    raise ValueError("finish or cancel the current box before switching tools")
                self.mode = "erase" if self.mode == "box" else "box"
            else:
                self.mode = "walls"
        elif cmd == "confirm":
            if not self.editor.room.closed:
                self.editor.dispatch({"action": "close"})
                self.mode = "box"
            elif self.editor.pending is not None:
                # Keep in place, trigger makes the actual second corner.
                self.editor.dispatch({"action": "undo"})
        elif cmd == "undo":
            self.editor.dispatch({"action": "undo"})
        elif cmd == "label":
            self.label = LABELS[(LABELS.index(self.label)+1) % len(LABELS)]
        elif cmd == "height":
            self.height = HEIGHTS[(HEIGHTS.index(self.height)+1) % len(HEIGHTS)]
        elif cmd == "rotate":
            self.yaw = (self.yaw + 15) % 180
        elif cmd == "save":
            save(self.path, self.editor.room)
            print(f"Saved room: {self.path}", file=sys.stderr)
            if self.export_dir is not None:
                if self.editor.room.closed:
                    file = frameport_snapshot(self.export_dir, self.editor.room)
                    print(f"FramePort export staged: {file}", file=sys.stderr)
                else:
                    print("Outline unfinished: JSON saved; FramePort export skipped", file=sys.stderr)
        else:
            raise ValueError(f"unexpected native event: {cmd}")

    def display(self) -> str:
        header = hud(self.editor, self.mode, self.label, self.height, self.yaw, self.error)
        selection = box_at_point(self.editor.room, self.aim) if self.aim is not None and self.mode == "erase" else None
        geom = segments_for_room(self.editor.room, pending=self.editor.pending if self.mode == "box" else None,
                                 aiming=self.aim, height=self.height, yaw=self.yaw,
                                 selection_id=selection)
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
    parser.add_argument("--input-debug", action="store_true",
                        help="print decoded controller presses to stderr for testing")
    args = parser.parse_args(argv)
    try:
        room = load(args.file) if args.file.exists() else Room(name=args.name, universe=0)
        session = Session(Editor(room), path=args.file, export_dir=args.export_frameport)
        return run(args.native, ROOT/"native/actions/room_actions.json", session,
                   input_mode=args.input_mode, input_debug=args.input_debug)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Spatial Room: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
