#!/usr/bin/env python3
"""Standalone legacy KWin task feed: never modifies Frametop session/core.

KWinTasks scripting body and window operations are preserved from the old
ft-taskbar provider. Only our private D-Bus service and snapshot output differ.
Run this helper on the SteamOS HOST with the nested KWin session bus.
"""
from __future__ import annotations
import json
import os
import signal
import socket
import urllib.parse
import sys
import tempfile
from pathlib import Path

import gi
gi.require_version("GLib", "2.0")
from gi.repository import GLib

import ft_desktop
import ft_taskbar_model as model
try:
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
except ImportError:
    dbus=None

RUN=os.environ.get("FT_TOOLBAR_RUNTIME") or f"/run/user/{os.getuid()}/frametop-spatial-toolbar"
KWIN_SCRIPT="tovakai-spatial-toolbar"
def log(*args):
    print("toolbar-tasks:", *args, file=sys.stderr, flush=True)
def write_atomic(path, source):
    path=Path(path)
    fd,temp=tempfile.mkstemp(prefix=".tasks-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            stream.write(source)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

class KWinTasks:
    """Windows from the nested KWin: a persistent KWin script pushes JSON to us."""

    SCRIPT = r"""
function maximized(w) {
  // KWin 6.2 scripting has setMaximize but no maximizeMode: compare with the work area.
  try {
    var a = workspace.clientArea(KWin.MaximizeArea, w), g = w.frameGeometry;
    return g.width >= a.width - 1 && g.height >= a.height - 1;
  } catch (e) { return false; }
}
function info(w) {
  return {id: w.internalId.toString(), caption: w.caption, cls: w.resourceClass,
          desktop: w.desktopFileName, minimized: w.minimized, output: w.output ? w.output.name : "",
          maximized: maximized(w), above: w.keepAbove, fullscreen: w.fullScreen};
}
function push() {
  var list = [], ws = workspace.windowList();
  for (var i = 0; i < ws.length; ++i) {
    var w = ws[i];
    if (!w.normalWindow || w.skipTaskbar) continue;
    list.push(info(w));
  }
  var a = workspace.activeWindow;
  callDBus("org.tovakai.SpatialToolbar", "/Tasks", "org.tovakai.SpatialToolbar", "Update",
           JSON.stringify({windows: list, active: a ? a.internalId.toString() : "",
                           outputs: workspace.screens.map(function (o) { return o.name; })}));
}
function hook(w) {
  var sigs = ["captionChanged", "minimizedChanged", "outputChanged", "keepAboveChanged",
              "fullScreenChanged", "maximizedChanged"];
  for (var i = 0; i < sigs.length; ++i) if (w[sigs[i]]) w[sigs[i]].connect(push);
}
if (workspace.screensChanged) workspace.screensChanged.connect(push);
workspace.windowAdded.connect(function (w) { hook(w); push(); });
workspace.windowRemoved.connect(push);
workspace.windowActivated.connect(push);
var all = workspace.windowList();
for (var i = 0; i < all.length; ++i) hook(all[i]);
push();
"""

    def __init__(self, on_change):
        self.on_change = on_change
        self.windows, self.active, self.outputs = [], "", []
        self.bus = None
        self.ok = False
        self._oneshot = 0
        if dbus is None:
            log("python3-dbus missing: no running tasks")
            return
        try:
            self.bus = dbus.SessionBus()
            self._name = dbus.service.BusName("org.tovakai.SpatialToolbar", self.bus)
            parent = self

            class Tasks(dbus.service.Object):
                @dbus.service.method("org.tovakai.SpatialToolbar", in_signature="s", out_signature="")
                def Update(self, payload):  # noqa: N802 — D-Bus method name
                    parent._update(str(payload))

            self._obj = Tasks(self.bus, "/Tasks")
        except Exception as e:  # noqa: BLE001
            log("session bus:", e)
            return
        self.load()
        GLib.timeout_add_seconds(10, self._watchdog)

    def _scripting(self):
        return dbus.Interface(self.bus.get_object("org.kde.KWin", "/Scripting"), "org.kde.kwin.Scripting")

    def _run_script(self, source, name):
        path = os.path.join(RUN, name + ".js")
        write_atomic(path, source)
        scripting = self._scripting()
        if scripting.isScriptLoaded(name):
            scripting.unloadScript(name)
        # KWin exports loadScript(s) and loadScript(ss); introspection alone picks (s).
        sid = int(scripting.loadScript(path, name, signature="ss"))
        script = self.bus.get_object("org.kde.KWin", f"/Scripting/Script{sid}")
        dbus.Interface(script, "org.kde.kwin.Script").run()

    def load(self):
        try:
            self._run_script(self.SCRIPT, KWIN_SCRIPT)
            self.ok = True
            log("KWin task script loaded")
        except Exception as e:  # noqa: BLE001 — KWin may still be starting
            self.ok = False
            log("KWin script:", e)

    def _watchdog(self):
        try:
            if not self._scripting().isScriptLoaded(KWIN_SCRIPT):
                self.load()
        except Exception:  # noqa: BLE001
            self.ok = False
        return True

    def _update(self, payload):
        try:
            data = json.loads(payload)
        except ValueError:
            return
        self.windows = data.get("windows") or []
        self.active = data.get("active") or ""
        self.outputs = data.get("outputs") or []
        self.on_change()

    # JavaScript run once for every listed window, as `w` (one-shot KWin scripts).
    OPS = {
        "activate": "w.minimized = false; workspace.activeWindow = w;",
        "minimize": "w.minimized = true;",
        "maximize": "w.minimized = false; w.setMaximize(true, true);",
        "unmaximize": "w.setMaximize(false, false);",
        "above": "w.keepAbove = true;",
        "unabove": "w.keepAbove = false;",
        "fullscreen": "w.minimized = false; w.fullScreen = true;",
        "unfullscreen": "w.fullScreen = false;",
        "close": "w.closeWindow();",
        # arg: the output's name
        "send": "for (var j = 0; j < workspace.screens.length; ++j) "
                "if (workspace.screens[j].name == arg) workspace.sendClientToScreen(w, workspace.screens[j]);",
    }

    def window_op(self, op, win_ids, arg=""):
        if not self.bus or not win_ids:
            return
        self._oneshot += 1
        name = f"tovakai-toolbar-op-{self._oneshot % 4}"
        src = (f"var ids = {json.dumps([str(i) for i in win_ids])}, arg = {json.dumps(str(arg))};\n"
               "var ws = workspace.windowList();\n"
               "for (var i = 0; i < ws.length; ++i) {\n"
               "  var w = ws[i];\n"
               "  if (ids.indexOf(w.internalId.toString()) < 0) continue;\n"
               f"  {self.OPS[op]}\n"
               "}\n")
        try:
            self._run_script(src, name)
        except Exception as e:  # noqa: BLE001
            log(op + ":", e)
        GLib.timeout_add(800, self._unload, name)

    def activate(self, win_id):
        """Raise + focus one window (un-minimizing it)."""
        self.window_op("activate", [win_id])

    def _unload(self, name):
        try:
            self._scripting().unloadScript(name)
        except Exception:  # noqa: BLE001
            pass
        return False

    def shutdown(self):
        if self.bus:
            self._unload(KWIN_SCRIPT)



def main():
    if dbus is None:
        log("python3-dbus is missing; running-task icons unavailable")
        return 1
    DBusGMainLoop(set_as_default=True)
    runtime=Path(RUN)
    runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
    def notify():
        payload={
            "windows":kwin.windows,
            "active":kwin.active,
            "outputs":kwin.outputs
        }
        write_atomic(runtime/"tasks.json",json.dumps(payload,ensure_ascii=False))
    kwin=KWinTasks(notify)
    if not kwin.bus:
        log("Could not reach nested KWin D-Bus session")
        return 1
    notify()
    # The original provider is retained for KWin window events. Our toolbar
    # sends only a verified running task ID; no shell or script is accepted.
    sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
    sock.bind(b"\0tovakai_toolbar_tasks")
    sock.setblocking(False)
    def on_commands(_fd,_condition):
        while True:
            try:
                message=sock.recv(2048).decode("utf-8","replace")
            except BlockingIOError:
                return True
            except OSError:
                return True
            if not message.startswith("task "):
                continue
            task_id=urllib.parse.unquote(message[5:].strip())
            try:
                items=model.merge_tasks([],kwin.windows,ft_desktop.list_applications(),kwin.active)
                task=next((t for t in items if t["id"]==task_id),None)
                if not task:
                    continue
                action,arg=model.task_click(task)
                if action=="focus":
                    kwin.activate(arg)
                elif action=="minimize":
                    kwin.window_op("minimize",[arg])
                elif action=="expose" and task["windows"]:
                    kwin.activate(task["windows"][0]["id"])
                elif action=="launch" and arg:
                    with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as launch:
                        launch.sendto(("desktop "+arg).encode(),b"\0frametop_launch")
            except Exception as exc:
                log("task activation failed:",exc)
    GLib.io_add_watch(sock.fileno(),GLib.IO_IN,on_commands)
    loop=GLib.MainLoop()
    def shutdown(*_):
        kwin.shutdown()
        sock.close()
        loop.quit()
        return False
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGINT,shutdown)
    log("standalone KWin task feed attached; source from legacy ft-taskbar")
    loop.run()
    return 0
if __name__=="__main__":
    raise SystemExit(main())
