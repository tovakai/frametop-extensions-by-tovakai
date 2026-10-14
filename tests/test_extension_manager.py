"""Offline safety and lifecycle checks for the standalone settings app manager."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))
sys.path.insert(0, str(ROOT / "apps" / "extension-manager"))
from manager_core import Manager, ManagerError, validate_url  # noqa: E402


class FakeCompositor:
    def __init__(self, caps=("screen.status", "screen.move", "screen.opacity")):
        self.caps = set(caps)

    def api_version(self):
        return 1

    def capabilities(self):
        return self.caps


def plugin(root, slug, identity, requires=(), depends=(), version="0.1.0"):
    folder = root / "plugins" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.py").write_text(
        "from pathlib import Path\n"
        "Path('/tmp/extension-manager-entrypoint-ran').touch()\n",
        encoding="utf-8",
    )
    (folder / "extension.json").write_text(json.dumps({
        "manifest_version": 1,
        "id": identity,
        "name": "Test " + slug,
        "version": version,
        "description": "Test source; do not run entrypoint",
        "status": "experimental",
        "min_extension_api": 1,
        "required_capabilities": list(requires),
        "optional_capabilities": [],
        "entrypoint": "run.py",
        "dependencies": list(depends),
    }), encoding="utf-8")
    return folder


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "upstream_repo"
        self.repo.mkdir()
        (self.repo / "sdk" / "frametop_ext").mkdir(parents=True)
        (self.repo / "sdk" / "frametop_ext" / "__init__.py").write_text("# sdk\n")
        plugin(self.repo, "alpha", "demo.alpha", requires=("screen.move",))
        plugin(self.repo, "beta", "demo.beta", depends=("demo.alpha",))
        self.config = self.root / "config" / "manager.json"
        self.data = self.root / "data"
        self.installed = self.root / "installed"
        self.mgr = Manager(repository=self.repo, config=self.config,
                           data=self.data, installed=self.installed,
                           client=FakeCompositor())

    def test_default_catalog_is_built_in_and_read_only(self):
        self.assertEqual(self.mgr.sources()[0]["id"], "tovakai")
        self.assertEqual(self.mgr.sources()[0]["path"], str(self.repo))
        items = self.mgr.catalog()
        self.assertEqual({p["id"] for p in items}, {"demo.alpha", "demo.beta"})
        self.assertFalse(self.config.exists())
        self.assertFalse(self.installed.exists())
        self.assertEqual(self.mgr.compatibility(items[0]), "compatible")

    def test_install_is_disabled_by_default_and_runs_no_plugin_code(self):
        poison = Path("/tmp/extension-manager-entrypoint-ran")
        # Test uses a fixture that WOULD write to a global temp file if run;
        # none of the manager operations should import/execute the entrypoint.
        poison.unlink(missing_ok=True)
        result = self.mgr.install("demo.alpha", "tovakai")
        self.assertEqual([x["id"] for x in result], ["demo.alpha"])
        items = self.mgr.installed_items()
        self.assertFalse(items["demo.alpha"]["enabled"])
        self.assertTrue((self.installed / "demo.alpha" / "plugins" /
                         "alpha" / "run.py").is_file())
        self.assertTrue((self.installed / "demo.alpha" / "sdk" /
                         "frametop_ext" / "__init__.py").is_file())
        self.assertFalse(poison.exists())
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.mgr.uninstall("demo.alpha")
        self.assertFalse((self.installed / "demo.alpha").exists())
        self.assertFalse(poison.exists())

    def test_dependencies_installed_in_order_and_do_not_auto_enable(self):
        plan = self.mgr.plan("demo.beta")
        self.assertEqual([x["id"] for x in plan], ["demo.alpha", "demo.beta"])
        self.mgr.install("demo.beta")
        items = self.mgr.installed_items()
        self.assertEqual(set(items), {"demo.alpha", "demo.beta"})
        self.assertFalse(items["demo.alpha"]["enabled"])
        with self.assertRaisesRegex(ManagerError, "Enable dependency"):
            self.mgr.enable("demo.beta", True)
        self.mgr.enable("demo.alpha", True)
        self.mgr.enable("demo.beta", True)
        self.assertTrue(self.mgr.installed_items()["demo.beta"]["enabled"])
        with self.assertRaisesRegex(ManagerError, "required by"):
            self.mgr.uninstall("demo.alpha")
        self.mgr.uninstall("demo.beta")
        self.mgr.uninstall("demo.alpha")

    def test_reinstall_updates_snapshot_and_preserves_selection(self):
        self.mgr.install("demo.alpha")
        self.mgr.enable("demo.alpha", True)
        plugin(self.repo, "alpha", "demo.alpha", version="0.2.0")
        self.mgr.install("demo.alpha")
        items = self.mgr.installed_items()
        self.assertEqual(items["demo.alpha"]["version"], "0.2.0")
        self.assertTrue(items["demo.alpha"]["enabled"])
        self.assertFalse((self.installed / ".backup-demo.alpha").exists())
        # Install does not alter core source files.
        self.assertTrue((self.repo / "plugins/alpha/extension.json").exists())

    def test_reject_unsafe_symlinks_before_copy(self):
        (self.repo / "plugins" / "alpha" / "secret-link").symlink_to("/etc/passwd")
        with self.assertRaisesRegex(ManagerError, "symlink"):
            self.mgr.install("demo.alpha")
        self.assertFalse((self.installed / "demo.alpha").exists())
        self.assertFalse(self.config.exists())

    def test_reject_invalid_dependencies_and_id_ambiguity(self):
        manifest = self.repo / "plugins" / "beta" / "extension.json"
        data = json.loads(manifest.read_text())
        data["dependencies"] = ["demo.beta"]
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ManagerError, "invalid dependency"):
            self.mgr.catalog()

    def test_bad_source_urls_cannot_be_git_command_options_or_file_urls(self):
        for url in (
            "--upload-pack=/tmp/evil", "file:///tmp/evil", "/tmp/repo",
            "ssh://example.com/any", "https://evil.org/test/repo",
            "https://github.com/owner/repo;whoami", "http://github.com/x/y",
        ):
            with self.subTest(url=url), self.assertRaises(ManagerError):
                validate_url(url)
        self.assertEqual(validate_url("git@github.com:somebody/plugins.git"),
                         "git@github.com:somebody/plugins.git")
        self.assertEqual(validate_url("https://github.com/owner/extensions"),
                         "https://github.com/owner/extensions")

    def test_cannot_remove_builtin_source(self):
        with self.assertRaisesRegex(ManagerError, "cannot be removed"):
            self.mgr.remove_source("tovakai")
        self.assertFalse(self.config.exists())

    def test_failure_copy_leaves_state_untouched(self):
        self.mgr.install("demo.alpha")
        before = self.config.read_bytes()
        dest = self.installed / "demo.alpha"
        source = self.repo / "plugins/alpha"
        (source / "badlink").symlink_to("/etc/passwd")
        with self.assertRaises(ManagerError):
            self.mgr.install("demo.alpha")
        self.assertEqual(self.config.read_bytes(), before)
        self.assertTrue(dest.is_dir())

    def test_no_cross_source_overwrite(self):
        self.mgr.install("demo.alpha")
        state = self.mgr.read()
        state["installed"]["demo.alpha"]["source"] = "other-source"
        self.mgr._save(state)
        with self.assertRaisesRegex(ManagerError, "different source"):
            self.mgr.install("demo.alpha")

    def test_installation_metadata_requires_consent_and_is_not_running(self):
        self.mgr.install("demo.alpha")
        selected = self.mgr.installed_items()["demo.alpha"]
        self.assertFalse(selected["enabled"])
        self.assertFalse((self.root / "systemd").exists())

    def test_invalid_config_never_overwritten(self):
        self.config.parent.mkdir()
        self.config.write_text('{"schema":99}')
        with self.assertRaises(ManagerError):
            self.mgr.install("demo.alpha")
        self.assertEqual(self.config.read_text(), '{"schema":99}')

    def test_user_desktop_installer_is_reversible(self):
        installer = ROOT / "apps" / "extension-manager" / "install.sh"
        self.assertTrue(installer.exists())
        home = self.root / "home"
        home.mkdir()
        env = {**os.environ, "HOME": str(home)}
        p = subprocess.run(["bash", str(installer), "install"], capture_output=True,
                           text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        entry = home / ".local/share/applications/frametop-extension-manager.desktop"
        self.assertIn("Categories=Settings;System;", entry.read_text())
        self.assertIn("X-Frametop-Extension-Manager=1", entry.read_text())
        self.assertNotIn("sudo ", installer.read_text())
        p = subprocess.run(["bash", str(installer), "uninstall"], capture_output=True,
                           text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(entry.exists())


if __name__ == "__main__":
    unittest.main()
