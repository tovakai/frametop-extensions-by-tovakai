"""Read-only API for extensions that use a saved spatial room.

Import from the plugin folder or load as a Python file. No background process,
Frametop socket, SteamVR or FramePort runtime dependency. Never assume room
coordinates are aligned without checking the active SteamVR universe.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

from room_model import Room, _edge_key, _uuid_for, load, signed_area

DEFAULT_ROOM = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / \
    "frametop-extensions" / "spatial-room" / "room.json"


def snapshot(path: Path = DEFAULT_ROOM, *, universe: int,
             standing_origin: tuple[float, ...] | None = None) -> dict:
    """Return immutable-by-convention JSON-like snapshot if tracking universe matches.

    A matching universe ID is necessary, but *not sufficient*, to guarantee
    physical alignment after recentering or relocalization.
    """
    room = load(path)
    if type(universe) is not int or universe == 0 or room.universe == 0:
        raise ValueError("a known, current SteamVR tracking universe is required")
    if room.universe != universe:
        raise ValueError(f"tracking universe mismatch: saved={room.universe}, active={universe}")
    if not room.closed:
        raise ValueError("room outline is unfinished")
    data = room.world_copy().to_dict()
    # Consumers receive effective STANDING-space geometry and stable wall IDs.
    data["local_alignment"] = room.alignment.to_dict()
    data["space"] = "steamvr-standing"
    data["walls"] = walls(room)
    saved = room.alignment.origin
    # Do not claim physical registration based only on a tracking universe ID.
    # Consumers that can read OpenVR may supply the current raw->standing pose.
    valid_origin = (standing_origin is not None and isinstance(standing_origin, (tuple, list))
                    and len(standing_origin) == 12
                    and all(type(v) in (float, int) and math.isfinite(v) for v in standing_origin))
    data["alignment_verified"] = bool(saved is not None and valid_origin and
        all(abs(a-b) <= 0.003 for a,b in zip(saved,standing_origin)))
    return data


def walls(room: Room) -> list[dict]:
    """Describe physical walls and their inward normals for spatial attachments."""
    room.validate()
    if not room.closed:
        raise ValueError("room outline is unfinished")
    corners = list(room.corners)
    if signed_area(corners) < 0:
        corners.reverse()
    result = []
    for index, (a, b) in enumerate(zip(corners, corners[1:] + corners[:1])):
        # Generate IDs from the immutable room-local edge even when realigning.
        edge_id = _uuid_for(room.id, _edge_key(a, b))
        a, b = room.to_world(a), room.to_world(b)
        dx, dz = b[0]-a[0], b[1]-a[1]
        width = math.hypot(dx, dz)
        # Contract: FramePort's positive outline ordering uses inward (-dz,dx).
        normal = (-dz/width, 0.0, dx/width)
        result.append({
            "id": edge_id,
            "index": index, "start": [a[0], room.floor_y, a[1]],
            "end": [b[0], room.floor_y, b[1]],
            "normal": list(normal),
            "width": width, "height": room.ceiling_y-room.floor_y
        })
    return result


def wall_anchor(room: Room, index: int, *, along: float = 0.5, height: float = 1.5,
                inset: float = 0.025) -> dict:
    """Place an item on a wall, facing inwards. Height is metres above the floor."""
    if type(index) is not int:
        raise ValueError("wall index must be an integer")
    if not all(type(v) in (float, int) and math.isfinite(v) for v in (along, height, inset)):
        raise ValueError("wall anchor coordinates must be finite")
    items = walls(room)
    if not 0 <= index < len(items):
        raise ValueError("wall index out of range")
    wall = items[index]
    if not 0 <= along <= 1 or not 0 <= height <= wall["height"] or not 0 <= inset <= 1:
        raise ValueError("wall attachment must stay within bounds")
    start, end, normal = wall["start"], wall["end"], wall["normal"]
    return {
        "wall_id": wall["id"],
        "position": [
            start[0]+(end[0]-start[0])*along+normal[0]*inset,
            room.floor_y+height,
            start[2]+(end[2]-start[2])*along+normal[2]*inset
        ],
        "normal": list(normal),
        "right": [(end[0]-start[0])/wall["width"], 0.0,
                  (end[2]-start[2])/wall["width"]],
        "up": [0.0, 1.0, 0.0]
    }
