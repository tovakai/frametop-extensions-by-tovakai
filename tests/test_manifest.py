import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdk"))
from frametop_ext.manifest import ManifestError, discover_manifests, load_manifest  # noqa: E402


class ManifestTest(unittest.TestCase):
    def test_discover_metadata_only(self):
        manifests = discover_manifests(ROOT / "plugins")
        self.assertEqual({m.id for m in manifests}, {"tovakai.spatial-profiles", "tovakai.spatial-room"})
        room = next(m for m in manifests if m.id == "tovakai.spatial-room")
        self.assertEqual(room.status, "prototype")
        self.assertEqual(room.required_capabilities, ())
        item = next(m for m in manifests if m.id == "tovakai.spatial-profiles")
        self.assertEqual(item.id, "tovakai.spatial-profiles")
        self.assertEqual(item.status, "experimental")
        self.assertEqual(item.version, "0.1.0")
        self.assertEqual(item.min_extension_api, 1)
        self.assertIn("screen.move", item.required_capabilities)

    def test_reject_traversal_and_invalid_capabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            plugin = folder / "extension.json"
            (folder / "runner.py").write_text("print('would execute')\n")
            valid = {
                "manifest_version": 1, "id": "demo.testing",
                "name": "Test", "version": "1.2.3",
                "status": "prototype", "min_extension_api": 1,
                "required_capabilities": ["screen.move"],
                "optional_capabilities": [], "entrypoint": "runner.py",
            }
            plugin.write_text(json.dumps(valid))
            self.assertEqual(load_manifest(plugin).id, "demo.testing")
            for patch in (
                {"entrypoint": "../runner.py"},
                {"entrypoint": "/tmp/runner.py"},
                {"version": "latest"},
                {"required_capabilities": ["screen.move", "screen.move"]},
                {"min_extension_api": False},
                {"id": "Invalid ID"},
            ):
                bad = {**valid, **patch}
                plugin.write_text(json.dumps(bad))
                with self.subTest(patch=patch), self.assertRaises(ManifestError):
                    load_manifest(plugin)

    def test_reading_manifests_does_not_execute_entrypoint(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "demo"
            folder.mkdir()
            (folder / "runner.py").write_text(
                "from pathlib import Path\nPath(__file__).with_suffix('.ran').touch()\n")
            (folder / "extension.json").write_text(json.dumps({
                "manifest_version": 1, "id": "demo.testing",
                "name": "Test", "version": "0.0.1",
                "status": "prototype", "min_extension_api": 1,
                "required_capabilities": [], "optional_capabilities": [],
                "entrypoint": "runner.py",
            }))
            self.assertEqual(len(discover_manifests(folder.parent)), 1)
            self.assertFalse((folder / "runner.ran").exists())


if __name__ == "__main__":
    unittest.main()
