#!/usr/bin/env python3
"""Isolated popup provider for the salvaged OpenVR toolbar.

Pixel appearance and hit rectangles use the original legacy ft-taskbar renderer
and model. Render on request, never on import. No compositor/UI monkeypatching.
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path
import sys
import tempfile
import urllib.parse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ft_desktop  # noqa: E402
import ft_toolbar  # noqa: E402
import ft_taskbar_model as model  # noqa: E402
import toolbar_profiles  # noqa: E402

import gi  # noqa: E402
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

FONT = "Noto Sans"
C_BG = (0x0E/255, 0x14/255, 0x1B/255)
C_ROW = (0x23/255, 0x26/255, 0x2E/255)
C_BTN = (0x3D/255, 0x44/255, 0x50/255)
C_ACCENT = (0x88/255, 0xCC/255, 0xF1/255)
C_TEXT = (0xDC/255, 0xDE/255, 0xDF/255)
C_DIM = (0x8B/255, 0x92/255, 0x9A/255)
RUN = ""
ICONS = ""

def log(*args):
    print("ft-toolbar-menu:", *args, file=sys.stderr, flush=True)

def write_atomic(path, data, mode="w"):
    destination = Path(path)
    fd, temp = tempfile.mkstemp(dir=destination.parent, prefix=".popup-", suffix=".tmp")
    try:
        with os.fdopen(fd, mode) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, destination)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

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



def image_rgba(surface):
    """Cairo ARGB32 is little-endian BGRA on the Frame; OpenVR wants RGBA."""
    surface.flush()
    width = surface.get_width()
    height = surface.get_height()
    stride = surface.get_stride()
    src = bytes(surface.get_data())
    output = bytearray(width * height * 4)
    if sys.byteorder != "little":
        raise RuntimeError("unsupported Cairo byte order")
    for y in range(height):
        for x in range(width):
            n = y * stride + 4*x
            o = (y * width + x)*4
            output[o:o+4] = bytes((src[n+2], src[n+1], src[n], src[n+3]))
    return output


def task_tile(task: dict, dimension: int = 128):
    """Reuse legacy task icon painter on a toolbar-coloured app tile."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, dimension, dimension)
    cr = cairo.Context(surface)
    rounded(cr, 0, 0, dimension, dimension, dimension * 0.17)
    cr.set_source_rgb(*C_BG)
    cr.fill()
    icon = icon_png(task.get("icon") or "")
    if icon and draw_icon(cr, icon, 24, 22, 80):
        pass
    else:
        # Fallback for windows without a FreeDesktop icon, not a blank tile.
        label = (task.get("name") or "?").strip()
        text(cr, label[:2].upper(), 26, 30, 76, 34, bold=True, align="center", h=70)
    if task.get("focused"):
        rounded(cr, 20, dimension - 9, dimension - 40, 4, 2)
        cr.set_source_rgb(*C_ACCENT)
        cr.fill()
    return surface


def render_toolbar(directory: Path):
    """Generate dynamic toolbar packing + task icon textures without OpenVR calls."""
    import ui_runtime
    running = ui_runtime.tasks(directory)
    width, positions = ui_runtime.button_positions(len(running))
    by_name = {name: x for _, name, x in positions}
    start_x = by_name["popup:start"]
    profile_x = by_name["popup:profiles"]
    tasks_text = []
    for i, task in enumerate(running):
        # IDs are only trusted from KWin's live task feed; no user-supplied path.
        tasks_text.append(f"task {model.wire_id(task['id'])} {by_name['task'+str(i+1)]:.8f}")
        write_atomic(directory / f"task-{i}.rgba", image_rgba(task_tile(task)), "wb")
    # Write task list last, so every referenced icon buffer already exists.
    write_atomic(directory / "tasks.txt", "\n".join(tasks_text) + "\n")
    write_atomic(directory / "layout.txt", (
        f"{width:.8f} {profile_x:.8f} {start_x:.8f} {len(running)}\n"
    ))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("render", "activate"))
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--kind", choices=("profiles", "start", "toolbar", "task"),
                        default="profiles")
    parser.add_argument("--item", default="")
    args = parser.parse_args(argv)
    directory = args.dir
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.action == "activate":
        if not args.item or len(args.item) > 400:
            parser.error("missing/oversized item ID")
        item = urllib.parse.unquote(args.item)
        import ui_runtime
        print(ui_runtime.activate(directory, args.kind, item))
        return 0
    global RUN, ICONS
    RUN = str(directory)
    ICONS = str(directory / "icons")
    (directory / "icons").mkdir(exist_ok=True, mode=0o700)
    if args.kind == "toolbar":
        render_toolbar(directory)
        return 0
    if args.kind == "start":
        import ui_runtime
        layout = ui_runtime.start_popup(directory)
    elif args.kind == "profiles":
        layout = toolbar_profiles.displays_popup()
    else:
        parser.error("no popup renderer for kind: " + args.kind)
    if layout["w"] > 1500 or layout["h"] > 2500:
        raise RuntimeError("popup texture too large")
    surface = render(layout, args.kind)
    write_atomic(directory / "popup.rgba", image_rgba(surface), "wb")
    write_atomic(directory / "popup.txt", model.items_text(
        args.kind, 1, layout, layout["w"] / model.PX_PER_M))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
