"""Standalone Frametop Extension Manager backend.

Catalogs/installs *files*, never executes downloaded extension code or modifies
the Frametop compositor. Only user-approved install/update operations copy files.
External repositories are user-selected and may contain untrusted Python/native
code: installing them is NOT a sandbox.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from frametop_ext.manifest import ID_RE, ManifestError, discover_manifests, load_manifest

DEFAULT_REPOSITORY = Path(__file__).resolve().parents[2]
CONFIG = Path.home() / ".config" / "frametop" / "extension-manager.json"
DATA = Path.home() / ".local" / "share" / "frametop" / "extension-manager"
INSTALLED = Path.home() / ".local" / "share" / "frametop" / "extensions"
URL_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:)"
    r"([A-Za-z0-9][A-Za-z0-9_.-]{0,98})/"
    r"([A-Za-z0-9][A-Za-z0-9_.-]{0,98})(?:\.git)?/?$"
)
MAX_FILES = 3000
MAX_BYTES = 150 * 1024 * 1024
MAX_SINGLE = 50 * 1024 * 1024
OMIT = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


class ManagerError(RuntimeError):
    pass


def validate_url(url: str) -> str:
    """Only GitHub repositories are accepted in v0.1 (no local/file/host injection)."""
    url = url.strip()
    if not URL_RE.fullmatch(url):
        raise ManagerError("Use a GitHub HTTPS or SSH repository URL (github.com/owner/repo)")
    return url.rstrip("/")


def _atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".manager-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _metadata(manifest):
    return {
        "id": manifest.id, "name": manifest.name, "version": manifest.version,
        "description": manifest.description, "status": manifest.status,
        "min_extension_api": manifest.min_extension_api,
        "required_capabilities": list(manifest.required_capabilities),
        "entrypoint": manifest.entrypoint,
    }


def _dependencies(manifest):
    """Optional additive manifest field; validated but not yet part of SDK dataclass."""
    file = manifest.directory / "extension.json"
    obj = json.loads(file.read_text(encoding="utf-8"))
    items = obj.get("dependencies", [])
    if not isinstance(items, list) or len(items) != len(set(str(x) for x in items)):
        raise ManagerError(f"{manifest.id}: dependencies must be unique IDs")
    for item in items:
        if not isinstance(item, str) or not ID_RE.fullmatch(item) or item == manifest.id:
            raise ManagerError(f"{manifest.id}: invalid dependency {item!r}")
    return items


def _check_safe_tree(tree: Path):
    """Reject symlinks, special files, excessive payloads and hidden Git metadata."""
    if not tree.is_dir() or tree.is_symlink():
        raise ManagerError(f"unsafe plugin source: {tree}")
    total = count = 0
    for root, dirs, files in os.walk(tree, followlinks=False):
        dirs[:] = [d for d in dirs if d not in OMIT]
        for d in dirs:
            if (Path(root) / d).is_symlink():
                raise ManagerError(f"symlink directory disallowed: {d}")
        for file in files:
            p = Path(root) / file
            if p.is_symlink() or not p.is_file():
                raise ManagerError(f"symlink/special file disallowed: {p}")
            n = p.stat().st_size
            total += n
            count += 1
            if n > MAX_SINGLE or total > MAX_BYTES or count > MAX_FILES:
                raise ManagerError("plugin exceeds safety limits (150 MiB / 3000 files)")
    return total, count


def _git(*args: str, cwd: Path | None = None):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}
    try:
        p = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True,
                           text=True, check=False, timeout=150)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ManagerError(f"Git unavailable or timed out: {exc}") from exc
    if p.returncode:
        raise ManagerError((p.stderr or p.stdout or "Git failed").strip()[:900])
    return p.stdout.strip()


class Manager:
    """Pure stdlib package manager with explicit source and install operations."""

    def __init__(self, repository: Path = DEFAULT_REPOSITORY, config: Path = CONFIG,
                 data: Path = DATA, installed: Path = INSTALLED, client=None):
        self.repository = Path(repository).expanduser().resolve()
        self.config = Path(config).expanduser()
        self.data = Path(data).expanduser()
        self.installed = Path(installed).expanduser()
        self.client = client

    def _default(self):
        return {
            "schema": 1,
            "sources": [{
                "id": "tovakai",
                "name": "Tovakai Extensions",
                "url": "https://github.com/tovakai/frametop-extensions-by-tovakai",
                "path": str(self.repository),
                "builtin": True,
            }],
            "installed": {},
        }

    def read(self):
        try:
            obj = json.loads(self.config.read_text(encoding="utf-8"))
        except FileNotFoundError:
            obj = self._default()
        except (OSError, ValueError) as exc:
            raise ManagerError(f"Invalid manager settings: {exc}") from exc
        if not isinstance(obj, dict) or obj.get("schema") != 1:
            raise ManagerError("Unsupported manager config version")
        if not isinstance(obj.get("sources"), list) or not isinstance(obj.get("installed"), dict):
            raise ManagerError("Malformed extension manager config")
        found = set()
        for source in obj["sources"]:
            if not isinstance(source, dict) or not {"id", "name", "path", "url", "builtin"} <= set(source):
                raise ManagerError("Malformed repository source")
            if not isinstance(source["id"], str) or not re.fullmatch(r"[a-z0-9-]{1,64}", source["id"]):
                raise ManagerError("Invalid repository source identifier")
            if source["id"] in found or not isinstance(source["builtin"], bool):
                raise ManagerError("Duplicate or invalid repository source")
            found.add(source["id"])
            validate_url(source["url"])
        for identity, item in obj["installed"].items():
            if not ID_RE.fullmatch(identity) or not isinstance(item, dict) or not {
                "source", "version", "enabled", "directory",
            } <= set(item):
                raise ManagerError("Invalid installed extension record")
        return obj

    @contextmanager
    def _lock(self):
        self.config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(str(self.config) + ".lock", "a+", encoding="utf-8") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(file, fcntl.LOCK_UN)

    def _save(self, obj):
        _atomic_json(self.config, obj)

    def sources(self):
        return self.read()["sources"]

    def add_source(self, url: str):
        url = validate_url(url)
        source_id = "repo-" + hashlib.sha256(url.encode()).hexdigest()[:14]
        with self._lock():
            state = self.read()
            if any(s["url"] == url for s in state["sources"]):
                raise ManagerError("Repository is already configured")
            if any(s["id"] == source_id for s in state["sources"]):
                raise ManagerError("Repository ID collision")
            dest = self.data / "sources" / source_id
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if dest.exists():
                raise ManagerError("Managed checkout already exists")
            # Clone into a sibling temporary path, so failures never create a
            # half-configured source or hide an existing directory.
            tmp = Path(tempfile.mkdtemp(prefix=".source-", dir=dest.parent))
            try:
                tmp.rmdir()
                _git("clone", "--depth", "1", "--", url, str(tmp))
                # No source hooks or scripts are executed by this manager.
                if not (tmp / "plugins").is_dir():
                    raise ManagerError("Repository has no plugins/ catalog")
                discover_manifests(tmp / "plugins")
                tmp.rename(dest)
            finally:
                if tmp.exists():
                    shutil.rmtree(tmp)
            source = {
                "id": source_id, "name": url.rsplit("/", 1)[-1].removesuffix(".git"),
                "url": url, "path": str(dest), "builtin": False,
            }
            state["sources"].append(source)
            self._save(state)
        return source

    def remove_source(self, source_id: str):
        with self._lock():
            state = self.read()
            source = next((s for s in state["sources"] if s["id"] == source_id), None)
            if source is None:
                raise ManagerError("Unknown repository")
            if source["builtin"]:
                raise ManagerError("The built-in catalog cannot be removed")
            state["sources"] = [s for s in state["sources"] if s["id"] != source_id]
            self._save(state)
            # Installed plugin snapshots remain intact even when a source is removed.
            managed = self.data / "sources" / source_id
            if Path(source["path"]).resolve() == managed.resolve() and managed.is_dir():
                shutil.rmtree(managed)

    def refresh(self, source_id: str):
        with self._lock():
            state = self.read()
            source = next((s for s in state["sources"] if s["id"] == source_id), None)
            if source is None:
                raise ManagerError("Unknown repository")
            path = Path(source["path"])
            if path.is_symlink() or not (path / ".git").exists():
                raise ManagerError("Repository checkout missing or not a Git checkout")
            # Explicit refresh only: never pulls during listing or manager startup.
            _git("pull", "--ff-only", cwd=path)
            discover_manifests(path / "plugins")
            return source

    def catalog(self):
        state = self.read()
        items = []
        for source in state["sources"]:
            root = Path(source["path"])
            if not root.is_dir():
                raise ManagerError(f"Missing repository checkout: {root}")
            try:
                plugins = discover_manifests(root / "plugins")
            except (ManifestError, OSError) as exc:
                raise ManagerError(f"{source['name']}: {exc}") from exc
            for manifest in plugins:
                detail = _metadata(manifest)
                detail["dependencies"] = _dependencies(manifest)
                detail["source"] = source["id"]
                detail["repository"] = source["name"]
                detail["installed"] = manifest.id in state["installed"]
                installed = state["installed"].get(manifest.id, {})
                detail["installed_version"] = installed.get("version", "")
                detail["installed_source"] = installed.get("source", "")
                detail["enabled"] = bool(installed.get("enabled", False))
                items.append(detail)
        return sorted(items, key=lambda x: (x["name"].casefold(), x["source"]))

    def compatibility(self, meta: dict):
        if self.client is None:
            return "unknown (desktop/API not queried)"
        try:
            ver = self.client.api_version()
            caps = self.client.capabilities()
        except Exception:
            return "unknown (Frametop isn't running)"
        if ver < meta["min_extension_api"]:
            return f"requires API {meta['min_extension_api']}"
        missing = set(meta["required_capabilities"]) - set(caps)
        if missing:
            return "missing " + ", ".join(sorted(missing))
        return "compatible"

    def plan(self, identity: str, source_id: str = ""):
        """Read-only; validate dependencies and show exact packages to install."""
        catalog = self.catalog()
        matches = [p for p in catalog if p["id"] == identity and
                   (not source_id or p["source"] == source_id)]
        if not matches:
            raise ManagerError(f"Extension not found: {identity}")
        if len(matches) > 1:
            raise ManagerError("Extension exists in multiple repos; specify its source")
        target = matches[0]
        lookup = {p["id"]: [] for p in catalog}
        for p in catalog:
            lookup[p["id"]].append(p)
        installed = self.read()["installed"]
        order = []
        visited = set()
        active = set()

        def walk(plugin):
            pid = plugin["id"]
            if pid in active:
                raise ManagerError("Circular plugin dependency")
            if pid in visited:
                return
            active.add(pid)
            for dep in plugin["dependencies"]:
                if dep in installed:
                    continue
                choices = lookup.get(dep, [])
                if len(choices) != 1:
                    raise ManagerError(f"Dependency {dep} missing or ambiguous across sources")
                walk(choices[0])
            active.remove(pid)
            visited.add(pid)
            order.append(plugin)

        walk(target)
        return order

    def _stage(self, meta, source, stage):
        """Copy only the requested extension, plus the source's SDK if present.

        Maintaining plugins/<slug>/... and sdk/... preserves the existing
        runtime's relative import paths when installed independently.
        """
        root = Path(source["path"])
        manifest = next(
            (m for m in discover_manifests(root / "plugins") if m.id == meta["id"]),
            None,
        )
        if manifest is None or manifest.version != meta["version"]:
            raise ManagerError("Catalog changed; refresh and review again")
        rel = manifest.directory.relative_to(root)
        if len(rel.parts) != 2 or rel.parts[0] != "plugins":
            raise ManagerError("Only plugins/<slug>/extension.json packages supported")
        _check_safe_tree(manifest.directory)
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(manifest.directory, target,
                        ignore=shutil.ignore_patterns(*OMIT))
        sdk = root / "sdk"
        if sdk.is_dir():
            _check_safe_tree(sdk)
            shutil.copytree(sdk, stage / "sdk",
                            ignore=shutil.ignore_patterns(*OMIT))
        check = load_manifest(target / "extension.json")
        if check.id != manifest.id or check.version != manifest.version:
            raise ManagerError("Copied manifest identity/version mismatch")
        return str(rel)

    def install(self, identity: str, source_id: str = ""):
        """Install approved extension + dependencies, DISABLED. No code is run."""
        with self._lock():
            state = self.read()
            order = self.plan(identity, source_id)
            for meta in order:
                pid = meta["id"]
                old = state["installed"].get(pid)
                if old and old["source"] != meta["source"]:
                    raise ManagerError(f"{pid} was installed from a different source")
                source = next(s for s in state["sources"] if s["id"] == meta["source"])
                self.installed.mkdir(parents=True, exist_ok=True, mode=0o700)
                stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=self.installed))
                dest = self.installed / pid
                backup = self.installed / (".backup-" + pid)
                moved = False
                try:
                    rel = self._stage(meta, source, stage)
                    if backup.exists():
                        raise ManagerError(f"Old backup exists; inspect {backup}")
                    if dest.exists():
                        dest.rename(backup)
                        moved = True
                    stage.rename(dest)
                    state["installed"][pid] = {
                        "source": source["id"], "version": meta["version"],
                        "directory": rel, "enabled": old["enabled"] if old else False,
                    }
                    self._save(state)
                    if backup.exists():
                        shutil.rmtree(backup)
                except Exception:
                    if dest.exists() and moved:
                        shutil.rmtree(dest)
                        backup.rename(dest)
                    elif not dest.exists() and moved and backup.exists():
                        backup.rename(dest)
                    raise
                finally:
                    if stage.exists():
                        shutil.rmtree(stage)
            return order

    def uninstall(self, identity: str):
        with self._lock():
            state = self.read()
            if identity not in state["installed"]:
                raise ManagerError("Extension is not installed")
            # Refuse to orphan installed dependents.
            for meta in self.catalog():
                if (meta["installed"] and meta["id"] != identity and
                        identity in meta["dependencies"]):
                    raise ManagerError(f"Uninstall blocked: required by {meta['id']}")
            target = self.installed / identity
            if not target.is_dir() or target.is_symlink():
                raise ManagerError("Installed files missing/unsafe; refusing to delete")
            tomb = self.installed / (".remove-" + identity)
            if tomb.exists():
                raise ManagerError("Prior removal backup exists")
            target.rename(tomb)
            try:
                del state["installed"][identity]
                self._save(state)
            except Exception:
                tomb.rename(target)
                raise
            shutil.rmtree(tomb)

    def enable(self, identity: str, enabled: bool):
        """Opt-in state only. Explicitly NOT a process supervisor or auto-run."""
        with self._lock():
            state = self.read()
            if identity not in state["installed"]:
                raise ManagerError("Extension is not installed")
            if enabled:
                # Protect against enabling a broken/missing dependency.
                installed_ids = set(state["installed"])
                manifest = load_manifest(
                    self.installed / identity / state["installed"][identity]["directory"] /
                    "extension.json")
                for dep in _dependencies(manifest):
                    if dep not in installed_ids or not state["installed"][dep]["enabled"]:
                        raise ManagerError(f"Enable dependency {dep} first")
                result = self.compatibility(_metadata(manifest))
                if result not in ("compatible",) and not result.startswith("unknown"):
                    raise ManagerError(result)
            state["installed"][identity]["enabled"] = bool(enabled)
            self._save(state)

    def installed_items(self):
        return copy.deepcopy(self.read()["installed"])
