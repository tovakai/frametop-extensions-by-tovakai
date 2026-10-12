"""Frametop extension SDK (experimental; no automatic plugin execution)."""

from .client import ExtensionError, Frametop
from .manifest import ExtensionManifest, ManifestError, discover_manifests, load_manifest

__all__ = [
    "ExtensionError",
    "Frametop",
    "ExtensionManifest",
    "ManifestError",
    "discover_manifests",
    "load_manifest",
]
