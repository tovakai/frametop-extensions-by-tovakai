#!/usr/bin/env python3
"""Read-only legacy spatial-profile inspector. No install, migration or live changes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk"))
from frametop_ext import ExtensionError, Frametop  # noqa: E402

DEFAULT_PROFILES = Path.home() / ".config" / "frametop-layout-profiles.json"
SLOT_COUNT = 6
DEFAULT_TRANSITION_MS = 450
SPATIAL_FIELDS = {
    "pos", "face", "roll", "metres", "curve", "pin", "opacity",
    "active_opacity", "idle_opacity", "attention", "follow_deadzone",
    "hidden", "dock",
}


class ProfileError(ValueError):
    """Malformed, missing or incompatible profile store."""


def read_store(path: Path) -> dict:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProfileError(f"could not read {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        raise ProfileError("expected a JSON object containing a 'profiles' object")
    profiles = data["profiles"]
    if not all(isinstance(k, str) and isinstance(v, dict) for k, v in profiles.items()):
        raise ProfileError("each profile must be a named object")
    for name, profile in profiles.items():
        screens = profile.get("screens")
        if not isinstance(screens, list) or not screens or not all(
            isinstance(s, dict) for s in screens
        ):
            raise ProfileError(f"profile {name!r}: screens must be a non-empty list of objects")
    current = data.get("current")
    if current is not None and (not isinstance(current, str) or current not in profiles):
        raise ProfileError("current profile does not exist")
    slots = data.get("slots", [None] * SLOT_COUNT)
    if not isinstance(slots, list) or len(slots) != SLOT_COUNT:
        raise ProfileError("expected exactly six spatial profile slots")
    if any(x is not None and (not isinstance(x, str) or x not in profiles) for x in slots):
        raise ProfileError("slot references an unknown profile")
    return {"current": current, "profiles": profiles, "slots": slots}


def profile_summary(profile: dict) -> dict:
    screens = profile["screens"]
    out = []
    for number, data in enumerate(screens, 1):
        pin = data.get("pin")
        anchor = (pin.get("anchor") or pin.get("hand")) if isinstance(pin, dict) else None
        out.append({
            "screen": number,
            "anchor": anchor or "world",
            "position": data.get("pos"),
            "face": data.get("face"),
            "width_metres": data.get("metres"),
            "curve": data.get("curve"),
            "active_opacity": data.get("active_opacity", data.get("opacity")),
            "idle_opacity": data.get("idle_opacity"),
            "gaze_attention": bool(data.get("attention", {}).get("enabled", False))
                if isinstance(data.get("attention"), dict) else False,
            "hidden": bool(data.get("hidden", False)),
            "follow_deadzone": data.get("follow_deadzone"),
            "docked": bool(data.get("dock", {}).get("docked", False))
                if isinstance(data.get("dock"), dict) else False,
            "unknown_fields": sorted(set(data) - SPATIAL_FIELDS),
        })
    return {
        "screens": out,
        "instruments": len(profile.get("instruments") or []),
        "toolbar": "toolbar" in profile,
        "transition_default_ms": DEFAULT_TRANSITION_MS,
    }


def migration_plan(profile: dict) -> dict:
    """Describe gaps without doing lossy conversion or changing live state."""
    summary = profile_summary(profile)
    capabilities = set()
    blockers = []
    for screen in summary["screens"]:
        number = screen["screen"]
        if screen["position"] is not None:
            capabilities.add("screen.move")
            blockers.append(f"screen {number}: stored pose is head-relative; needs a live HMD transform")
        if screen["active_opacity"] is not None:
            capabilities.add("screen.opacity")
        if screen["anchor"] != "world":
            blockers.append(f"screen {number}: {screen['anchor']} follow/pin needs an anchoring API")
        if screen["gaze_attention"] or screen["idle_opacity"] is not None:
            blockers.append(f"screen {number}: gaze-driven opacity needs a gaze-target feed")
        if screen["docked"]:
            blockers.append(f"screen {number}: toolbar docking API not available")
    if summary["instruments"]:
        blockers.append("spatial instruments require an overlay/attachment extension API")
    if summary["toolbar"]:
        blockers.append("toolbar state requires an independently running toolbar extension")
    return {
        **summary,
        "api_capabilities": sorted(capabilities),
        "migration_blockers": blockers,
        "ready_to_apply": False,  # Explicitly no apply implementation yet.
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_PROFILES,
                        help="read-only path to old frametop-layout-profiles.json")
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list", help="list stored spatial profiles and six slots")
    p_list.add_argument("--json", action="store_true")
    p_show = sub.add_parser("show", help="inspect a profile, without applying it")
    p_show.add_argument("name")
    p_plan = sub.add_parser("plan", help="inspect supported fields and migration blockers")
    p_plan.add_argument("name")
    sub.add_parser("check-api", help="query the live Frametop extension API (optional)")
    args = parser.parse_args(argv)
    try:
        if args.command == "check-api":
            client = Frametop()
            print(json.dumps({"api": client.api_version(),
                              "capabilities": sorted(client.capabilities())}, indent=2))
            return 0
        store = read_store(args.file)
        if args.command == "list":
            if args.json:
                print(json.dumps({
                    "current": store["current"],
                    "profiles": sorted(store["profiles"]),
                    "slots": store["slots"],
                }, indent=2))
            else:
                for name in sorted(store["profiles"]):
                    print(name + (" *" if name == store["current"] else ""))
                print("slots: " + ", ".join(f"{n+1}={x or '-'}"
                                          for n, x in enumerate(store["slots"])))
            return 0
        if args.name not in store["profiles"]:
            raise ProfileError(f"no spatial profile named {args.name!r}")
        profile = store["profiles"][args.name]
        report = profile_summary(profile) if args.command == "show" else migration_plan(profile)
        print(json.dumps({"name": args.name, **report}, indent=2))
        return 0
    except (ProfileError, ExtensionError) as exc:
        print(f"spatial-profiles: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
