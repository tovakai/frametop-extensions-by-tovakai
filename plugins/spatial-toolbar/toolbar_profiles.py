"""Bridge from the preserved legacy toolbar Displays menu to Spatial Profiles v0.1.

This is a model/controller adapter, not a rendered VR overlay yet. Existing
toolbar popups use the same layout coordinates and item kinds as the original.
Spatial Profiles never imports or depends on the toolbar.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Callable

HERE = Path(__file__).resolve().parent
PROFILES_DIR = HERE.parent / "spatial-profiles"
SDK_DIR = HERE.parents[1] / "sdk"
sys.path.insert(0, str(PROFILES_DIR))
sys.path.insert(0, str(SDK_DIR))

import ft_taskbar_model as legacy_model  # noqa: E402
import spatial_runtime as profiles  # noqa: E402
from frametop_ext import Frametop  # noqa: E402


def displays_popup(store_path: Path = profiles.DEFAULT_STORE) -> dict:
    """Return the *original* Displays popup geometry, bound to independent profiles.

    Profile rows, cyan active state and 1..6 slot badges keep their original
    layout. Only the legacy 'Display Settings…' footer is replaced: that
    action edited upstream layout state, not our extension.
    """
    store = profiles.read_store(store_path)
    layout = legacy_model.profiles_layout(
        sorted(store["profiles"], key=str.casefold),
        store["current"] or "",
        store["slots"],
    )
    for item in layout["items"]:
        if item["id"] == "settings":
            item.update({
                "id": "capture",
                "label": "Save current arrangement",
                "kind": "row",
            })
    return layout


def _next_name(store: dict) -> str:
    """Stable names until a proper popup text-entry/rename control is ported."""
    for number in range(1, 10000):
        name = f"Arrangement {number}"
        if name not in store["profiles"]:
            return name
    raise profiles.ProfileError("too many unnamed arrangements")


def activate(item_id: str, store_path: Path = profiles.DEFAULT_STORE,
             client_factory: Callable[[], Frametop] = Frametop,
             duration_ms: int = profiles.DEFAULT_DURATION) -> str:
    """Handle a user-triggered Displays popup item, never execute arbitrary text.

    Call only from actual click/confirm events. This module never starts a
    compositor, activates on import, or runs a plugin's arbitrary commands.
    """
    if not isinstance(item_id, str):
        raise profiles.ProfileError("invalid toolbar item identifier")
    store_path = Path(store_path)
    if item_id == "capture":
        store = profiles.read_store(store_path)
        name = _next_name(store)
        profiles.save_current(store_path, name, client_factory())
        return f"saved {name}"
    if item_id.startswith("profile:"):
        name = item_id[len("profile:"):]
        store = profiles.read_store(store_path)
        if name not in store["profiles"]:
            raise profiles.ProfileError(f"no saved arrangement named {name!r}")
        profiles.switch(store_path, name, client_factory(), duration_ms)
        return f"switched {name}"
    if item_id in {"none", "settings", ""}:
        raise profiles.ProfileError("toolbar item is not actionable")
    raise profiles.ProfileError(f"unsupported toolbar item: {item_id!r}")


def state_json(store_path: Path = profiles.DEFAULT_STORE) -> str:
    """Inspection output useful before the independent OpenVR surface is built."""
    return json.dumps(displays_popup(store_path), indent=2)
