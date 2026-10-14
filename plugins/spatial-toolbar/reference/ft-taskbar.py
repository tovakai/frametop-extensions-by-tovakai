#!/usr/bin/env python3
"""ft-taskbar: providers and popup renderer for the Frametop spatial toolbar.

Runs on the SteamOS host inside the nested session's D-Bus (started by
frametop-session.sh next to ft-launch). ft-screens keeps everything spatial (placement,
hit testing, hover, docking); this process owns what needs host libraries:

  tasks     the nested KWin's windows, through a KWin script that calls back over D-Bus
            (org.frametop.Taskbar /Tasks Update), merged with the pinned apps
            (layout toolbar.pinned_apps) — no process scraping
  start     installed applications (layout/ft_desktop.py), launched through ft-launch
  profiles  ft-layout's spatial profiles; switching runs `ft-layout profile apply`
  volume    the default PipeWire sink (wpctl; `pactl subscribe` for live changes)
  wifi      NetworkManager over the system bus (libnm); secured networks that are not
            saved yet go to the network settings — never a password prompt here

Wire (abstract datagram sockets):
  ft-screens -> @frametop_taskbar   hello | open KIND [ARG] | click KIND ID U V |
                                    scroll KIND DY | closed KIND | task ID
  ft-taskbar -> @ft_screens         toolbar popup KIND SERIAL | toolbar popup-close KIND |
                                    toolbar tasks SERIAL | toolbar tray volume LEVEL PCT |
                                    toolbar tray wifi ENABLED BARS CONNECTED
Files (shared with the container): /run/user/UID/frametop-taskbar/{popup.png,popup.txt,
tasks.txt,icons/}.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT_DIR = os.path.join(HERE, "..", "layout")
sys.path.insert(0, LAYOUT_DIR)
import ft_desktop  # noqa: E402
import ft_layout  # noqa: E402
import ft_taskbar_model as model  # noqa: E402

import gi  # noqa: E402

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import GLib, Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

try:
    gi.require_version("NM", "1.0")
    from gi.repository import NM  # noqa: E402
except (ImportError, ValueError):
    NM = None
try:
    import dbus  # noqa: E402
    import dbus.service  # noqa: E402
    from dbus.mainloop.glib import DBusGMainLoop  # noqa: E402
except ImportError:
    dbus = None

SOCK = b"\0frametop_taskbar"
SCREENS = b"\0ft_screens"
LAUNCH = b"\0frametop_launch"
FT_LAYOUT = os.path.join(LAYOUT_DIR, "ft-layout")
RUN = f"/run/user/{os.getuid()}/frametop-taskbar"
ICONS = os.path.join(RUN, "icons")
# The session's XDG_RUNTIME_DIR is the nested one; PipeWire lives in the host's.
AUDIO_ENV = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}")
KWIN_SCRIPT = "frametop-taskbar"
FONT = "Noto Sans"

# SteamVR gamepadui palette (same as the toolbar).
C_BG = (0x0E / 255, 0x14 / 255, 0x1B / 255)
C_ROW = (0x23 / 255, 0x26 / 255, 0x2E / 255)
C_BTN = (0x3D / 255, 0x44 / 255, 0x50 / 255)
C_ACCENT = (0x88 / 255, 0xCC / 255, 0xF1 / 255)
C_TEXT = (0xDC / 255, 0xDE / 255, 0xDF / 255)
C_DIM = (0x8B / 255, 0x92 / 255, 0x9A / 255)


def log(*a):
    print("ft-taskbar:", *a, file=sys.stderr, flush=True)


def write_atomic(path, data, mode="w"):
    tmp = path + ".tmp"
    with open(tmp, mode) as f:
        f.write(data)
    os.replace(tmp, path)


# ---------------------------------------------------------------- drawing

def rounded(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


def text(cr, s, x, y, w, size, color=C_TEXT, bold=False, align="left", h=None, lines=1):
    layout = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription(f"{FONT} {'Bold ' if bold else ''}{size}px")
    fd.set_absolute_size(size * Pango.SCALE)
    layout.set_font_description(fd)
    layout.set_text(s or "", -1)
    layout.set_width(int(w * Pango.SCALE))
    layout.set_ellipsize(Pango.EllipsizeMode.END)
    if lines > 1:
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_height(-lines)
    layout.set_alignment({"left": Pango.Alignment.LEFT, "center": Pango.Alignment.CENTER,
                          "right": Pango.Alignment.RIGHT}[align])
    _ink, logical = layout.get_pixel_extents()
    if h is not None:
        y += (h - logical.height) / 2
    cr.set_source_rgb(*color)
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, layout)


_icon_cache: dict[str, str] = {}


def icon_png(name):
    """A PNG for an icon name or path (cached under ICONS), or '' if none resolves."""
    if not name:
        return ""
    if name in _icon_cache:
        return _icon_cache[name]
    path = ""
    if os.path.isabs(name) and name.endswith(".png") and os.path.isfile(name):
        path = name
    else:
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[-80:]
        dest = os.path.join(ICONS, safe + ".png")
        if os.path.isfile(dest):
            path = dest
        else:
            try:
                path = ft_desktop.ensure_raster_icon(name, dest, prefer_size=128) or ""
                # ft-screens runs in the dev container, where host-only paths (Flatpak
                # exports symlink into /var/lib/flatpak/app) don't resolve: hand it a copy
                # in the runtime dir both sides share.
                if path and path != dest and path.lower().endswith(".png"):
                    shutil.copyfile(path, dest)
                    path = dest
            except Exception as e:  # noqa: BLE001 — a broken icon must not break the menu
                log("icon", name, e)
    _icon_cache[name] = path
    return path


def draw_icon(cr, path, x, y, size):
    try:
        img = cairo.ImageSurface.create_from_png(path)
    except Exception:  # noqa: BLE001
        return False
    w, h = img.get_width(), img.get_height()
    if w <= 0 or h <= 0:
        return False
    s = size / max(w, h)
    cr.save()
    cr.translate(x + (size - w * s) / 2, y + (size - h * s) / 2)
    cr.scale(s, s)
    cr.set_source_surface(img, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_GOOD)
    cr.paint()
    cr.restore()
    return True


def draw_bars(cr, x, y, h, bars, color):
    for i in range(4):
        bh = h * (i + 1) / 4
        cr.set_source_rgb(*(color if i < bars else C_BTN))
        rounded(cr, x + i * 9, y + h - bh, 6, bh, 2)
        cr.fill()


def draw_lock(cr, x, y, color):
    cr.set_source_rgb(*color)
    rounded(cr, x, y + 8, 14, 11, 2)
    cr.fill()
    cr.set_line_width(2.4)
    cr.arc(x + 7, y + 8, 4.5, 3.1416, 0)
    cr.stroke()


def render(layout, kind):
    w, h = layout["w"], layout["h"]
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    rounded(cr, 0, 0, w, h, 24)
    cr.set_source_rgba(*C_BG, 0.97)
    cr.fill()
    if layout.get("header"):
        text(cr, layout["header"], model.PAD + 4, model.PAD, w - 2 * model.PAD - 120, 24, bold=True)
    if layout.get("subtitle"):
        text(cr, layout["subtitle"], w - model.PAD - 200, model.PAD + 4, 196, 17, C_DIM, align="right")
    for it in layout["items"]:
        draw_item(cr, it, kind)
    surf.flush()
    return surf


def draw_item(cr, it, kind):
    x, y, w, h, k = it["x"], it["y"], it["w"], it["h"], it.get("kind")
    cr.new_path()  # Pango leaves a current point; arcs would otherwise join it with a line
    active = it.get("active", False)
    enabled = it.get("enabled", True)
    if k == "chip":
        rounded(cr, x, y, w, h, h / 2)
        cr.set_source_rgb(*(C_ACCENT if active else C_ROW))
        cr.fill()
        text(cr, it["label"], x, y, w, 17, C_BG if active else C_TEXT, bold=active, align="center", h=h)
    elif k == "app":
        icon = icon_png(it.get("icon"))
        if not (icon and draw_icon(cr, icon, x + (w - 60) / 2, y + 8, 60)):
            rounded(cr, x + (w - 60) / 2, y + 8, 60, 60, 14)
            cr.set_source_rgb(*C_BTN)
            cr.fill()
            text(cr, (it.get("label") or "?")[:1].upper(), x, y + 8, w, 30, bold=True, align="center", h=60)
        text(cr, it.get("label", ""), x + 2, y + 74, w - 4, 15, align="center", lines=2)
    elif k == "pin":
        cr.arc(x + w / 2, y + h / 2, 9, 0, 6.2832)
        if it.get("pinned"):
            cr.set_source_rgb(*C_ACCENT)
            cr.fill()
        else:
            cr.set_source_rgba(*C_DIM, 0.6)
            cr.set_line_width(2)
            cr.stroke()
    elif k == "nav":
        rounded(cr, x, y, w, h, 12)
        cr.set_source_rgb(*C_ROW)
        cr.fill()
        text(cr, it["label"], x, y, w, 30, C_TEXT if enabled else C_BTN, bold=True, align="center", h=h)
    elif k == "toggle":
        rounded(cr, x, y, w, h, 14)
        cr.set_source_rgb(*C_ROW)
        cr.fill()
        if w > 120:
            text(cr, it["label"], x + 18, y, w - 100, 19, h=h)
            sx, sw = x + w - 74, 56
        else:
            sx, sw = x + (w - 48) / 2, 48
        rounded(cr, sx, y + h / 2 - 13, sw, 26, 13)
        cr.set_source_rgb(*(C_ACCENT if active else C_BTN))
        cr.fill()
        kx = sx + (sw - 13 if active else 13)
        cr.arc(kx, y + h / 2, 10, 0, 6.2832)
        cr.set_source_rgb(*C_TEXT)
        cr.fill()
    elif k == "mute":
        rounded(cr, x, y, w, h, 14)
        cr.set_source_rgb(*C_ROW)
        cr.fill()
        cx, cy = x + w / 2 - 6, y + h / 2
        cr.set_source_rgb(*(C_DIM if active else C_TEXT))
        cr.move_to(cx - 12, cy - 6)
        cr.line_to(cx - 5, cy - 6)
        cr.line_to(cx + 4, cy - 14)
        cr.line_to(cx + 4, cy + 14)
        cr.line_to(cx - 5, cy + 6)
        cr.line_to(cx - 12, cy + 6)
        cr.close_path()
        cr.fill()
        cr.set_line_width(3)
        if active:
            cr.set_source_rgb(*C_ACCENT)
            cr.move_to(cx + 10, cy - 7)
            cr.line_to(cx + 22, cy + 7)
            cr.move_to(cx + 22, cy - 7)
            cr.line_to(cx + 10, cy + 7)
        else:
            cr.arc(cx + 6, cy, 10, -0.8, 0.8)
            cr.new_sub_path()
            cr.arc(cx + 6, cy, 17, -0.8, 0.8)
        cr.stroke()
    elif k == "slider":
        v = it.get("value", 0.0)
        ty = y + h / 2 - 5
        rounded(cr, x, ty, w, 10, 5)
        cr.set_source_rgb(*C_BTN)
        cr.fill()
        rounded(cr, x, ty, max(10, w * v), 10, 5)
        cr.set_source_rgb(*(C_DIM if it.get("muted") else C_ACCENT))
        cr.fill()
        cr.arc(x + w * v, y + h / 2, 14, 0, 6.2832)
        cr.set_source_rgb(*C_TEXT)
        cr.fill()
    elif k in ("network", "profile", "window", "row"):
        rounded(cr, x, y, w, h, 12)
        cr.set_source_rgb(*C_ROW)
        cr.fill()
        if active:
            rounded(cr, x, y + 10, 5, h - 20, 2.5)
            cr.set_source_rgb(*C_ACCENT)
            cr.fill()
        label_w = w - 36 - (90 if k in ("network", "profile") else 0)
        color = C_TEXT if enabled else C_DIM
        if k == "window" and it.get("minimized"):
            color = C_DIM
        text(cr, it.get("label", ""), x + 18, y, label_w, 19, color, bold=active, h=h)
        if k == "network":
            draw_bars(cr, x + w - 52, y + 14, h - 28, it.get("bars", 0), C_ACCENT if active else C_TEXT)
            if it.get("secure"):
                draw_lock(cr, x + w - 80, y + h / 2 - 11, C_DIM)
        if k == "profile" and it.get("badge"):
            rounded(cr, x + w - 50, y + 12, 32, h - 24, 8)
            cr.set_source_rgb(*C_BTN)
            cr.fill()
            text(cr, it["badge"], x + w - 50, y + 12, 32, 17, bold=True, align="center", h=h - 24)


# ---------------------------------------------------------------- providers

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
  callDBus("org.frametop.Taskbar", "/Tasks", "org.frametop.Taskbar", "Update",
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
            self._name = dbus.service.BusName("org.frametop.Taskbar", self.bus)
            parent = self

            class Tasks(dbus.service.Object):
                @dbus.service.method("org.frametop.Taskbar", in_signature="s", out_signature="")
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
        name = f"frametop-op-{self._oneshot % 4}"
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


class Volume:
    def __init__(self, on_change):
        self.on_change = on_change
        self.level, self.muted, self.device = 0.0, False, ""
        self._pending = False
        self.refresh()
        try:
            self.sub = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        env=AUDIO_ENV, text=True, bufsize=1)
            GLib.io_add_watch(self.sub.stdout, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, self._event)
        except OSError:
            self.sub = None
            GLib.timeout_add_seconds(2, self._poll)

    def _event(self, stream, cond):
        if cond & GLib.IO_HUP:
            GLib.timeout_add_seconds(2, self._poll)
            return False
        line = stream.readline()
        if ("sink" in line or "server" in line) and not self._pending:
            self._pending = True
            GLib.timeout_add(80, self._debounced)
        return True

    def _debounced(self):
        self._pending = False
        self.refresh()
        return False

    def _poll(self):
        self.refresh()
        return True

    def _wpctl(self, *args):
        try:
            return subprocess.run(["wpctl", *args], capture_output=True, text=True, env=AUDIO_ENV,
                                  timeout=2).stdout
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def refresh(self):
        level, muted = model.parse_wpctl_volume(self._wpctl("get-volume", "@DEFAULT_AUDIO_SINK@"))
        device = model.parse_wpctl_description(self._wpctl("inspect", "@DEFAULT_AUDIO_SINK@"))
        if (level, muted, device) != (self.level, self.muted, self.device):
            self.level, self.muted, self.device = level, muted, device
            self.on_change()

    def set_level(self, v):
        self._wpctl("set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{max(0.0, min(1.0, v)):.3f}")
        if self.muted:
            self._wpctl("set-mute", "@DEFAULT_AUDIO_SINK@", "0")
        self.refresh()

    def toggle_mute(self):
        self._wpctl("set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")
        self.refresh()


class Wifi:
    def __init__(self, on_change):
        self.on_change = on_change
        self.client = None
        self.networks: list[dict] = []
        self.enabled, self.bars, self.connected = False, 0, False
        if NM is None:
            log("libnm (gi NM) missing: no Wi-Fi")
            return
        try:
            self.client = NM.Client.new(None)
        except Exception as e:  # noqa: BLE001
            log("NetworkManager:", e)
            return
        for sig in ("notify::wireless-enabled", "notify::active-connections", "device-added", "device-removed"):
            self.client.connect(sig, lambda *_: self.refresh())
        GLib.timeout_add_seconds(5, lambda: (self.refresh(), True)[1])
        self.refresh()

    def device(self):
        if not self.client:
            return None
        for d in self.client.get_devices():
            if isinstance(d, NM.DeviceWifi):
                return d
        return None

    @staticmethod
    def _ssid(ap):
        b = ap.get_ssid()
        return NM.utils_ssid_to_utf8(b.get_data()) if b else ""

    def known(self):
        out = set()
        for c in self.client.get_connections() if self.client else []:
            s = c.get_setting_wireless()
            if s and s.get_ssid():
                out.add(NM.utils_ssid_to_utf8(s.get_ssid().get_data()))
        return out

    def refresh(self):
        try:
            self._refresh()
        except Exception as e:  # noqa: BLE001 — keep the bar alive if libnm misbehaves
            log("wifi refresh:", e)

    def _refresh(self):
        if not self.client:
            return
        dev = self.device()
        enabled = bool(self.client.wireless_get_enabled())
        aps, active_ssid, bars = [], "", 0
        if dev:
            act = dev.get_active_access_point()
            if act:
                active_ssid, bars = self._ssid(act), model.signal_bars(act.get_strength())
            for ap in dev.get_access_points():
                # NM_802_11_AP_FLAGS_PRIVACY = 0x1 (the enum's GI name starts with a digit).
                secure = bool(int(ap.get_flags()) & 0x1) or bool(int(ap.get_wpa_flags())) or \
                    bool(int(ap.get_rsn_flags()))
                aps.append({"ssid": self._ssid(ap), "strength": ap.get_strength(), "secure": secure,
                            "path": ap.get_path()})
        self._aps = aps
        networks = model.merge_networks(aps, self.known(), active_ssid)
        state = (enabled, bars, bool(active_ssid), [(n["ssid"], n["bars"], n["active"]) for n in networks])
        if state != getattr(self, "_state", None):
            self._state = state
            self.enabled, self.bars, self.connected, self.networks = enabled, bars, bool(active_ssid), networks
            self.on_change()

    def scan(self):
        dev = self.device()
        if dev:
            try:
                dev.request_scan_async(None, None, None)
            except Exception:  # noqa: BLE001 — scanning too often is refused; fine
                pass

    def set_enabled(self, on):
        if not self.client:
            return
        try:
            self.client.dbus_set_property(NM.DBUS_PATH, NM.DBUS_INTERFACE, "WirelessEnabled",
                                          GLib.Variant("b", bool(on)), -1, None, None, None)
        except Exception as e:  # noqa: BLE001
            log("wifi toggle:", e)

    def connect(self, net):
        """Saved network or an open one only; anything needing a secret goes to settings."""
        dev = self.device()
        action = model.network_click(net)
        if not dev or action == "settings":
            return False
        if action == "activate":
            for c in self.client.get_connections():
                s = c.get_setting_wireless()
                if s and s.get_ssid() and NM.utils_ssid_to_utf8(s.get_ssid().get_data()) == net["ssid"]:
                    self.client.activate_connection_async(c, dev, None, None, None, None)
                    return True
            return False
        for ap in self._aps:
            if ap["ssid"] == net["ssid"] and not ap["secure"]:
                self.client.add_and_activate_connection_async(None, dev, ap["path"], None, None, None)
                return True
        return False


# ---------------------------------------------------------------- the service

class Taskbar:
    def __init__(self):
        os.makedirs(ICONS, exist_ok=True)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(SOCK)
        self.sock.setblocking(False)
        GLib.io_add_watch(self.sock.fileno(), GLib.IO_IN, self._recv)
        self.popup = model.PopupState()
        self.serial = 0
        self.start_cat, self.start_page_n = "", 0
        self._apps = None
        self._tasks_text = ""
        self._tray_sent = {}
        self.tasks: list[dict] = []
        self.ready = False  # providers report their first state while being built
        self.kwin = KWinTasks(self.push_tasks)
        self.volume = Volume(self.on_volume)
        self.wifi = Wifi(self.on_wifi)
        self.ready = True
        GLib.timeout_add_seconds(60, self._forget_apps)
        self.push_tasks()
        self.push_tray(force=True)

    # --- wire
    def send(self, msg, dest=SCREENS):
        try:
            self.sock.sendto(msg.encode(), dest)
        except OSError:
            pass  # ft-screens not up yet; it says hello when it is

    def _recv(self, _fd, _cond):
        while True:
            try:
                data = self.sock.recv(8192)
            except BlockingIOError:
                return True
            except OSError:
                return True
            line = data.decode(errors="replace").strip()
            if not line or line.startswith(("ok", "error")):
                continue  # ft-screens' replies to our notifications
            try:
                self.handle(line)
            except Exception as e:  # noqa: BLE001 — one bad request must not stop the bar
                log("request", repr(line), e)

    def handle(self, line):
        f = line.split()
        cmd = f[0]
        if cmd == "hello":
            self._tasks_text = ""
            self.push_tasks()
            self.push_tray(force=True)
        elif cmd == "open" and len(f) >= 2:
            self.popup.kind, self.popup.arg = f[1], (urllib.parse.unquote(f[2]) if len(f) > 2 else "")
            if f[1] == "start":
                self.start_page_n = 0
                self._apps = None  # pick up newly installed .desktop files
            if f[1] == "wifi":
                self.wifi.scan()
            self.show_popup()
        elif cmd == "closed":
            self.popup.close("ft-screens")
        elif cmd == "scroll" and len(f) >= 3 and f[1] == "start":
            self.start_page_n += 1 if float(f[2]) < 0 else -1
            self.show_popup()
        elif cmd == "click" and len(f) >= 3:
            u = float(f[3]) if len(f) > 3 else 0.5
            self.click(f[1], urllib.parse.unquote(f[2]), u)
        elif cmd == "task" and len(f) >= 2:
            self.task_click(urllib.parse.unquote(f[1]))

    # --- popups
    def apps(self):
        if self._apps is None:
            try:
                self._apps = ft_desktop.list_applications()
            except OSError:
                self._apps = []
        return self._apps

    def _forget_apps(self):
        self._apps = None  # background refresh; Start open also clears the cache
        return True

    def pinned(self):
        return list((ft_layout.load_layout().get("toolbar") or {}).get("pinned_apps") or [])

    def build(self, kind, arg):
        if kind == "start":
            apps = self.apps()
            page, self.start_page_n, pages = model.start_page(apps, self.start_cat, self.start_page_n)
            return model.start_layout(page, model.start_categories(apps), self.start_cat, self.start_page_n,
                                      pages, self.pinned())
        if kind == "windows":
            task = next((t for t in self.tasks if t["id"] == arg), None)
            return model.windows_layout(task or {"name": "Windows", "windows": []})
        if kind == "taskmenu":
            task = self.task(arg) or {"name": "Window", "windows": []}
            return model.task_menu_layout(task, self.app_actions(task), self.kwin.outputs,
                                          bool(self.desktop_path(task)))
        if kind == "profiles":
            store = ft_layout.load_profiles()
            return model.profiles_layout(sorted(store.get("profiles") or {}), store.get("current") or "",
                                         store.get("slots") or {})
        if kind == "volume":
            return model.volume_layout(self.volume.level, self.volume.muted, self.volume.device)
        if kind == "wifi":
            return model.wifi_layout(self.wifi.enabled, self.wifi.networks)
        raise ValueError(kind)

    def show_popup(self):
        kind, arg = self.popup.kind, self.popup.arg
        if not kind:
            return
        layout = self.build(kind, arg)
        self._layout = layout
        surf = render(layout, kind)
        self.serial += 1
        surf.write_to_png(os.path.join(RUN, "popup.png.tmp"))
        os.replace(os.path.join(RUN, "popup.png.tmp"), os.path.join(RUN, "popup.png"))
        write_atomic(os.path.join(RUN, "popup.txt"),
                     model.items_text(kind, self.serial, layout, layout["w"] / model.PX_PER_M))
        self.send(f"toolbar popup {kind} {self.serial}")

    def close_popup(self):
        kind = self.popup.kind
        self.popup.close("action")
        if kind:
            self.send(f"toolbar popup-close {kind}")

    def launch(self, line):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            s.bind(b"")
            s.settimeout(3)
            s.sendto(line.encode(), LAUNCH)
            reply = s.recv(4096).decode(errors="replace")
            s.close()
            if not reply.startswith("ok"):
                log("launch", line, reply)
        except OSError as e:
            log("ft-launch:", e)

    def click(self, kind, item, u):
        if kind != self.popup.kind:
            return
        if kind == "start":
            if item.startswith("app:"):
                self.launch("desktop " + item[4:])
                self.close_popup()
            elif item.startswith("pin:"):
                self.toggle_pin(item[4:])
                self.show_popup()
            elif item.startswith("cat:"):
                self.start_cat = "" if item == "cat:all" else item[4:]
                self.start_page_n = 0
                self.show_popup()
            elif item in ("page:prev", "page:next"):
                self.start_page_n += 1 if item == "page:next" else -1
                self.show_popup()
        elif kind == "windows" and item.startswith("win:"):
            self.kwin.activate(item[4:])
            self.close_popup()
        elif kind == "taskmenu":
            self.task_menu_click(item)
            self.close_popup()
        elif kind == "profiles":
            if item.startswith("profile:"):
                subprocess.Popen([FT_LAYOUT, "profile", "apply", item[8:]], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                self.close_popup()
            elif item == "settings":
                self.launch("desktop ft-display-settings.desktop")
                self.close_popup()
        elif kind == "volume":
            if item == "slider":
                self.volume.set_level(u)
            elif item == "mute":
                self.volume.toggle_mute()
            elif item == "settings":
                self.launch("command " + json.dumps(["systemsettings", "kcm_pulseaudio"]))
                self.close_popup()
        elif kind == "wifi":
            if item == "wifi:toggle":
                self.wifi.set_enabled(not self.wifi.enabled)
            elif item.startswith("net:"):
                net = next((n for n in self.wifi.networks if "net:" + n["key"] == item), None)
                if net and not self.wifi.connect(net):
                    self.launch("command " + json.dumps(["systemsettings", "kcm_networkmanagement"]))
                self.close_popup()
            elif item == "settings":
                self.launch("command " + json.dumps(["systemsettings", "kcm_networkmanagement"]))
                self.close_popup()

    def toggle_pin(self, desktop_id):
        layout = ft_layout.load_layout()
        tb = dict(layout.get("toolbar") or {})
        tb["pinned_apps"] = model.toggle_pin(list(tb.get("pinned_apps") or []), desktop_id)
        layout["toolbar"] = tb
        ft_layout.save_layout(layout)
        self.push_tasks()

    # --- tasks
    def push_tasks(self):
        if not self.ready:
            return
        self.tasks = model.merge_tasks(self.pinned(), self.kwin.windows, self.apps(), self.kwin.active)
        icons = {t["id"]: icon_png(t["icon"]) for t in self.tasks}
        body = model.tasks_text(0, self.tasks, icons)
        if body == self._tasks_text:
            return
        self._tasks_text = body
        self.serial += 1
        write_atomic(os.path.join(RUN, "tasks.txt"), model.tasks_text(self.serial, self.tasks, icons))
        self.send(f"toolbar tasks {self.serial}")
        if self.popup.kind == "windows":
            self.show_popup()

    def task(self, task_id):
        return next((t for t in self.tasks if t["id"] == task_id), None)

    def task_click(self, task_id):
        task = self.task(task_id)
        if not task:
            return
        action, arg = model.task_click(task)
        if action == "launch" and arg:
            self.launch("desktop " + arg)
        elif action == "focus":
            self.kwin.activate(arg)
        elif action == "minimize":
            self.kwin.window_op("minimize", [arg])
        # "expose": ft-screens opens the windows popup itself (it knows the window count).

    # --- a task's right-click menu
    def desktop_path(self, task):
        did = task.get("desktop_id") or ""
        app = next((a for a in self.apps() if a["id"] == did), None)
        return (app or {}).get("path") or (ft_desktop.find_desktop_by_id(did) if did else None) or ""

    def app_actions(self, task):
        path = self.desktop_path(task)
        return ft_desktop.desktop_actions(path) if path else []

    def task_menu_click(self, item):
        task = self.task(self.popup.arg)
        if not task:
            return
        wins = task.get("windows") or []
        ids = [w["id"] for w in wins]
        every = lambda k: bool(wins) and all(w.get(k) for w in wins)  # noqa: E731
        if item.startswith("act:"):
            act = next((a for a in self.app_actions(task) if a["id"] == item[4:]), None)
            if act:
                try:
                    self.launch("command " + json.dumps(ft_desktop.argv_from_desktop_exec(act["exec"])))
                except ValueError as e:
                    log("action", act["id"], e)
        elif item == "new" and task.get("desktop_id"):
            self.launch("desktop " + task["desktop_id"])
        elif item == "min":
            if every("minimized"):
                self.kwin.window_op("activate", ids)
            else:
                self.kwin.window_op("minimize", ids)
        elif item == "max":
            self.kwin.window_op("unmaximize" if every("maximized") else "maximize", ids)
        elif item == "above":
            self.kwin.window_op("unabove" if every("above") else "above", ids)
        elif item == "full":
            self.kwin.window_op("unfullscreen" if every("fullscreen") else "fullscreen", ids)
        elif item.startswith("send:"):
            outs = model.output_order(self.kwin.outputs)
            n = int(item[5:]) if item[5:].isdigit() else 0
            if 1 <= n <= len(outs):
                self.kwin.window_op("send", ids, outs[n - 1])
        elif item == "pin" and task.get("desktop_id"):
            self.toggle_pin(task["desktop_id"])
        elif item == "close":
            self.kwin.window_op("close", ids)

    # --- tray
    def push_tray(self, force=False):
        vol = f"toolbar tray volume {model.volume_glyph_level(self.volume.level, self.volume.muted)} " \
              f"{int(round(self.volume.level * 100))}"
        wifi = f"toolbar tray wifi {int(self.wifi.enabled)} {self.wifi.bars} {int(self.wifi.connected)}"
        for key, msg in (("volume", vol), ("wifi", wifi)):
            if force or self._tray_sent.get(key) != msg:
                self._tray_sent[key] = msg
                self.send(msg)

    def on_volume(self):
        if self.ready:
            self.push_tray()
            if self.popup.kind == "volume":
                self.show_popup()

    def on_wifi(self):
        if self.ready:
            self.push_tray()
            if self.popup.kind == "wifi":
                self.show_popup()


def main():
    if dbus is not None:
        DBusGMainLoop(set_as_default=True)
    try:
        bar = Taskbar()
    except OSError as e:
        log("cannot bind @frametop_taskbar:", e)
        return 1
    loop = GLib.MainLoop()

    def stop(*_):
        bar.kwin.shutdown()
        loop.quit()

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, stop)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, stop)
    log("listening on @frametop_taskbar")
    loop.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
