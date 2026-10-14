"""Identify a running task's icon beyond the Start-menu desktop catalog.

The legacy model matches normal app windows to Start's list of .desktop
entries. Steam/Flatpak/AppImage/nested KWin windows may supply a valid desktop
file name, but be hidden by OnlyShowIn or have a different WM_CLASS. We keep
the original matching model and only *enrich icon candidates* for these cases.
No processes are launched, no core session files are read or changed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _unique(values):
    seen = set()
    output = []
    for item in values:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        output.append(name)
    return output


def _stem(value: str) -> str:
    name = str(value or "").strip()
    if not name:
        return ""
    if name.lower().endswith(".desktop"):
        name = name[:-8]
    return name


def icon_candidates(task: dict[str, Any], raw_windows: list[dict[str, Any]],
                    desktop_lookup=None) -> list[str]:
    """Candidates from desktop icon, real KWin desktop ID and resource class.

    For a window without a match in the Start catalog, consult the *actual*
    .desktop file by KWin desktopFileName. This retrieves Icon= even for a
    NoDisplay/OnlyShowIn app. Fall back to appropriately named theme icons.
    """
    possible = [task.get("icon", "")]
    desktop = task.get("desktop_id") or ""
    if desktop:
        possible.append(_stem(desktop))
    for window in raw_windows:
        identifier = window.get("desktop") or ""
        cls = window.get("cls") or ""
        if desktop_lookup and identifier:
            info = desktop_lookup(identifier)
            if info:
                possible.append(info.get("icon", ""))
        possible.extend((_stem(identifier), cls, _stem(cls)))
        # Some vendors ship only com.vendor.App icons, while KWin publishes
        # "App" or com.vendor.App.desktop. Try both full and short IDs.
        if identifier and not identifier.startswith("/"):
            possible.append(_stem(identifier).split(".")[-1])
    return _unique(possible)


def task_sources(tasks: list[dict], windows: list[dict], desktop_lookup=None) -> list[dict]:
    """Add display-only candidates to existing task dictionaries."""
    by_id = {str(w.get("id", "")): w for w in windows}
    for task in tasks:
        related = [by_id[str(w.get("id", ""))]
                   for w in task.get("windows", [])
                   if str(w.get("id", "")) in by_id]
        task["icon_candidates"] = icon_candidates(task, related, desktop_lookup)
    return tasks
