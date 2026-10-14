"""World-anchored Spatial Profiles runtime (Frametop extension API v1).

Own store; does not write Frametop's upstream config or legacy profile file.
Requires a running ft-screens compositor. No background daemon.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import tempfile

from frametop_ext import Frametop, ExtensionError

DEFAULT_STORE = Path.home() / ".config" / "frametop-extensions" / "spatial-profiles.json"
DEFAULT_DURATION = 450
SLOTS = 6
REQUIRED_CAPS = {"screen.status", "screen.move", "screen.opacity"}
# Keep these v1 profile fields intentionally narrow, to avoid lossy migrations.
SCREEN_FIELDS = {"pos", "face", "roll", "metres", "curve", "opacity", "hidden"}


class ProfileError(ValueError):
    pass


def _finite(value, low=None, high=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ProfileError("screen parameters must be finite numbers")
    if low is not None and value < low or high is not None and value > high:
        raise ProfileError(f"screen parameter outside {low}..{high}")
    return float(value)


def _tuple(value, length):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ProfileError(f"expected {length} coordinates")
    return [_finite(x) for x in value]


def validate_profile(profile):
    """No partial or lossy application of legacy-only capabilities."""
    if not isinstance(profile, dict) or set(profile) != {"screens"}:
        raise ProfileError("only spatial-only {'screens': [...]} profiles are supported")
    screens = profile["screens"]
    if not isinstance(screens, list) or not (1 <= len(screens) <= 9):
        raise ProfileError("profile needs 1..9 desktop screens")
    normalized = []
    for index, data in enumerate(screens, 1):
        if not isinstance(data, dict) or set(data) != SCREEN_FIELDS:
            raise ProfileError(f"screen {index}: unsupported or missing fields; no lossy migration")
        pos, face = _tuple(data["pos"], 3), _tuple(data["face"], 2)
        roll = _finite(data["roll"])
        width = _finite(data["metres"], .15, 12)
        curve = _finite(data["curve"], 0, 1000)
        if 0 < curve < .5:
            raise ProfileError(f"screen {index}: curved radius must be at least 0.5 metres")
        alpha = _finite(data["opacity"], 0, 1)
        if type(data["hidden"]) is not bool:
            raise ProfileError(f"screen {index}: hidden must be true/false")
        normalized.append({
            "pos": pos, "face": face, "roll": roll,
            "metres": width, "curve": curve, "opacity": alpha,
            "hidden": data["hidden"],
        })
    return {"screens": normalized}


def empty_store():
    return {"version": 1, "current": None, "profiles": {}, "slots": [None] * SLOTS}


def validate_store(data):
    if not isinstance(data, dict) or set(data) != set(empty_store()):
        raise ProfileError("invalid versioned Spatial Profiles store")
    if type(data["version"]) is not int or data["version"] != 1:
        raise ProfileError("unsupported Spatial Profiles store version")
    profiles = data["profiles"]
    if not isinstance(profiles, dict) or not all(
        isinstance(k, str) and k and len(k) <= 100 for k in profiles
    ):
        raise ProfileError("invalid profile names")
    for profile in profiles.values():
        validate_profile(profile)
    current = data["current"]
    if current is not None and current not in profiles:
        raise ProfileError("current references an unknown profile")
    slots = data["slots"]
    if not isinstance(slots, list) or len(slots) != SLOTS or any(
        s is not None and s not in profiles for s in slots
    ):
        raise ProfileError("slot references an unknown profile")
    return data


def read_store(path=DEFAULT_STORE):
    path = Path(path)
    try:
        return validate_store(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return empty_store()
    except (OSError, ValueError) as exc:
        raise ProfileError(f"couldn't read profiles from {path}: {exc}") from exc


def _write_store(path, store):
    """Atomic commit with owner-only permissions; caller must hold _locked."""
    validate_store(store)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=".spatial-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            os.fchmod(file.fileno(), 0o600)
            json.dump(store, file, indent=2, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def _locked(path):
    """Serialize modifications and live applies, including competing CLIs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(str(path) + ".lock", "a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _cross(a, b):
    return [a[1]*b[2] - a[2]*b[1],
            a[2]*b[0] - a[0]*b[2],
            a[0]*b[1] - a[1]*b[0]]


def _normal(a):
    size = math.sqrt(_dot(a, a))
    if size < .000001:
        raise ProfileError("invalid screen orientation matrix")
    return [x/size for x in a]


def _yaw_pitch(vector):
    size = math.sqrt(_dot(vector, vector))
    if size < .000001:
        raise ProfileError("invalid screen facing vector")
    return [math.degrees(math.atan2(-vector[0], -vector[2])),
            math.degrees(math.asin(max(-1, min(1, vector[1] / size))))]


def _turn(vector, yaw):
    a = math.radians(yaw)
    s, c = math.sin(a), math.cos(a)
    return [vector[0]*c + vector[2]*s, vector[1], -vector[0]*s + vector[2]*c]


def _round(values, places):
    return [round(x, places) for x in values]


def _read_get(reply):
    fields = reply.split()
    if len(fields) not in (17, 29) or fields[0] != "ok":
        raise ProfileError("malformed 'get' reply")
    try:
        values = [float(x) for x in fields[1:16]]
    except ValueError as exc:
        raise ProfileError("non-numeric screen pose") from exc
    if not all(math.isfinite(x) for x in values):
        raise ProfileError("non-finite screen pose")
    pin = fields[16]
    if pin not in {"none", "head", "left", "right"} or (
        pin == "none" and len(fields) != 17 or pin != "none" and len(fields) != 29
    ):
        raise ProfileError("malformed pin state")
    return {
        "center": values[:3],
        "x_axis": values[3:6],
        "z_axis": values[9:12],
        "metres": values[12],
        "curve": values[14],
        "pin": pin,
    }


def _read_head(client):
    fields = client.request("head").split()
    if len(fields) != 5:
        raise ProfileError("malformed headset pose")
    try:
        vals = [float(x) for x in fields[1:]]
    except ValueError as exc:
        raise ProfileError("non-numeric headset pose") from exc
    if not all(math.isfinite(x) for x in vals):
        raise ProfileError("invalid headset pose")
    return vals[:3], vals[3]


def _screen_numbers(client):
    fields = client.request("screens").split()
    if len(fields) < 3 or fields[0] != "ok":
        raise ProfileError("malformed screens reply")
    try:
        count = int(fields[1])
    except ValueError as exc:
        raise ProfileError("invalid screen count") from exc
    if not 1 <= count <= 9 or len(fields) != count + 2:
        raise ProfileError("screen list/count mismatch")
    numbers = []
    for entry in fields[2:]:
        match = re.fullmatch(r"(\d+):(\d+)x(\d+):([0-9.]+)", entry)
        if match is None:
            raise ProfileError(f"invalid screen entry: {entry}")
        numbers.append(int(match[1]))
        if int(match[2]) <= 0 or int(match[3]) <= 0:
            raise ProfileError("desktop screen has no buffer yet")
    if numbers != list(range(1, count+1)):
        raise ProfileError("non-contiguous desktop screen list")
    return numbers


def _visible_hidden(client):
    fields = client.request("concealed").split()
    if not fields or fields[0] != "ok":
        raise ProfileError("malformed concealed reply")
    try:
        hidden = {int(x) for x in fields[1:]}
    except ValueError as exc:
        raise ProfileError("malformed hidden screen list") from exc
    return hidden


def require_core(client):
    if client.api_version() < 1 or not REQUIRED_CAPS.issubset(client.capabilities()):
        raise ProfileError("Frametop extension API v1 with screen.move, screen.opacity and screen.status required")


def snapshot(client):
    """Read the actual live arrangement in head-relative coordinates.

    Refuse transient animations and pinned displays; neither is safe to
    reinterpret as a static world-space profile.
    """
    require_core(client)
    numbers = _screen_numbers(client)
    eye, heading = _read_head(client)
    hidden = _visible_hidden(client)
    result = []
    for n in numbers:
        g = _read_get(client.request(f"get {n}"))
        status = client.screen_status(n)
        if g["pin"] != "none" or status.get("pinned") != "none":
            raise ProfileError(f"screen {n} is pinned; v0.1.0 supports world-anchored screens only")
        if status.get("moving") != "0" or status.get("fading") != "0":
            raise ProfileError(f"screen {n} is animating; capture after transitions finish")
        alpha = _finite(float(status["opacity"]), 0, 1)
        relative = _turn([c-e for c, e in zip(g["center"], eye)], -heading)
        front = [-x for x in g["z_axis"]]
        yaw, pitch = _yaw_pitch(front)
        right = _normal(_cross([0, 1, 0], g["z_axis"]))
        up = _cross(g["z_axis"], right)
        roll = math.degrees(math.atan2(_dot(g["x_axis"], up), _dot(g["x_axis"], right)))
        result.append({
            "pos": _round(relative, 4),
            "face": _round([yaw - heading, pitch], 2),
            "roll": round(roll, 2),
            "metres": round(_finite(g["metres"], .15, 12), 4),
            "curve": round(_finite(g["curve"], 0, 1000), 3),
            "opacity": round(alpha, 4),
            "hidden": n in hidden,
        })
    return validate_profile({"screens": result})


def targets(profile, eye, heading):
    """Transform a captured head-relative layout into current standing-world space."""
    profile = validate_profile(profile)
    result = []
    for screen in profile["screens"]:
        delta = _turn(screen["pos"], heading)
        result.append((
            [e+d for e, d in zip(eye, delta)],
            [screen["face"][0] + heading, screen["face"][1]],
            screen,
        ))
    return result


def _apply_commands(client, target, duration):
    for n, (center, face, screen) in enumerate(target, 1):
        # Native generic commands for width/curve/hidden; v1 animation endpoint
        # for pose and opacity. Never change KWin resolution or launch apps.
        client.request(f"width {n} {screen['metres']:.4f}")
        client.request(f"curve {n} {screen['curve']:.3f}")
        client.move(n, *center, *face, screen["roll"], duration_ms=duration)
        client.opacity(n, screen["opacity"], duration_ms=duration)
        client.request(f"{'conceal' if screen['hidden'] else 'reveal'} {n}")


def apply_profile(client, profile, duration=DEFAULT_DURATION):
    if type(duration) is not int or not 0 <= duration <= 10000:
        raise ProfileError("duration must be an integer 0..10000 ms")
    require_core(client)
    profile = validate_profile(profile)
    numbers = _screen_numbers(client)
    if len(profile["screens"]) != len(numbers):
        raise ProfileError("profile screen count does not match live desktop")
    # Snapshot first for rollback, and refuse pinned or transitioning screens.
    before = snapshot(client)
    eye, heading = _read_head(client)
    steps = targets(profile, eye, heading)
    try:
        _apply_commands(client, steps, duration)
    except (ExtensionError, ProfileError, ValueError) as exc:
        try:
            # Best effort only: a device or compositor can disappear mid-command.
            _apply_commands(client, targets(before, eye, heading), 0)
        except (ExtensionError, ProfileError, ValueError) as undo:
            raise ProfileError(f"apply failed ({exc}); rollback ALSO failed ({undo})") from exc
        raise ProfileError(f"apply failed ({exc}); attempted to restore initial screen state") from exc


def save_current(path, name, client):
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ProfileError("profile name must be 1..100 nonblank characters")
    with _locked(path):
        store = read_store(path)
        # Collect before writing. A failed capture never damages saved profiles.
        store["profiles"][name] = snapshot(client)
        store["current"] = name
        _write_store(path, store)
    return store


def switch(path, name, client, duration=DEFAULT_DURATION):
    with _locked(path):
        store = read_store(path)
        if name not in store["profiles"]:
            raise ProfileError(f"unknown profile: {name!r}")
        apply_profile(client, store["profiles"][name], duration)
        store["current"] = name
        _write_store(path, store)
    return store


def bind_slot(path, number, name):
    if type(number) is not int or not 1 <= number <= SLOTS:
        raise ProfileError("slot must be 1..6")
    with _locked(path):
        store = read_store(path)
        if name is not None and name not in store["profiles"]:
            raise ProfileError(f"unknown profile: {name!r}")
        store["slots"][number-1] = name
        _write_store(path, store)
    return store


def use_slot(path, number, client, duration=DEFAULT_DURATION):
    if type(number) is not int or not 1 <= number <= SLOTS:
        raise ProfileError("slot must be 1..6")
    with _locked(path):
        store = read_store(path)
        name = store["slots"][number-1]
        if name is None:
            raise ProfileError(f"slot {number} is empty")
        apply_profile(client, store["profiles"][name], duration)
        store["current"] = name
        _write_store(path, store)
    return name


def delete_profile(path, name):
    with _locked(path):
        store = read_store(path)
        if name not in store["profiles"]:
            raise ProfileError(f"unknown profile: {name!r}")
        del store["profiles"][name]
        store["slots"] = [None if x == name else x for x in store["slots"]]
        if store["current"] == name:
            store["current"] = None
        _write_store(path, store)
    return store
