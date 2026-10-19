#!/usr/bin/env python3
"""Opt-in live stereo preview controller; requires matching Frametop core branch.

No model inference or background daemon. Does not modify system settings.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk"))
from frametop_ext import ExtensionError, Frametop  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="FrameDepth diagnostic stereo preview")
    parser.add_argument("--control", default="ft_screens", help="Frametop abstract control socket")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-api", help="check for matching stereo preview capability")
    status = sub.add_parser("status", help="read preview state for a desktop screen")
    status.add_argument("screen", type=int)
    enable = sub.add_parser("on", help="enable brightness-based FAKE depth for one screen")
    enable.add_argument("screen", type=int)
    enable.add_argument("--strength", type=float, default=0.006, help="0..0.03")
    enable.add_argument("--convergence", type=float, default=0.5, help="0..1")
    enable.add_argument("--swap", action="store_true", help="reverse the left/right shift")
    disable = sub.add_parser("off", help="restore ordinary 2D for one screen")
    disable.add_argument("screen", type=int)
    args = parser.parse_args()

    client = Frametop(control=args.control)
    try:
        if args.command == "check-api":
            client._require_stereo_preview()
            print("ok: screen.stereo.preview available (live rendering NOT verified)")
        elif args.command == "status":
            state = client.stereo_preview_state(args.screen)
            print(" ".join(f"{key}={value}" for key, value in state.items()))
        elif args.command == "on":
            client.stereo_preview(args.screen, args.strength, args.convergence, args.swap)
            print(f"ok: diagnostic preview enabled for screen {args.screen}")
        elif args.command == "off":
            client.stereo_preview_off(args.screen)
            print(f"ok: screen {args.screen} returned to 2D")
    except (ExtensionError, ValueError) as exc:
        parser.exit(1, f"frame-depth: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
