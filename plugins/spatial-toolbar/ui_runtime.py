"""Existing toolbar models adapted to standalone start-menu and task overlays."""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import time
import tempfile
import urllib.parse

import ft_desktop
import ft_taskbar_model as model
import ft_toolbar
import task_icons



def _write_json_atomic(path: Path, value) -> None:
    """Owner-only metadata, no dependency on Cairo/Pango or the menu process."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix=".toolbar-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            os.fchmod(out.fileno(), 0o600)
            json.dump(value, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def cached_apps(runtime: Path, ttl: float = 60.) -> list[dict]:
    """Share the legacy FreeDesktop app scan across short-lived popup processes.

    Popup category clicks used to repeat the full icon/desktop-file discovery
    scan. The user-owned cache is time-bounded and only stores catalog metadata.
    Cache files cannot select executable paths or alter app launch validation:
    launching still goes through the existing Frametop launch service.
    """
    path = runtime / "app-catalog.json"
    try:
        if not path.is_symlink():
            stat = path.stat()
            if stat.st_size <= 4 * 1024 * 1024 and time.time() - stat.st_mtime < ttl:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list) and all(
                        isinstance(a, dict) and isinstance(a.get("id"), str)
                        for a in data):
                    return data
    except (OSError, ValueError, TypeError):
        pass
    apps = ft_desktop.list_applications()
    if not path.is_symlink():
        _write_json_atomic(path, apps)
    return apps


def tasks(runtime: Path) -> list[dict]:
    try:
        data = json.loads((runtime / "tasks.json").read_text(encoding="utf-8"))
        windows, active = data["windows"], data.get("active", "")
        if not isinstance(windows, list) or not isinstance(active, str):
            return []
        merged = model.merge_tasks([], windows, cached_apps(runtime), active)[:12]
        def find_icon_desktop(desktop_id):
            path = ft_desktop.find_desktop_by_id(desktop_id)
            return ft_desktop.read_desktop_entry(path) if path else None
        return task_icons.task_sources(merged, windows, find_icon_desktop)
    except (OSError, KeyError, TypeError, ValueError):
        # KWin feed isn't running yet, so show Start/Displays without false task tiles.
        return []


def groups(count: int) -> dict:
    # Layout comes directly from legacy ft_toolbar.py. There is no phantom Tray
    # or empty task tile; the actual interactive button count matches this model.
    return {
        "left": [{"type": "start"}] + ([{"type": "tasks", "count": count}] if count else []),
        "center": [],
        "right": [{"type": "displays"}],
    }


def button_positions(count: int):
    model_groups = groups(count)
    positions = ft_toolbar.button_local_x(model_groups)
    return ft_toolbar.toolbar_total_width(model_groups), positions


def get_start_state(runtime: Path) -> tuple[str, int]:
    try:
        obj = json.loads((runtime / "start-state.json").read_text(encoding="utf-8"))
        cat = str(obj.get("category") or "")[:80]
        page = max(0, min(1000, int(obj.get("page", 0))))
        return cat, page
    except (OSError, TypeError, ValueError):
        return "", 0


def set_start_state(runtime: Path, category: str, page: int):
    # The runtime directory is private and never accepts arbitrary paths.
    _write_json_atomic(runtime / "start-state.json", {
        "category": category, "page": page,
    })


def start_popup(runtime: Path):
    apps = cached_apps(runtime)
    category, page_number = get_start_state(runtime)
    page_apps, page, pages = model.start_page(apps, category, page_number)
    return model.start_layout(
        page_apps, model.start_categories(apps), category, page, pages, []
    )


def _launch_desktop(desktop_id: str):
    # Reuse the existing nested-desktop launch service rather than inheriting
    # the container's outer Wayland environment (which produces rogue windows).
    if not desktop_id or any(ch.isspace() or ch == "\0" for ch in desktop_id):
        raise ValueError("invalid desktop ID")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.bind(b"")
        sock.settimeout(2.0)
        sock.sendto(("desktop " + desktop_id).encode(), b"\0frametop_launch")
        reply = sock.recv(4096).decode("utf-8", "replace")
    if not reply.startswith("ok"):
        raise RuntimeError(f"ft-launch refused {desktop_id}: {reply}")


def activate(runtime: Path, kind: str, item: str) -> str:
    if kind == "start":
        if item.startswith("cat:"):
            cat = "" if item == "cat:all" else item[4:]
            valid = {c for _, c in model.start_categories(cached_apps(runtime))}
            if cat not in valid:
                raise ValueError("unknown Start category")
            set_start_state(runtime, cat, 0)
            return "refresh"
        if item in ("page:prev", "page:next"):
            cat, page = get_start_state(runtime)
            set_start_state(runtime, cat, max(0, page + (1 if item == "page:next" else -1)))
            return "refresh"
        if item.startswith("app:"):
            desktop_id = item[4:]
            # Confirm this ID is from the discovered desktop catalog.
            valid = {a["id"] for a in cached_apps(runtime)}
            if desktop_id not in valid:
                raise ValueError("unknown application")
            _launch_desktop(desktop_id)
            return "closed"
        raise ValueError(f"unsupported Start action: {item!r}")
    if kind == "profiles":
        import toolbar_profiles
        toolbar_profiles.activate(item)
        return "closed"
    if kind == "task":
        # Only task IDs from the current KWin feed are accepted.
        valid = {t["id"] for t in tasks(runtime)}
        if item not in valid:
            raise ValueError("unknown running task")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(("task " + model.wire_id(item)).encode(),
                        b"\0tovakai_toolbar_tasks")
        return "closed"
    raise ValueError(f"unsupported toolbar action: {kind}")
