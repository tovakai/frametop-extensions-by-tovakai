"""Headless manual placement state machine. A VR UI can feed it controller rays.

It owns NO SteamVR controller hooks and NO compositor resources. Transitions are
testable while the eventual VR overlay supplies pose/input events.
"""
from __future__ import annotations

import copy
import math
import uuid

from room_model import Box, LABELS, MAX_CORNERS, MAX_VOLUMES, Room, finite, point_xz, validate_outline


def floor_hit(origin, direction, floor_y: float, max_distance: float = 10) -> tuple[float, float]:
    """Intersect tracked controller ray with the floor; reject parallel/behind/far."""
    if not isinstance(origin, (list, tuple)) or not isinstance(direction, (list, tuple)) or \
       len(origin) != 3 or len(direction) != 3:
        raise ValueError("ray needs three-component origin and direction")
    x, y, z = (finite(v, "ray origin") for v in origin)
    dx, dy, dz = (finite(v, "ray direction") for v in direction)
    if not 0.9 <= math.sqrt(dx*dx + dy*dy + dz*dz) <= 1.1:
        raise ValueError("ray direction must be unit length")
    if abs(dy) < 1e-5:
        raise ValueError("controller ray is parallel to the floor")
    t = (floor_y-y)/dy
    if not 0 < t <= max_distance:
        raise ValueError("controller ray does not hit the floor in front of you")
    return point_xz([x+t*dx, z+t*dz])


def box_between(a, b, label: str, height: float, floor_y: float, yaw_deg: float = 0) -> Box:
    if label not in LABELS:
        raise ValueError("unsupported furniture label")
    a, b = point_xz(a), point_xz(b)
    height = finite(height, "box height")
    yaw_deg = finite(yaw_deg, "yaw")
    if not 0.05 <= height <= 10:
        raise ValueError("box height must be 5 cm..10 m")
    dx, dz = b[0]-a[0], b[1]-a[1]
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    w, d = abs(c*dx-s*dz), abs(s*dx+c*dz)
    if w < 0.05 or d < 0.05:
        raise ValueError("draw a box at least 5 cm wide and deep")
    return Box(uuid.uuid4().hex, label, (a[0]+b[0])/2, (a[1]+b[1])/2,
               floor_y+height, yaw_deg, w, d, height)


class Editor:
    def __init__(self, room: Room) -> None:
        self.room = room
        self.pending: tuple[float, float] | None = None
        self.history: list[tuple[Room, tuple[float, float] | None]] = []

    def _checkpoint(self) -> None:
        self.history.append((copy.deepcopy(self.room), self.pending))
        if len(self.history) > 50:
            self.history.pop(0)

    def dispatch(self, event: dict) -> dict:
        """Apply one explicit command, never writes files or changes the desktop."""
        if not isinstance(event, dict):
            raise ValueError("event must be a JSON object")
        action = event.get("action")
        if action == "status":
            return {"corners": len(self.room.corners), "closed": self.room.closed,
                    "boxes": len(self.room.boxes), "box_pending": self.pending is not None,
                    "universe": self.room.universe}
        if action == "undo":
            if not self.history:
                raise ValueError("nothing to undo")
            self.room, self.pending = self.history.pop()
        elif action == "corner":
            if self.room.closed:
                raise ValueError("outline already closed")
            if len(self.room.corners) >= MAX_CORNERS:
                raise ValueError("too many corners")
            p = floor_hit(event.get("origin"), event.get("direction"), self.room.floor_y)
            if self.room.corners and math.dist(p, self.room.corners[-1]) < 0.05:
                raise ValueError("new corner is too close")
            self._checkpoint()
            self.room.corners.append(p)
        elif action == "close":
            validate_outline(self.room.corners)
            self._checkpoint()
            self.room.closed = True
        elif action == "box_start":
            if not self.room.closed:
                raise ValueError("complete the outline first")
            p = floor_hit(event.get("origin"), event.get("direction"), self.room.floor_y)
            self._checkpoint()
            self.pending = p
        elif action == "box_finish":
            if self.pending is None:
                raise ValueError("point at the first box corner first")
            if len(self.room.boxes) >= MAX_VOLUMES:
                raise ValueError("too many furniture boxes")
            p = floor_hit(event.get("origin"), event.get("direction"), self.room.floor_y)
            box = box_between(self.pending, p, event.get("label", "OTHER"),
                              event.get("height", 0.75), self.room.floor_y,
                              event.get("yaw_deg", 0))
            if box.top_y > self.room.ceiling_y:
                raise ValueError("furniture exceeds ceiling height")
            self._checkpoint()
            self.room.boxes.append(box)
            self.pending = None
        elif action == "set_ceiling":
            ceiling_y = finite(event.get("height"), "ceiling height") + self.room.floor_y
            if not 1.5 <= ceiling_y-self.room.floor_y <= 10:
                raise ValueError("ceiling height must be 1.5..10 m")
            if any(b.top_y > ceiling_y for b in self.room.boxes):
                raise ValueError("ceiling would cut through furniture")
            self._checkpoint()
            self.room.ceiling_y = ceiling_y
        elif action == "set_box_label":
            ident = event.get("id")
            label = event.get("label")
            if label not in LABELS:
                raise ValueError("unsupported furniture label")
            box = next((b for b in self.room.boxes if b.id == ident), None)
            if box is None:
                raise ValueError("box ID not found")
            if box.label != label:
                self._checkpoint()
                box.label = label
        elif action == "resize_box":
            ident = event.get("id")
            height = finite(event.get("height"), "furniture height")
            if not 0.05 <= height <= 10:
                raise ValueError("furniture height must be 5 cm..10 m")
            box = next((b for b in self.room.boxes if b.id == ident), None)
            if box is None:
                raise ValueError("box ID not found")
            # Keep the furniture's bottom fixed while resizing upwards.
            bottom_y = box.top_y - box.h
            if bottom_y + height > self.room.ceiling_y + 1e-9:
                raise ValueError("furniture height exceeds room ceiling")
            if abs(height - box.h) >= 1e-8:
                self._checkpoint()
                box.top_y = bottom_y + height
                box.h = height
        elif action == "rotate_box":
            ident = event.get("id")
            delta = finite(event.get("delta_deg"), "rotation delta")
            if not -360 <= delta <= 360:
                raise ValueError("rotation increment outside allowed range")
            box = next((b for b in self.room.boxes if b.id == ident), None)
            if box is None:
                raise ValueError("box ID not found")
            if delta:
                self._checkpoint()
                box.yaw_deg = (box.yaw_deg + delta) % 360
        elif action == "delete_box":
            ident = event.get("id")
            if not isinstance(ident, str) or not any(b.id == ident for b in self.room.boxes):
                raise ValueError("box ID not found")
            self._checkpoint()
            self.room.boxes = [b for b in self.room.boxes if b.id != ident]
        else:
            raise ValueError(f"unknown action: {action!r}")
        self.room.validate()
        return self.dispatch({"action": "status"})
