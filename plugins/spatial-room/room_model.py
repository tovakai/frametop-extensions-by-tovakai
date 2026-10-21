"""Portable, dependency-free room model for the Frametop spatial-room extension.

Coordinates: SteamVR Standing/STAGE, right-handed, +Y up, -Z forward, metres.
The editable JSON format is ours; FramePort's room.txt is an explicit export.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

FORMAT = "frametop-spatial-room"
FORMAT_VERSION = 1
UUID_RE = re.compile(r"^[0-9a-f]{32}$")
LABELS = frozenset({"TABLE", "COUCH", "BED", "STORAGE", "SCREEN", "LAMP", "PLANT", "OTHER"})
MAX_CORNERS = 64
MAX_VOLUMES = 256
MAX_FILE_SIZE = 1024 * 1024


def finite(value: object, name: str) -> float:
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def length(value: object, name: str, low: float = 0.001, high: float = 100) -> float:
    v = finite(value, name)
    if not low <= v <= high:
        raise ValueError(f"{name} must be between {low} and {high} metres")
    return v


def point_xz(value: object) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("point must be [x, z]")
    x, z = (finite(value[0], "x"), finite(value[1], "z"))
    if abs(x) > 100 or abs(z) > 100:
        raise ValueError("point lies outside the 100 metre working area")
    return x, z


def validate_id(value: object) -> str:
    if not isinstance(value, str) or not UUID_RE.fullmatch(value):
        raise ValueError("entity IDs must be 32 lowercase hex digits")
    return value


def signed_area(corners: list[tuple[float, float]]) -> float:
    return sum(x * b - a * z for (x, z), (a, b) in
               zip(corners, corners[1:] + corners[:1])) / 2


def _orient(a, b, c) -> float:
    return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])


def _on_segment(a, b, p) -> bool:
    return (min(a[0], b[0])-1e-9 <= p[0] <= max(a[0], b[0])+1e-9 and
            min(a[1], b[1])-1e-9 <= p[1] <= max(a[1], b[1])+1e-9)


def _intersect(a, b, c, d) -> bool:
    ab_c, ab_d = _orient(a, b, c), _orient(a, b, d)
    cd_a, cd_b = _orient(c, d, a), _orient(c, d, b)
    if (ab_c > 1e-9 and ab_d < -1e-9 or ab_c < -1e-9 and ab_d > 1e-9) and \
       (cd_a > 1e-9 and cd_b < -1e-9 or cd_a < -1e-9 and cd_b > 1e-9):
        return True
    return any(abs(o) <= 1e-9 and _on_segment(s, e, p) for o, s, e, p in
               ((ab_c, a, b, c), (ab_d, a, b, d), (cd_a, c, d, a), (cd_b, c, d, b)))


def validate_outline(corners: list[tuple[float, float]]) -> None:
    n = len(corners)
    if not 3 <= n <= MAX_CORNERS:
        raise ValueError("closed outline needs 3..64 corners")
    if abs(signed_area(corners)) < 0.01:
        raise ValueError("room outline has near-zero area")
    for i in range(n):
        a, b = corners[i], corners[(i+1) % n]
        if math.dist(a, b) < 0.05:
            raise ValueError("room corners must be at least 5 cm apart")
        for j in range(i+1, n):
            if j in (i, (i+1) % n) or i == 0 and j == n-1:
                continue
            if _intersect(a, b, corners[j], corners[(j+1) % n]):
                raise ValueError("room outline crosses itself")


@dataclass
class Box:
    id: str
    label: str
    cx: float
    cz: float
    top_y: float
    yaw_deg: float
    w: float
    d: float
    h: float

    @classmethod
    def from_dict(cls, data: object) -> "Box":
        if not isinstance(data, dict):
            raise ValueError("box must be an object")
        label = data.get("label")
        if label not in LABELS:
            raise ValueError(f"unsupported furniture label: {label!r}")
        result = cls(validate_id(data.get("id")), label,
                     finite(data.get("cx"), "cx"), finite(data.get("cz"), "cz"),
                     finite(data.get("top_y"), "top_y"), finite(data.get("yaw_deg"), "yaw_deg"),
                     length(data.get("w"), "width", 0.05), length(data.get("d"), "depth", 0.05),
                     length(data.get("h"), "height", 0.05))
        if any(abs(v) > 100 for v in (result.cx, result.cz, result.top_y)):
            raise ValueError("box centre outside working area")
        return result

    def to_dict(self) -> dict:
        return vars(self).copy()


@dataclass
class Room:
    name: str
    universe: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    floor_y: float = 0
    ceiling_y: float = 2.5
    corners: list[tuple[float, float]] = field(default_factory=list)
    closed: bool = False
    boxes: list[Box] = field(default_factory=list)

    def validate(self) -> None:
        validate_id(self.id)
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 120:
            raise ValueError("room name must have 1..120 characters")
        if type(self.universe) is not int or not 0 <= self.universe < 2**64:
            raise ValueError("SteamVR universe must be an unsigned 64-bit integer")
        self.floor_y = finite(self.floor_y, "floor_y")
        self.ceiling_y = finite(self.ceiling_y, "ceiling_y")
        if abs(self.floor_y) > 100 or not 1.5 <= self.ceiling_y-self.floor_y <= 10:
            raise ValueError("ceiling must be 1.5..10 metres above the floor")
        if type(self.closed) is not bool:
            raise ValueError("closed must be boolean")
        if len(self.corners) > MAX_CORNERS:
            raise ValueError("too many corners")
        self.corners = [point_xz(p) for p in self.corners]
        for a, b in zip(self.corners, self.corners[1:]):
            if math.dist(a, b) < 0.05:
                raise ValueError("room corners must be at least 5 cm apart")
        if self.closed:
            validate_outline(self.corners)
        if len(self.boxes) > MAX_VOLUMES:
            raise ValueError("too many boxes")
        seen = {self.id}
        for box in self.boxes:
            box = Box.from_dict(box.to_dict())
            if box.id in seen:
                raise ValueError("duplicate entity UUID")
            seen.add(box.id)
            if box.top_y > self.ceiling_y+0.05 or box.top_y-box.h < self.floor_y-0.05:
                raise ValueError("furniture extends outside floor/ceiling")

    @classmethod
    def from_dict(cls, data: object) -> "Room":
        if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("version") != FORMAT_VERSION:
            raise ValueError("unsupported spatial room format")
        room = cls(data.get("name"), data.get("universe"), data.get("id"),
                   data.get("floor_y", 0), data.get("ceiling_y", 2.5),
                   data.get("corners", []), data.get("closed", False),
                   [Box.from_dict(b) for b in data.get("boxes", [])])
        room.validate()
        return room

    def to_dict(self) -> dict:
        self.validate()
        return {"format": FORMAT, "version": FORMAT_VERSION,
                "name": self.name, "universe": self.universe, "id": self.id,
                "floor_y": self.floor_y, "ceiling_y": self.ceiling_y,
                "corners": [list(p) for p in self.corners], "closed": self.closed,
                "boxes": [box.to_dict() for box in self.boxes]}


def load(path: Path) -> Room:
    path = Path(path)
    if path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("room file is too large")
    return Room.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save(path: Path, room: Room, *, replace: bool = True) -> None:
    """Atomic save, owner-only. No mutation of Steam, FramePort or Frametop settings."""
    data = json.dumps(room.to_dict(), indent=2, ensure_ascii=False) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not replace and path.exists():
        raise FileExistsError(str(path))
    temp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix=".room-", suffix=".tmp",
                                         dir=path.parent, delete=False) as f:
            temp = Path(f.name)
            os.fchmod(f.fileno(), 0o600)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _uuid_for(room_id: str, value: str) -> str:
    return uuid.uuid5(uuid.UUID(hex=room_id), value).hex


def _num(v: float) -> str:
    return format(v, ".9g")


def _edge_key(a: tuple[float, float], b: tuple[float, float]) -> str:
    a, b = sorted([a, b])
    return "wall:" + ",".join(_num(v) for v in (*a, *b))


def to_frameport(room: Room, *, now: int | None = None) -> str:
    """Generate FramePort v1 room.txt. No mesh needed; publication is explicit."""
    room.validate()
    if not room.closed:
        raise ValueError("finish the room outline before export")
    corners = room.corners[:]
    if signed_area(corners) < 0:
        corners.reverse()  # FramePort wants positive signed area in XZ.
    timestamp = int(time.time()) if now is None else now
    rows = ["frameport-room 1", f"universe {room.universe}", "source manual", f"time {timestamp}",
            f"room {room.id}", f"floor {_uuid_for(room.id, 'floor')} {_num(room.floor_y)}",
            f"ceiling {_uuid_for(room.id, 'ceiling')} {_num(room.ceiling_y)}",
            "outline " + str(len(corners)) + " " + " ".join(_num(v) for p in corners for v in p)]
    for a, b in zip(corners, corners[1:] + corners[:1]):
        rows.append("wall " + " ".join((_uuid_for(room.id, _edge_key(a, b)),
                    *(_num(v) for v in (*a, *b, room.floor_y, room.ceiling_y)))))
    for box in room.boxes:
        rows.append("volume " + " ".join((box.id, box.label, *(_num(v) for v in
                    (box.cx, box.cz, box.top_y, box.yaw_deg, box.w, box.d, box.h)))))
    return "\n".join(rows) + "\n"
