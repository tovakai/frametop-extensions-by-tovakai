"""Frametop DesktopToolbar layout math + config sanitize.

Mirrors screens/desktop_toolbar.inc. Pure Python — no OpenVR.
0.1.0: toolbar chrome is enabled by default (Start / Tasks / Displays / Tray).

SteamVR ControlBar grammar (from installed dashboard CSS on the Frame):
  bar 1800×180, #0e141b, radius 30px
  ControlBarGroup: pad 7px, radius 9001 / Large 21px, #23262E
  Small button 85px circle; Large button radius 16px
  Active outline #88ccf1 2px; section gap 1rem

Frametop modules (asymmetric tiles, not one button array). Default taskbar:
  [ Start ] [ pinned + running apps ... ] [ Displays ] [ tray: volume, Wi-Fi ]
Older modules (home, launcher, profiles 1–6, actions, user) stay available; a saved
toolbar that still has the previous default strip is moved to the taskbar default.
"""
from __future__ import annotations

import math
from typing import Any

SLOT_COUNT = 6

# Scale: SteamVR 1800×180 (10:1). OpenVR height = width * texAspect.
BAR_H_M = 0.090
BAR_ASPECT = 10.0  # width/height
PX = BAR_H_M / 180.0

# Cell sides ≤ BAR_H_M (square overlays: width sets height).
APP_W_M = BAR_H_M * (150.0 / 180.0) * 0.90
APP_H_M = APP_W_M
BTN_M = BAR_H_M * (85.0 / 180.0)
SEG_M = BAR_H_M * (64.0 / 180.0)
GROUP_PAD_M = BAR_H_M * (7.0 / 180.0)
INNER_GAP_M = 0.4 * 16 * PX
MODULE_GAP_M = 16 * PX
BAR_PAD_M = 12 * PX
ICON_FRAC = 45 / 85
HIT_PAD_FRAC = 0.12

GAP_M = INNER_GAP_M
ZONE_GAP_M = MODULE_GAP_M
GROUP_GAP_M = MODULE_GAP_M
TILE_M = APP_W_M
PILL_PAD_M = GROUP_PAD_M
TRAY_EXTRA_M = 0.0

# Follow modes shared with screens and instruments ("screen" = legacy one-shot: place the
# toolbar under screen N when no pose has been saved yet).
TOOLBAR_ANCHORS = ("world", "head", "head-rigid", "yaw-follow", "position-follow", "screen")
FOLLOW_ANCHORS = ("head", "head-rigid", "yaw-follow", "position-follow")
SCALE_RANGE = (0.5, 2.0)
DEFAULT_IDLE_OPACITY = 1.0  # fully opaque; lower it in Display Settings
MODULE_TYPES = ("home", "launcher", "profiles", "action", "user", "utilities",
                "start", "tasks", "displays", "tray")
SIMPLE_MODULES = ("profiles", "home", "user", "start", "tasks", "displays", "tray")  # no arguments
TRAY_ITEMS = ("volume", "wifi")
DEFAULT_GROUPS = {
    "left": [{"type": "start"}, {"type": "tasks"}],
    "center": [],
    "right": [{"type": "displays"}, {"type": "tray"}],
}
# The strip every toolbar had before the taskbar; saved copies of it are migrated.
LEGACY_DEFAULT_GROUPS = {
    "left": [{"type": "home"}, {"type": "launcher", "id": "launcher"}],
    "center": [{"type": "profiles"}],
    "right": [
        {"type": "action", "action": "layout.reset"},
        {"type": "action", "action": "screens.toggle"},
        {"type": "user"},
    ],
}

# Colours (CSS vars)
COLOR_BAR = (0x0E, 0x14, 0x1B)  # --gamepadui-darkest-grey
COLOR_GROUP = (0x23, 0x26, 0x2E)  # --gamepadui-darker-grey
COLOR_BTN = (0x3D, 0x44, 0x50)  # --gamepadui-dark-grey
COLOR_ACCENT = (0x88, 0xCC, 0xF1)  # Active outline


def module_cell_count(mod: dict[str, Any]) -> int:
    t = str(mod.get("type", "")).lower()
    if t == "profiles":
        return SLOT_COUNT
    if t == "tasks":  # one tile per task; `count` when known (ft-screens has the real list)
        return max(1, int(mod.get("count", 1) or 1))
    if t == "tray":
        return len(TRAY_ITEMS)
    if t in ("start", "displays"):
        return 1
    if t == "utilities":
        acts = mod.get("actions") or []
        return max(1, len(acts)) if isinstance(acts, list) else 1
    if t in ("home", "launcher", "action", "user"):
        return 1
    return 0


def module_button_count(mod: dict[str, Any]) -> int:
    return module_cell_count(mod)


def group_button_count(modules: list[dict[str, Any]]) -> int:
    return sum(module_cell_count(m) for m in modules)


def module_width(mod: dict[str, Any]) -> float:
    t = str(mod.get("type", "")).lower()
    if t in ("home", "launcher", "user", "start"):
        return APP_W_M
    if t == "tasks":
        n = module_cell_count(mod)
        return GROUP_PAD_M * 2 + n * APP_W_M + (n - 1) * INNER_GAP_M
    if t in ("displays", "tray"):
        n = module_cell_count(mod)
        return GROUP_PAD_M * 2 + n * BTN_M + (n - 1) * INNER_GAP_M
    if t == "profiles":
        n = SLOT_COUNT
        return GROUP_PAD_M * 2 + n * SEG_M + max(0, n - 1) * INNER_GAP_M
    if t == "utilities":
        n = module_cell_count(mod)
        return GROUP_PAD_M * 2 + n * BTN_M + max(0, n - 1) * INNER_GAP_M
    if t == "action":
        # lone action → treated as a utilities chip width
        return GROUP_PAD_M * 2 + BTN_M
    return 0.0


def ordered_modules(groups: dict[str, list[dict[str, Any]]]) -> list[tuple[str, dict[str, Any]]]:
    """Flatten left→center→right; coalesce consecutive right actions into one utilities module."""
    out: list[tuple[str, dict[str, Any]]] = []
    pending_actions: list[str] = []

    def flush_actions(side: str) -> None:
        nonlocal pending_actions
        if not pending_actions:
            return
        out.append((side, {"type": "utilities", "actions": list(pending_actions)}))
        pending_actions = []

    for side in ("left", "center", "right"):
        for mod in groups.get(side) or []:
            t = str(mod.get("type", "")).lower()
            if t == "action" and side == "right":
                pending_actions.append(str(mod.get("action") or "layout.reset"))
                continue
            flush_actions(side)
            out.append((side, mod))
        if side == "right":
            flush_actions("right")
    return out


def toolbar_content_width(groups: dict[str, list[dict[str, Any]]]) -> float:
    mods = ordered_modules(groups)
    if not mods:
        return BAR_PAD_M * 2
    widths = [module_width(m) for _, m in mods]
    return BAR_PAD_M * 2 + sum(widths) + MODULE_GAP_M * (len(widths) - 1)


def toolbar_total_width(groups: dict[str, list[dict[str, Any]]]) -> float:
    # Backing is 10:1; min width keeps visual height == BAR_H_M.
    return max(toolbar_content_width(groups), BAR_H_M * BAR_ASPECT)


def side_starts(groups: dict[str, list[dict[str, Any]]]) -> dict[str, float]:
    """Left edge of each side's run: left packed to the left end, right to the right end,
    center centred (clamped between them). Mirrors PlaceToolbar."""
    run: dict[str, float] = {"left": 0.0, "center": 0.0, "right": 0.0}
    count: dict[str, int] = {"left": 0, "center": 0, "right": 0}
    for side, mod in ordered_modules(groups):
        run[side] += (MODULE_GAP_M if count[side] else 0.0) + module_width(mod)
        count[side] += 1
    half = toolbar_total_width(groups) / 2
    starts = {"left": -half + BAR_PAD_M, "center": -run["center"] / 2, "right": half - BAR_PAD_M - run["right"]}
    if count["center"]:
        lo = starts["left"] + run["left"] + MODULE_GAP_M if count["left"] else -half + BAR_PAD_M
        hi = (starts["right"] - MODULE_GAP_M if count["right"] else half - BAR_PAD_M) - run["center"]
        starts["center"] = min(max(starts["center"], lo), max(lo, hi))
    return starts


def group_origins(groups: dict[str, list[dict[str, Any]]]) -> dict[str, float]:
    """Centre X of the first module that belongs to each side (compat)."""
    cursor = side_starts(groups)
    out: dict[str, float] = {}
    for side, mod in ordered_modules(groups):
        w = module_width(mod)
        if side not in out:
            out[side] = cursor[side] + w / 2
        cursor[side] += w + MODULE_GAP_M
    return out


def button_local_x(groups: dict[str, list[dict[str, Any]]]) -> list[tuple[str, str, float]]:
    """(group, label, local_x) along the unwrapped arc."""
    cursor = side_starts(groups)
    out: list[tuple[str, str, float]] = []
    for side, mod in ordered_modules(groups):
        t = str(mod.get("type", "")).lower()
        w = module_width(mod)
        x = cursor[side]
        if t in ("home", "launcher", "user"):
            label = t if t != "launcher" else f"launcher:{mod.get('id') or 'launcher'}"
            if t == "launcher":
                label = f"launcher:{mod.get('id') or 'launcher'}"
            elif t == "home":
                label = "home"
            else:
                label = "user"
            out.append((side, label, x + w / 2))
        elif t == "profiles":
            inner = x + GROUP_PAD_M + SEG_M / 2
            for s in range(1, SLOT_COUNT + 1):
                out.append((side, f"profile{s}", inner))
                inner += SEG_M + INNER_GAP_M
        elif t == "utilities":
            acts = mod.get("actions") or ["layout.reset"]
            inner = x + GROUP_PAD_M + BTN_M / 2
            for act in acts:
                out.append((side, f"action:{act}", inner))
                inner += BTN_M + INNER_GAP_M
        elif t == "action":
            out.append((side, f"action:{mod.get('action') or 'layout.reset'}", x + w / 2))
        elif t == "start":
            out.append((side, "popup:start", x + w / 2))
        elif t == "tasks":
            inner = x + GROUP_PAD_M + APP_W_M / 2
            for i in range(module_cell_count(mod)):
                out.append((side, f"task{i + 1}", inner))
                inner += APP_W_M + INNER_GAP_M
        elif t in ("displays", "tray"):
            names = ["profiles"] if t == "displays" else list(TRAY_ITEMS)
            inner = x + GROUP_PAD_M + BTN_M / 2
            for name in names:
                out.append((side, f"popup:{name}", inner))
                inner += BTN_M + INNER_GAP_M
        cursor[side] = x + w + MODULE_GAP_M
    return out


def overlay_curvature(width_m: float, radius_m: float) -> float:
    if radius_m <= 0.25 or width_m <= 0:
        return 0.0
    return max(0.0, min(1.0, width_m / (2 * math.pi * radius_m)))


def arc_point(u_m: float, radius_m: float, dz: float = 0.0) -> tuple[float, float, float]:
    if radius_m <= 0.25:
        return (u_m, 0.0, dz)
    a = u_m / radius_m
    c, sn = math.cos(a), math.sin(a)
    return (radius_m * sn - dz * sn, 0.0, radius_m - radius_m * c + dz * c)


def sphere_pitch_deg(bar_pos: tuple[float, float, float], hmd_pos: tuple[float, float, float]) -> tuple[float, float, float]:
    dx = hmd_pos[0] - bar_pos[0]
    dy = hmd_pos[1] - bar_pos[1]
    dz = hmd_pos[2] - bar_pos[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist < 1e-6:
        return (0.0, 0.0, 0.0)
    yaw = math.degrees(math.atan2(-dx, -dz))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, dy / dist))))
    return (yaw, pitch, dist)


# Docking (mirrors screens/toolbar_dock.inc).
DOCK_LIFT_M = 0.025      # toolbar top edge -> the lowest screen control
DOCK_SPACING_M = 0.05    # between docked screens
DOCK_SPAN_RAD = 1.6      # a wider group is pushed back to subtend this
DOCK_ANIM_SEC = 0.450    # same cosine ease window as profile apply (DEFAULT_PROFILE_DURATION_MS)
CHROME_GAP_FRAC = 0.06   # ChromeStyle::kGapFrac
BAR_HALF_H_FRAC = 12.0 / 256.0


def dock_ease(t: float) -> float:
    """Cosine ease-in-out 0..1 → 0..1 (mirrors DockEase / ft_layout.ease_in_out)."""
    t = max(0.0, min(1.0, float(t)))
    return 0.5 * (1.0 - math.cos(math.pi * t))


def dock_clearance(chrome_m: float, grip_m: float) -> float:
    """How far a screen's own controls hang below its bottom edge."""
    return chrome_m * (CHROME_GAP_FRAC + BAR_HALF_H_FRAC) + grip_m / 2


def dock_slots(screens: list[dict[str, float]], curve_m: float, scale: float = 1.0) -> list[dict[str, float]]:
    """Docked screens in slot order -> arc centre u, cylinder radius R and lift (all in the
    dock anchor's frame). Each screen dict: metres, height, chrome, grip."""
    if not screens:
        return []
    c = curve_m if curve_m > 0.25 else 1.0
    total = sum(s["metres"] for s in screens) + DOCK_SPACING_M * (len(screens) - 1)
    radius = max(c, total / DOCK_SPAN_RAD)
    top = BAR_H_M * scale / 2 + DOCK_LIFT_M
    u = -total / 2
    out = []
    for s in screens:
        w = s["metres"]
        out.append({"u": u + w / 2, "radius": radius,
                    "lift": top + dock_clearance(s.get("chrome", 0.0), s.get("grip", 0.0)) + s["height"] / 2,
                    "left": u, "right": u + w})
        u += w + DOCK_SPACING_M
    return out


def screen_attach_y(screen_height_m: float, toolbar_height_m: float = BAR_H_M, gap_m: float = 0.05) -> float:
    return -(screen_height_m / 2 + gap_m + toolbar_height_m / 2)


def _num(raw: Any, default: float, lo: float, hi: float) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default
    if math.isnan(v):
        return default
    return max(lo, min(hi, v))


def _vec(raw: Any, n: int) -> list[float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) < n:
        return None
    try:
        out = [float(v) for v in raw[:n]]
    except (TypeError, ValueError):
        return None
    return None if any(math.isnan(v) for v in out) else out


def sanitize_attention(raw: Any) -> dict[str, Any]:
    """Same shape as a screen's attention block; on by default for the toolbar."""
    a = raw if isinstance(raw, dict) else {}
    return {
        "enabled": bool(a.get("enabled", True)),
        "in_ms": _num(a.get("in_ms"), 150.0, 20.0, 2000.0),
        "out_ms": _num(a.get("out_ms"), 250.0, 20.0, 2000.0),
        "dwell_ms": _num(a.get("dwell_ms"), 80.0, 0.0, 1000.0),
        "hold_ms": _num(a.get("hold_ms"), 400.0, 0.0, 1000.0),
    }


def sanitize_deadzone(raw: Any) -> dict[str, Any]:
    d = raw if isinstance(raw, dict) else {}
    return {
        "enabled": bool(d.get("enabled", False)),
        "degrees": _num(d.get("degrees"), 15.0, 1.0, 90.0),
        "metres": _num(d.get("metres"), 0.15, 0.02, 1.0),
    }


def sanitize_pin(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    anchor = str(raw.get("anchor", "")).lower()
    rel = _vec(raw.get("rel"), 12)
    if anchor not in FOLLOW_ANCHORS or rel is None:
        return None
    return {"anchor": anchor, "rel": rel}


def sanitize_pinned_apps(raw: Any) -> list[str]:
    """Desktop ids pinned to the task area, in order, without duplicates."""
    out: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        did = str(item or "").strip()
        if did and did not in out and "/" not in did:
            out.append(did)
    return out


def sanitize_toolbar(raw: Any) -> dict[str, Any] | None:
    if raw is None or not isinstance(raw, dict):
        return None
    # 0.1.0: toolbar is the default desktop chrome; only an explicit false disables it.
    enabled = bool(raw.get("enabled", True))
    anchor = str(raw.get("anchor", "world")).lower().replace("_", "-")
    if anchor not in TOOLBAR_ANCHORS:
        anchor = "world"
    try:
        screen = max(1, int(raw.get("screen", 1)))
    except (TypeError, ValueError):
        screen = 1
    try:
        metres = max(0.25, min(float(raw.get("metres", 0.70)), 1.8))
    except (TypeError, ValueError):
        metres = 0.70
    try:
        offset_y = float(raw.get("offset_y", -0.14))
    except (TypeError, ValueError):
        offset_y = -0.14

    groups_in = raw.get("groups") if isinstance(raw.get("groups"), dict) else {}
    groups: dict[str, list[dict[str, Any]]] = {"left": [], "center": [], "right": []}
    for side in ("left", "center", "right"):
        items = groups_in.get(side) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            t = str(item.get("type", "")).lower()
            if t not in MODULE_TYPES:
                continue
            mod: dict[str, Any] = {"type": t}
            if t == "launcher":
                mod["id"] = str(item.get("id") or "launcher")
            if t == "action":
                act = str(item.get("action") or "").strip()
                if not act:
                    continue
                mod["action"] = act
            if t == "utilities":
                acts = item.get("actions") or []
                if not isinstance(acts, list) or not acts:
                    continue
                mod["actions"] = [str(a) for a in acts if str(a).strip()]
            groups[side].append(mod)

    if (enabled and not any(groups[s] for s in groups)) or groups == LEGACY_DEFAULT_GROUPS:
        groups = {side: [dict(m) for m in mods] for side, mods in DEFAULT_GROUPS.items()}

    active = _num(raw.get("active_opacity", raw.get("opacity")), 1.0, 0.0, 1.0)
    idle = _num(raw.get("idle_opacity"), min(active, DEFAULT_IDLE_OPACITY), 0.0, 1.0)
    if idle > active:  # looking must never be dimmer than looking away
        active, idle = idle, active
    out: dict[str, Any] = {
        "enabled": enabled,
        "anchor": anchor,
        "screen": screen,
        "metres": metres,
        "offset_y": offset_y,
        "scale": _num(raw.get("scale"), 1.0, *SCALE_RANGE),
        "active_opacity": round(active, 3),
        "idle_opacity": round(idle, 3),
        "attention": sanitize_attention(raw.get("attention")),
        "follow_deadzone": sanitize_deadzone(raw.get("follow_deadzone")),
        "pinned_apps": sanitize_pinned_apps(raw.get("pinned_apps")),
        "groups": groups,
    }
    pos, face = _vec(raw.get("pos"), 3), _vec(raw.get("face"), 2)
    if pos is not None and face is not None:
        out["pos"], out["face"] = pos, face
    pin = sanitize_pin(raw.get("pin"))
    if pin is not None and anchor in FOLLOW_ANCHORS and pin["anchor"] == anchor:
        out["pin"] = pin
    return out


def toolbar_socket_commands(tb: dict[str, Any], eye: tuple[float, float, float], heading: float,
                            turn_yaw) -> list[str]:
    """ft-screens commands that restore a sanitized toolbar (modules, look, then pose)."""
    if not tb.get("enabled"):
        return ["toolbar disable"]
    cmds = ["toolbar clear"]
    for side in ("left", "center", "right"):
        for mod in tb.get("groups", {}).get(side) or []:
            t = mod.get("type")
            if t in SIMPLE_MODULES:
                cmds.append(f"toolbar module {side} {t}")
            elif t == "launcher":
                cmds.append(f"toolbar module {side} launcher {mod.get('id') or 'launcher'}")
            elif t == "action":
                cmds.append(f"toolbar module {side} action {mod.get('action')}")
            elif t == "utilities":
                cmds.extend(f"toolbar module {side} action {a}" for a in mod.get("actions") or [])
    cmds.append(f"toolbar scale {float(tb.get('scale', 1.0)):.3f}")
    cmds.append(f"toolbar opacity {tb['active_opacity']:.3f} {tb['idle_opacity']:.3f}")
    att = tb["attention"]
    if att["enabled"]:
        cmds.append(f"toolbar attention on {att['in_ms']:.0f} {att['out_ms']:.0f} "
                    f"{att['dwell_ms']:.0f} {att['hold_ms']:.0f}")
    else:
        cmds.append("toolbar attention off")
    dz = tb["follow_deadzone"]
    cmds.append(f"toolbar deadzone on {dz['degrees']:.1f} {dz['metres']:.3f}" if dz["enabled"]
                else "toolbar deadzone off")
    cmds.append("toolbar enable")
    anchor = tb.get("anchor") or "world"
    if "pos" in tb and "face" in tb:
        world = turn_yaw(tuple(tb["pos"]), heading)
        c = tuple(e + v for e, v in zip(eye, world))
        cmds.append("toolbar pin world")
        cmds.append("toolbar place %.4f %.4f %.4f %.3f 0 0" % (c[0], c[1], c[2], float(tb["face"][0]) + heading))
    elif anchor == "screen":
        cmds.append(f"toolbar attach screen {int(tb.get('screen') or 1)}")
    else:
        cmds.append("toolbar pin world")
        cmds.append("toolbar recenter")
    if anchor in FOLLOW_ANCHORS:
        pin = tb.get("pin")
        if pin:
            cmds.append(f"toolbar pin {anchor} " + " ".join(f"{v:.5f}" for v in pin["rel"]))
        else:
            cmds.append(f"toolbar pin {anchor}")
    return cmds


def default_toolbar() -> dict[str, Any]:
    return sanitize_toolbar({"enabled": True, "groups": {}}) or {}
