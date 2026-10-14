"""Frametop taskbar model: tasks, click decisions, popup state and popup layouts.

Pure Python (no Qt / cairo / D-Bus) so it is unit-tested on any machine; session/ft-taskbar.py
renders and runs the providers on top of it, screens/toolbar_taskbar.inc mirrors the click
and popup rules.

Tasks = pinned apps (layout toolbar.pinned_apps, in order) then running apps, one entry per
application. Windows come from the nested KWin (a KWin script; never process scraping) and
are matched to an application by desktop file name, then StartupWMClass, then the resource
class against the desktop id.
"""
from __future__ import annotations

import math
import re
import urllib.parse
import zlib
from typing import Any, Iterable

# Popup kinds. One is open at a time.
POPUP_KINDS = ("start", "windows", "taskmenu", "profiles", "volume", "wifi")

# Start menu: freedesktop main categories, shown in this order when present.
START_CATEGORIES = [
    ("All", ""), ("Internet", "Network"), ("Games", "Game"), ("Media", "AudioVideo"),
    ("Graphics", "Graphics"), ("Office", "Office"), ("Development", "Development"),
    ("Utilities", "Utility"), ("System", "System"), ("Settings", "Settings"),
]
START_COLUMNS = 4
START_ROWS = 4


def _norm(name: str) -> str:
    n = (name or "").strip().lower()
    if n.endswith(".desktop"):
        n = n[:-8]
    return n


def app_index(apps: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Lookups for matching windows to applications: id, short id and wm class."""
    idx: dict[str, dict[str, Any]] = {}
    for a in apps:
        did = _norm(a.get("id", ""))
        if not did:
            continue
        idx.setdefault(did, a)
        idx.setdefault(did.rsplit(".", 1)[-1], a)  # org.kde.konsole -> konsole
        if a.get("wm_class"):
            idx.setdefault("wm:" + _norm(a["wm_class"]), a)
    return idx


def window_app(win: dict[str, Any], idx: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any] | None]:
    """(task key, matching app or None) for one KWin window."""
    for key in (_norm(win.get("desktop", "")),):
        if key and key in idx:
            return _norm(idx[key]["id"]), idx[key]
    cls = _norm(win.get("cls", ""))
    if cls and "wm:" + cls in idx:
        a = idx["wm:" + cls]
        return _norm(a["id"]), a
    if cls and cls in idx:
        return _norm(idx[cls]["id"]), idx[cls]
    key = _norm(win.get("desktop", "")) or cls or ("window:" + str(win.get("id", "")))
    return key, None


def merge_tasks(pinned: list[str], windows: list[dict[str, Any]], apps: Iterable[dict[str, Any]],
                active: str = "") -> list[dict[str, Any]]:
    """Pinned first (pin order), then running apps (first-seen order); one task per app."""
    idx = app_index(apps)
    tasks: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def task(key: str, app: dict[str, Any] | None, desktop_id: str = "") -> dict[str, Any]:
        if key not in tasks:
            tasks[key] = {
                "id": key,
                "desktop_id": (app or {}).get("id") or desktop_id,
                "name": (app or {}).get("name") or desktop_id or key,
                "icon": (app or {}).get("icon") or "",
                "pinned": False,
                "windows": [],
                "focused": False,
            }
            order.append(key)
        return tasks[key]

    for did in pinned:
        key = _norm(did)
        app = idx.get(key)
        task(_norm(app["id"]) if app else key, app, did)["pinned"] = True
    for win in windows:
        key, app = window_app(win, idx)
        t = task(key, app, win.get("desktop") or "")
        if not t["icon"] and not app:
            t["name"] = win.get("caption") or t["name"]
            t["icon"] = win.get("desktop") or win.get("cls") or ""
        t["windows"].append({"id": str(win.get("id", "")), "caption": win.get("caption") or t["name"],
                             "minimized": bool(win.get("minimized")), "output": win.get("output") or "",
                             "maximized": bool(win.get("maximized")), "above": bool(win.get("above")),
                             "fullscreen": bool(win.get("fullscreen"))})
        if active and str(win.get("id", "")) == active:
            t["focused"] = True
    return [tasks[k] for k in order]


def task_click(task: dict[str, Any]) -> tuple[str, str]:
    """What clicking a task does: launch it, focus its only window (minimize it when it
    already has focus, like a desktop taskbar), or offer the windows."""
    wins = task.get("windows") or []
    if not wins:
        return ("launch", task.get("desktop_id") or "")
    if len(wins) == 1:
        if task.get("focused") and not wins[0].get("minimized"):
            return ("minimize", wins[0]["id"])
        return ("focus", wins[0]["id"])
    return ("expose", task.get("id") or "")


def output_order(names: Iterable[str]) -> list[str]:
    """KWin output names in Frametop screen order (WL-0, WL-1, ... WL-10), as ft_layout."""
    return sorted(set(n for n in names if n),
                  key=lambda n: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", n)])


def toggle_pin(pinned: list[str], desktop_id: str) -> list[str]:
    out = [p for p in pinned if _norm(p) != _norm(desktop_id)]
    if len(out) == len(pinned):
        out.append(desktop_id)
    return out


class PopupState:
    """One popup at a time; same anchor toggles; any visibility change closes it."""

    def __init__(self) -> None:
        self.kind = ""
        self.arg = ""

    def open(self, kind: str, arg: str = "") -> bool:
        """True when it is now open (False: it was the same popup, now closed)."""
        if kind not in POPUP_KINDS:
            raise ValueError(kind)
        if self.kind == kind and self.arg == arg:
            self.close("toggle")
            return False
        self.kind, self.arg = kind, arg
        return True

    def close(self, _reason: str = "") -> None:
        self.kind, self.arg = "", ""

    def on_click_elsewhere(self, on_popup: bool, on_toolbar: bool) -> None:
        if self.kind and not on_popup and not on_toolbar:
            self.close("click-away")

    def on_visibility(self, toolbar_visible: bool) -> None:
        if not toolbar_visible:
            self.close("hidden")

    def is_open(self) -> bool:
        return bool(self.kind)


# ---------------------------------------------------------------- start menu model

def start_categories(apps: Iterable[dict[str, Any]]) -> list[tuple[str, str]]:
    """Category chips that have at least one app (All always first)."""
    present = set()
    for a in apps:
        present.update(a.get("categories") or [])
    return [(label, cat) for label, cat in START_CATEGORIES if not cat or cat in present]


def start_page(apps: list[dict[str, Any]], category: str, page: int,
               per_page: int = START_COLUMNS * START_ROWS) -> tuple[list[dict[str, Any]], int, int]:
    """(apps on this page, page clamped, page count) for a category filter."""
    pool = [a for a in apps if not category or category in (a.get("categories") or [])]
    pages = max(1, math.ceil(len(pool) / per_page))
    page = max(0, min(page, pages - 1))
    return pool[page * per_page:(page + 1) * per_page], page, pages


# ---------------------------------------------------------------- popup layout (pixels)

PX_PER_M = 1000          # popup texture pixels per metre (1 px = 1 mm)
PAD = 16
ROW_H = 56
HEADER_H = 52


def rect(x: int, y: int, w: int, h: int) -> dict[str, int]:
    return {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}


def list_layout(rows: list[dict[str, Any]], width: int = 420, header: str = "",
                footer: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Vertical list popup: optional header, one row per entry, optional footer rows."""
    y = PAD + (HEADER_H if header else 0)
    items = []
    for r in rows:
        items.append(dict(r, **rect(PAD, y, width - 2 * PAD, ROW_H)))
        y += ROW_H + 4
    for r in footer or []:
        items.append(dict(r, **rect(PAD, y + 6, width - 2 * PAD, ROW_H - 8)))
        y += ROW_H + 2
    return {"w": width, "h": y + PAD, "header": header, "items": items}


def start_layout(page_apps: list[dict[str, Any]], cats: list[tuple[str, str]], category: str,
                 page: int, pages: int, pinned: list[str]) -> dict[str, Any]:
    cell_w, cell_h = 132, 120
    width = PAD * 2 + START_COLUMNS * cell_w
    items = []
    # Category chips, wrapped onto rows.
    x, y, chip_h = PAD, PAD + HEADER_H, 40
    for label, cat in cats:
        w = 22 + 11 * len(label)
        if x + w > width - PAD:
            x, y = PAD, y + chip_h + 6
        items.append(dict({"id": "cat:" + (cat or "all"), "kind": "chip", "label": label,
                           "active": cat == category}, **rect(x, y, w, chip_h)))
        x += w + 6
    grid_y = y + chip_h + 12
    pin_set = {_norm(p) for p in pinned}
    for i, a in enumerate(page_apps):
        r, c = divmod(i, START_COLUMNS)
        cx, cy = PAD + c * cell_w, grid_y + r * cell_h
        items.append(dict({"id": "app:" + a["id"], "kind": "app", "label": a["name"], "icon": a.get("icon", ""),
                           "pinned": _norm(a["id"]) in pin_set}, **rect(cx + 4, cy + 4, cell_w - 8, cell_h - 8)))
        items.append(dict({"id": "pin:" + a["id"], "kind": "pin", "pinned": _norm(a["id"]) in pin_set},
                          **rect(cx + cell_w - 40, cy + 6, 32, 32)))
    foot_y = grid_y + START_ROWS * cell_h + 6
    if pages > 1:
        items.append(dict({"id": "page:prev", "kind": "nav", "label": "‹", "enabled": page > 0},
                          **rect(PAD, foot_y, 64, 44)))
        items.append(dict({"id": "page:next", "kind": "nav", "label": "›", "enabled": page < pages - 1},
                          **rect(width - PAD - 64, foot_y, 64, 44)))
    return {"w": width, "h": foot_y + 44 + PAD, "header": "Applications",
            "subtitle": f"{page + 1} / {pages}" if pages > 1 else "", "items": items}


def volume_layout(level: float, muted: bool, device: str) -> dict[str, Any]:
    width = 420
    y = PAD + HEADER_H
    items = [
        dict({"id": "mute", "kind": "mute", "label": "Unmute" if muted else "Mute", "active": muted},
             **rect(PAD, y, 72, 56)),
        dict({"id": "slider", "kind": "slider", "value": max(0.0, min(1.0, level)), "muted": muted},
             **rect(PAD + 84, y + 8, width - 2 * PAD - 84, 40)),
    ]
    y += 56 + 10
    items.append(dict({"id": "settings", "kind": "row", "label": "Sound settings…"}, **rect(PAD, y, width - 2 * PAD, 48)))
    header = "Volume  " + ("muted" if muted else f"{int(round(level * 100))}%")
    return {"w": width, "h": y + 48 + PAD, "header": header, "subtitle": device, "items": items}


def wifi_layout(enabled: bool, networks: list[dict[str, Any]], max_rows: int = 7) -> dict[str, Any]:
    width = 460
    y = PAD + HEADER_H
    items = [dict({"id": "wifi:toggle", "kind": "toggle", "label": "Wi-Fi on" if enabled else "Wi-Fi off",
                   "active": enabled}, **rect(PAD, y, width - 2 * PAD, 52))]
    y += 60
    for n in networks[:max_rows] if enabled else []:
        items.append(dict({"id": "net:" + n["key"], "kind": "network", "label": n["ssid"], "bars": n["bars"],
                           "secure": n["secure"], "active": n["active"], "known": n["known"]},
                          **rect(PAD, y, width - 2 * PAD, 52)))
        y += 56
    items.append(dict({"id": "settings", "kind": "row", "label": "Network settings…"}, **rect(PAD, y + 4, width - 2 * PAD, 48)))
    return {"w": width, "h": y + 52 + PAD, "header": "Wi-Fi", "items": items}


def profiles_layout(names: list[str], current: str, slots: Any) -> dict[str, Any]:
    """slots: ft_layout's list (index 0 = slot 1) or a {slot: name} mapping."""
    pairs = (slots or {}).items() if isinstance(slots, dict) else \
        ((i + 1, v) for i, v in enumerate(slots or []))
    slot_of = {}
    for k, v in pairs:
        if v:
            slot_of.setdefault(str(v), str(k))
    rows = [{"id": "profile:" + n, "kind": "profile", "label": n, "active": n == current,
             "badge": slot_of.get(n, "")} for n in names]
    if not rows:
        rows = [{"id": "none", "kind": "row", "label": "No saved profiles yet", "enabled": False}]
    return list_layout(rows, header="Displays", footer=[{"id": "settings", "kind": "row",
                                                         "label": "Display Settings…"}])


def windows_layout(task: dict[str, Any]) -> dict[str, Any]:
    rows = [{"id": "win:" + w["id"], "kind": "window", "label": w["caption"], "active": False,
             "minimized": w.get("minimized", False)} for w in task.get("windows") or []]
    return list_layout(rows, width=520, header=task.get("name") or "Windows")


MENU_ROW_H = 44
MENU_GAP = 12  # between the menu's groups


def task_menu_layout(task: dict[str, Any], actions: list[dict[str, Any]], outputs: list[str],
                     can_launch: bool) -> dict[str, Any]:
    """A task's right-click menu, grouped like a desktop taskbar's: the application's own
    actions (its .desktop file's), New window; the window commands; Send to desktop N for
    every other Frametop screen; Pin to taskbar; Close. Window commands act on all of the
    task's windows."""
    wins = task.get("windows") or []
    n = len(wins)
    groups: list[list[dict[str, Any]]] = []
    launch = [{"id": "act:" + a["id"], "label": a["name"]} for a in actions]
    if can_launch and not any(a["name"].strip().lower() == "new window" for a in actions):
        launch.append({"id": "new", "label": "New window" if wins else "Open"})
    groups.append(launch)
    if wins:
        every = lambda k: all(w.get(k) for w in wins)  # noqa: E731
        groups.append([
            {"id": "min", "label": "Restore" if every("minimized") else "Minimize"},
            {"id": "max", "label": "Restore size" if every("maximized") else "Maximize"},
            {"id": "above", "label": "Keep above others", "active": every("above")},
            {"id": "full", "label": "Fullscreen", "active": every("fullscreen")},
        ])
        here = {w.get("output") for w in wins}
        groups.append([{"id": f"send:{i + 1}", "label": f"Send to desktop {i + 1}"}
                       for i, name in enumerate(output_order(outputs))
                       if not (len(here) == 1 and name in here)])
    if task.get("desktop_id"):
        groups.append([{"id": "pin", "label": "Unpin from taskbar" if task.get("pinned") else "Pin to taskbar"}])
    if wins:
        groups.append([{"id": "close", "label": f"Close all {n} windows" if n > 1 else "Close window"}])
    width = 400
    y = PAD + HEADER_H
    items = []
    for g in [g for g in groups if g]:
        if items:
            y += MENU_GAP
        for r in g:
            items.append(dict({"kind": "row"}, **r, **rect(PAD, y, width - 2 * PAD, MENU_ROW_H)))
            y += MENU_ROW_H + 4
    return {"w": width, "h": y - 4 + PAD, "header": task.get("name") or "Window", "items": items}


# ---------------------------------------------------------------- providers (parsing only)

def parse_wpctl_volume(text: str) -> tuple[float, bool]:
    """`wpctl get-volume` -> (level 0..1.5, muted)."""
    m = re.search(r"Volume:\s*([0-9.]+)", text or "")
    return (float(m.group(1)) if m else 0.0, "[MUTED]" in (text or ""))


def parse_wpctl_description(text: str) -> str:
    m = re.search(r'node\.description\s*=\s*"([^"]*)"', text or "")
    if m:
        return m.group(1)
    m = re.search(r'node\.nick\s*=\s*"([^"]*)"', text or "")
    return m.group(1) if m else ""


def volume_glyph_level(level: float, muted: bool) -> int:
    """Tray glyph state: 0 muted / silent, 1..3 waves."""
    if muted or level <= 0.005:
        return 0
    return 1 if level < 0.34 else 2 if level < 0.67 else 3


def signal_bars(strength: int) -> int:
    """NetworkManager strength 0..100 -> 0..4 bars."""
    s = max(0, min(100, int(strength)))
    return 0 if s < 5 else 1 if s < 30 else 2 if s < 55 else 3 if s < 80 else 4


def merge_networks(aps: list[dict[str, Any]], known_ssids: set[str], active_ssid: str) -> list[dict[str, Any]]:
    """Access points -> one row per SSID (strongest), active first, then by strength."""
    best: dict[str, dict[str, Any]] = {}
    for ap in aps:
        ssid = ap.get("ssid") or ""
        if not ssid:
            continue
        cur = best.get(ssid)
        if cur is None or ap.get("strength", 0) > cur["strength"]:
            best[ssid] = {"ssid": ssid, "strength": int(ap.get("strength", 0)), "secure": bool(ap.get("secure")),
                          "key": re.sub(r"[^A-Za-z0-9_.-]", "_", ssid)[:24] + "_" +
                                 format(zlib.crc32(ssid.encode()) & 0xFFFF, "04x")}
    out = []
    for n in best.values():
        n["bars"] = signal_bars(n["strength"])
        n["known"] = n["ssid"] in known_ssids
        n["active"] = n["ssid"] == active_ssid
        out.append(n)
    out.sort(key=lambda n: (not n["active"], -n["strength"], n["ssid"].lower()))
    return out


def network_click(net: dict[str, Any]) -> str:
    """activate (known), connect-open (no password needed), or settings (needs a secret:
    never asked for here)."""
    if net.get("known"):
        return "activate"
    if not net.get("secure"):
        return "connect-open"
    return "settings"


# ---------------------------------------------------------------- wire formats

def wire_id(s: str) -> str:
    """Item / task ids travel as single whitespace-free tokens (percent-encoded)."""
    return urllib.parse.quote(s, safe=":._-/@+")


def items_text(kind: str, serial: int, layout: dict[str, Any], metres: float) -> str:
    """popup.txt for ft-screens: header line, then one `item id x y w h` per hit rect."""
    lines = [f"popup {kind} {serial} {layout['w']} {layout['h']} {metres:.4f}"]
    for it in layout["items"]:
        if it.get("enabled", True) is False:
            continue
        lines.append(f"item {wire_id(it['id'])} {it['x']} {it['y']} {it['w']} {it['h']}")
    return "\n".join(lines) + "\n"


def tasks_text(serial: int, tasks: list[dict[str, Any]], icons: dict[str, str]) -> str:
    """tasks.txt for ft-screens: one tab-separated line per task."""
    lines = [f"tasks {serial} {len(tasks)}"]
    for t in tasks:
        lines.append("\t".join([
            "task", wire_id(t["id"]), "1" if t["pinned"] else "0", str(len(t["windows"])),
            "1" if t["focused"] else "0", icons.get(t["id"], ""), (t["name"] or "").replace("\t", " ")[:80],
        ]))
    return "\n".join(lines) + "\n"
