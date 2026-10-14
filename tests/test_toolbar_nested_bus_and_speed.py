"""Standalone toolbar's nested KWin bus discovery and shared app catalog."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"plugins/spatial-toolbar"))
import nested_bus
import ui_runtime


class NestedBusTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.proc=self.root/"proc"
        self.proc.mkdir()
        self.host=self.root/"runtime"
        (self.host/"frametop").mkdir(parents=True)

    def fake_process(self, pid, name, runtime, bus):
        path=self.proc/str(pid)
        path.mkdir()
        (path/"comm").write_text(name+"\n")
        (path/"environ").write_bytes((
            f"XDG_RUNTIME_DIR={runtime}\0"
            f"DBUS_SESSION_BUS_ADDRESS={bus}\0"
            "WAYLAND_DISPLAY=wayland-1\0"
            "PRIVATE_CREDENTIAL=secret-do-not-copy\0"
        ).encode())
        return path

    def discover(self):
        return nested_bus.discover(proc_root=self.proc,uid=os.getuid(),
                                   host_runtime=self.host)

    def test_ignores_host_and_uses_unique_nested_bus(self):
        self.fake_process(101,"kwin_wayland",str(self.host),"unix:path=/host/bus")
        self.fake_process(102,"kwin_wayland",str(self.host/"frametop"),
                          "unix:path=/tmp/private-nested-bus")
        self.fake_process(103,"plasmashell",str(self.host/"frametop"),
                          "unix:path=/tmp/private-nested-bus")
        found=self.discover()
        self.assertEqual(found["DBUS_SESSION_BUS_ADDRESS"],
                         "unix:path=/tmp/private-nested-bus")
        self.assertEqual(found["XDG_RUNTIME_DIR"],str(self.host/"frametop"))
        self.assertEqual(found["WAYLAND_DISPLAY"],"wayland-1")
        self.assertNotIn("PRIVATE_CREDENTIAL",found)

    def test_refuses_ambiguous_or_missing_private_session(self):
        self.fake_process(102,"kwin_wayland",str(self.host/"frametop"),
                          "unix:path=/tmp/nested-one")
        self.fake_process(103,"plasmashell",str(self.host/"frametop"),
                          "unix:path=/tmp/nested-two")
        with self.assertRaisesRegex(nested_bus.NestedSessionError,
                                    "uniquely discover"):
            self.discover()
        (self.proc/"103"/"environ").unlink()
        self.assertEqual(self.discover()["DBUS_SESSION_BUS_ADDRESS"],
                         "unix:path=/tmp/nested-one")

    def test_refuses_a_host_bus_even_when_only_process(self):
        self.fake_process(101,"kwin_wayland",str(self.host),"unix:path=/host/bus")
        with self.assertRaises(nested_bus.NestedSessionError):
            self.discover()


class CatalogCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime=Path(self.tmp.name)

    def test_subprocess_shared_app_cache_refresh_and_permissions(self):
        calls=[]
        def enumerate_apps():
            calls.append(1)
            return [{"id":"org.example.Editor","name":"Editor","categories":["Utility"]}]
        with patch.object(ui_runtime.ft_desktop,"list_applications",side_effect=enumerate_apps):
            first=ui_runtime.cached_apps(self.runtime)
            second=ui_runtime.cached_apps(self.runtime)
            self.assertEqual(first,second)
            self.assertEqual(len(calls),1)
            path=self.runtime/"app-catalog.json"
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            stale=time.time()-120
            os.utime(path,(stale,stale))
            ui_runtime.cached_apps(self.runtime)
            self.assertEqual(len(calls),2)

    def test_corrupt_cache_falls_back_to_scan(self):
        (self.runtime/"app-catalog.json").write_text("{bad")
        with patch.object(ui_runtime.ft_desktop,"list_applications",return_value=[]):
            self.assertEqual(ui_runtime.cached_apps(self.runtime),[])

    def test_start_state_remains_fully_roundtrippable(self):
        ui_runtime.set_start_state(self.runtime,"Game",3)
        self.assertEqual(ui_runtime.get_start_state(self.runtime),("Game",3))


if __name__=="__main__":
    unittest.main()
