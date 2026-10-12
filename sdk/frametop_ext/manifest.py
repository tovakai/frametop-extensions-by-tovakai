"""Metadata-only manifest validation. NEVER execute an entrypoint during discovery."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

ID_RE = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
CAP_RE = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+$")
VALID_STATUSES = {"planned", "prototype", "experimental", "stable"}


class ManifestError(ValueError):
    """An extension's metadata is malformed or unsafe."""


@dataclass(frozen=True)
class ExtensionManifest:
    manifest_version: int
    id: str
    name: str
    version: str
    description: str
    status: str
    min_extension_api: int
    required_capabilities: tuple[str, ...]
    optional_capabilities: tuple[str, ...]
    entrypoint: str
    directory: Path


def load_manifest(path: Path) -> ExtensionManifest:
    path = Path(path)
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestError(f"{path}: {exc}") from exc
    if not isinstance(source, dict):
        raise ManifestError(f"{path}: expected a JSON object")
    if type(source.get("manifest_version")) is not int or source["manifest_version"] != 1:
        raise ManifestError(f"{path}: unsupported manifest_version")
    identity = source.get("id")
    if not isinstance(identity, str) or not ID_RE.fullmatch(identity):
        raise ManifestError(f"{path}: invalid extension id")
    name, version = source.get("name"), source.get("version")
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ManifestError(f"{path}: invalid name")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ManifestError(f"{path}: invalid version")
    status = source.get("status")
    if status not in VALID_STATUSES:
        raise ManifestError(f"{path}: invalid status")
    api = source.get("min_extension_api")
    if type(api) is not int or api < 1 or api > 100:
        raise ManifestError(f"{path}: invalid min_extension_api")
    entry = source.get("entrypoint")
    if not isinstance(entry, str) or not entry or "\\" in entry or "\x00" in entry:
        raise ManifestError(f"{path}: invalid entrypoint")
    relative = Path(entry)
    if relative.is_absolute() or ".." in relative.parts or entry in (".", "./"):
        raise ManifestError(f"{path}: unsafe entrypoint")
    # Metadata only. A manager must still verify installation/execution policies.
    root = path.parent.resolve()
    if not (root / relative).resolve().is_relative_to(root):
        raise ManifestError(f"{path}: entrypoint escapes extension directory")
    if not (root / relative).is_file():
        raise ManifestError(f"{path}: missing entrypoint")
    capabilities = []
    for key in ("required_capabilities", "optional_capabilities"):
        items = source.get(key)
        if not isinstance(items, list) or any(
            not isinstance(item, str) or not CAP_RE.fullmatch(item) for item in items
        ) or len(set(items)) != len(items):
            raise ManifestError(f"{path}: invalid {key}")
        capabilities.append(tuple(items))
    description = source.get("description", "")
    if not isinstance(description, str):
        raise ManifestError(f"{path}: invalid description")
    return ExtensionManifest(
        1, identity, name, version, description, status,
        api, capabilities[0], capabilities[1], entry, root
    )


def discover_manifests(root: Path) -> list[ExtensionManifest]:
    """Discover extension metadata, with no scripts run or files written."""
    root = Path(root)
    seen: set[str] = set()
    results = []
    for path in sorted(root.glob("*/extension.json")):
        manifest = load_manifest(path)
        if manifest.id in seen:
            raise ManifestError(f"duplicate extension id: {manifest.id}")
        seen.add(manifest.id)
        results.append(manifest)
    return results
