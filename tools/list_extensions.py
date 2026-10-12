#!/usr/bin/env python3
"""Display extension manifest metadata. Does not import or execute any plugins."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))

from frametop_ext.manifest import ManifestError, discover_manifests  # noqa: E402


def main() -> int:
    try:
        manifests = discover_manifests(ROOT / "plugins")
    except ManifestError as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 1
    if not manifests:
        print("No extension manifests found")
    for plugin in manifests:
        print(f"{plugin.id} v{plugin.version} [{plugin.status}] - {plugin.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
