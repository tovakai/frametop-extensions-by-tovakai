#!/usr/bin/env python3
"""Headless Frametop Extension Manager, for device testing and recovery.

Works without Qt or an active desktop. Sources and package metadata are
untrusted; installed entrypoints are NEVER run automatically.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk"))
from frametop_ext import Frametop  # noqa: E402
from manager_core import Manager, ManagerError  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("catalog", "sources", "installed", "info"):
        sub.add_parser(name)
    add = sub.add_parser("add-source", help="clone user-approved GitHub repository")
    add.add_argument("url")
    remove = sub.add_parser("remove-source", help="remove source; keep installed snapshots")
    remove.add_argument("source")
    refresh = sub.add_parser("refresh", help="explicitly pull source's Git checkout")
    refresh.add_argument("source")
    for command in ("plan", "install"):
        p = sub.add_parser(command)
        p.add_argument("id")
        p.add_argument("--source", default="")
    uninstall = sub.add_parser("uninstall")
    uninstall.add_argument("id")
    for command in ("enable", "disable"):
        p = sub.add_parser(command, help="metadata selection ONLY; no autostart")
        p.add_argument("id")
    args = parser.parse_args(argv)
    manager = Manager(client=Frametop())
    try:
        if args.command == "catalog":
            output = manager.catalog()
            for p in output:
                p["compatibility"] = manager.compatibility(p)
        elif args.command == "sources":
            output = manager.sources()
        elif args.command == "installed":
            output = manager.installed_items()
        elif args.command == "info":
            try:
                ft = Frametop()
                output = {"api": ft.api_version(), "capabilities": sorted(ft.capabilities())}
            except Exception as e:
                output = {"api": None, "status": str(e)}
        elif args.command == "add-source":
            output = manager.add_source(args.url)
        elif args.command == "remove-source":
            manager.remove_source(args.source)
            output = {"removed": args.source}
        elif args.command == "refresh":
            output = manager.refresh(args.source)
        elif args.command == "plan":
            output = manager.plan(args.id, args.source)
        elif args.command == "install":
            output = {"installed": [p["id"] for p in manager.install(args.id, args.source)]}
        elif args.command == "uninstall":
            manager.uninstall(args.id)
            output = {"uninstalled": args.id}
        elif args.command in ("enable", "disable"):
            manager.enable(args.id, args.command == "enable")
            output = {"id": args.id, "enabled": args.command == "enable",
                      "note": "metadata only: no entrypoint or background service launched"}
        else:
            raise ManagerError("unknown command")
        if args.json or isinstance(output, (list, dict)):
            print(json.dumps(output, indent=2, default=str))
        else:
            print(output)
        return 0
    except (ManagerError, OSError, ValueError) as exc:
        print(f"extension-manager: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
