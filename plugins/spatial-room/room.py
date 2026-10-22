#!/usr/bin/env python3
"""Prototype spatial-room CLI and JSON-lines editor protocol (VR adapter planned)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from editor import Editor
from room_model import Room, load, save, to_frameport


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Frametop manual room layout prototype")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="create an empty draft")
    new.add_argument("file", type=Path)
    new.add_argument("--name", required=True)
    new.add_argument("--universe", required=True, type=int,
                     help="SteamVR standing universe ID (0 marks alignment unknown)")
    new.add_argument("--ceiling", type=float, default=2.5)
    edit = sub.add_parser("edit", help="process JSON event lines on stdin")
    edit.add_argument("file", type=Path)
    check = sub.add_parser("check", help="validate a draft")
    check.add_argument("file", type=Path)
    export = sub.add_parser("export", help="export FramePort room.txt without installing it")
    export.add_argument("file", type=Path)
    export.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "new":
            room = Room(name=args.name, universe=args.universe, ceiling_y=args.ceiling)
            save(args.file, room, replace=False)
            print(f"Created draft {args.file}")
        elif args.command == "check":
            room = load(args.file)
            print(json.dumps({"name": room.name, "corners": len(room.corners),
                              "closed": room.closed, "boxes": len(room.boxes),
                              "universe": room.universe}))
        elif args.command == "export":
            room = load(args.file)
            text = to_frameport(room)
            if args.output.exists():
                raise FileExistsError(f"{args.output} already exists; refusing to overwrite")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive create, not a silent overwrite of a FramePort room.
            with args.output.open("x", encoding="utf-8") as out:
                out.write(text)
            if room.universe == 0:
                print("WARNING: SteamVR tracking universe is unknown; room may not align", file=sys.stderr)
            print(f"Exported {args.output}")
        elif args.command == "edit":
            editor = Editor(load(args.file))
            for line in sys.stdin:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError("event must be a JSON object")
                    if event.get("action") == "save":
                        save(args.file, editor.room)
                        result = {"saved": str(args.file)}
                    else:
                        result = editor.dispatch(event)
                    print(json.dumps({"ok": True, **result}), flush=True)
                except (ValueError, TypeError, OSError, KeyError) as exc:
                    print(json.dumps({"ok": False, "error": str(exc)}), flush=True)
    except (ValueError, TypeError, OSError) as exc:
        print(f"room: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
