#!/usr/bin/env python3
"""FreeDesktop application discovery, icon resolution, and nested-session launch helpers.

Used by ft-layout (CLI / Display Settings) and session/ft-launch.py (VR activation bridge).
Does not shell-eval Exec lines or plasmashell.env.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# Field codes in Desktop Entry Exec= (removed; never passed to a shell).
_FIELD_CODE_RE = re.compile(r"%(?:[fFuUdDnNickvm]|[A-Za-z])")

LAUNCHER_GLYPHS = (
    "play",
    "stop",
    "home",
    "gear",
    "star",
    "moon",
    "music",
    "terminal",
    "arrow",
    "power",
)

APPEARANCE_MODES = ("app", "glyph", "image", "fallback")
ACTION_KINDS = ("application", "action", "command")


def xdg_data_dirs():
    """XDG data directories (user first), including Flatpak exports and distrobox host paths.

    Display Settings / ft-layout often run inside the `dev` container; Frametop launches
    apps on the SteamOS host. Prefer host `/run/host/usr/share` entries when present so
    the chooser matches what `ft-launch` can actually start.
    """
    dirs = []
    home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    dirs.append(home)
    raw = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for part in raw.split(":"):
        part = part.strip()
        if part and part not in dirs:
            dirs.append(part)
    # Distrobox mounts the SteamOS root here; host apps beat container-only .desktop files.
    host_dirs = []
    for host in (
        "/run/host/usr/local/share",
        "/run/host/usr/share",
        "/run/host/var/lib/flatpak/exports/share",
    ):
        if host not in dirs and os.path.isdir(host):
            host_dirs.append(host)
    if host_dirs:
        dirs[1:1] = host_dirs
    # Flatpak exports often live here even when XDG_DATA_DIRS is incomplete.
    for extra in (
        os.path.expanduser("~/.local/share/flatpak/exports/share"),
        "/var/lib/flatpak/exports/share",
    ):
        if extra not in dirs and os.path.isdir(extra):
            dirs.append(extra)
    return dirs


def applications_dirs():
    return [os.path.join(d, "applications") for d in xdg_data_dirs()]


def _truthy(val):
    return (val or "").strip().lower() in ("1", "true")


def read_desktop_entry(path):
    """Parse a .desktop Application entry, including Hidden / NoDisplay ones.

    Returns None if missing, not Type=Application, lacking Name/Exec, or unreadable.
    Includes boolean ``hidden`` and ``nodisplay`` flags from the file.
    """
    path = str(path)
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    group = None
    entry = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1].strip()
            continue
        if group != "Desktop Entry" or "=" not in line:
            continue
        key, val = line.split("=", 1)
        entry[key.strip().lower()] = val.strip()
    if entry.get("type", "Application") != "Application":
        return None
    name = entry.get("name") or ""
    exec_line = entry.get("exec") or ""
    if not name or not exec_line:
        return None
    return {
        "path": os.path.abspath(path),
        "id": desktop_id_for_path(path),
        "name": name,
        "generic_name": entry.get("genericname") or "",
        "icon": entry.get("icon") or "",
        "exec": exec_line,
        "terminal": _truthy(entry.get("terminal")),
        "try_exec": entry.get("tryexec") or "",
        "categories": [c for c in (entry.get("categories") or "").split(";") if c],
        "wm_class": entry.get("startupwmclass") or "",
        "only_show_in": [d for d in (entry.get("onlyshowin") or "").split(";") if d],
        "not_show_in": [d for d in (entry.get("notshowin") or "").split(";") if d],
        "hidden": _truthy(entry.get("hidden")),
        "nodisplay": _truthy(entry.get("nodisplay")),
    }


def parse_desktop_file(path):
    """Launchable Application entry (not Hidden). NoDisplay apps are included.

    Frametop Start lists every launchable app; SteamOS leaves many NoDisplay stubs
    that still have a real Exec. Hidden=true means the entry is deleted.
    """
    info = read_desktop_entry(path)
    if not info or info["hidden"]:
        return None
    return {k: v for k, v in info.items() if k not in ("hidden", "nodisplay")}


def current_desktops(env=None):
    """XDG_CURRENT_DESKTOP as a list.

    Frametop's start menu runs inside nested Plasma, but the process often inherits the
    host session's XDG_CURRENT_DESKTOP=gamescope. Apps with OnlyShowIn=KDE (System
    Settings, Menu Editor, …) must still appear, so KDE is always included.
    """
    raw = (env or os.environ).get("XDG_CURRENT_DESKTOP") or "KDE"
    desks = [d for d in raw.split(":") if d]
    if "KDE" not in desks and "Plasma" not in desks:
        desks.append("KDE")
    return desks


def shown_in(info, desktops):
    """OnlyShowIn= / NotShowIn= against the current desktops."""
    if info.get("only_show_in") and not set(info["only_show_in"]) & set(desktops):
        return False
    return not set(info.get("not_show_in") or []) & set(desktops)


def desktop_actions(path):
    """The application's own actions ([Desktop Action X] groups listed in Actions=), in
    order: [{"id", "name", "exec"}]. Actions without a Name or Exec are skipped."""
    try:
        text = Path(str(path)).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    group, listed, found = None, [], {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1].strip()
            continue
        if "=" not in line:
            continue
        key, val = (s.strip() for s in line.split("=", 1))
        if group == "Desktop Entry" and key == "Actions":
            listed = [a for a in val.split(";") if a]
        elif group and group.startswith("Desktop Action ") and key in ("Name", "Exec"):
            found.setdefault(group[15:].strip(), {})[key.lower()] = val
    out = []
    for a in listed:
        info = found.get(a) or {}
        if info.get("name") and info.get("exec"):
            out.append({"id": a, "name": info["name"], "exec": info["exec"]})
    return out


def desktop_id_for_path(path):
    """Stable desktop-file id: basename, or relative path under an applications/ dir.

    FreeDesktop desktop-file ids use `/` → `-` for subdirectories
    (`kde/foo.desktop` → `kde-foo.desktop`).
    """
    path = os.path.abspath(path)
    base = os.path.basename(path)
    for apps in applications_dirs():
        apps = os.path.abspath(apps)
        if path.startswith(apps + os.sep):
            rel = path[len(apps) + 1 :].replace(os.sep, "-")
            return rel if rel.endswith(".desktop") else base
    return base


def _usable_desktop_path(path):
    """Absolute path if this file is a launchable (non-Hidden) Application, else None."""
    info = read_desktop_entry(path)
    if info and not info["hidden"]:
        return info["path"]
    return None


def find_desktop_by_id(desktop_id):
    """Resolve a desktop id (e.g. org.kde.konsole.desktop) to an absolute path.

    Skips Hidden=true stubs so a SteamOS user overlay does not block the system file.
    """
    desktop_id = str(desktop_id or "").strip()
    if not desktop_id:
        return None
    if not desktop_id.endswith(".desktop"):
        desktop_id += ".desktop"
    # Absolute path passed through when launchable.
    if os.path.isabs(desktop_id) and os.path.isfile(desktop_id):
        return _usable_desktop_path(desktop_id) or desktop_id

    for apps in applications_dirs():
        if not os.path.isdir(apps):
            continue
        # Top-level basename (org.kde.konsole.desktop).
        p = os.path.join(apps, desktop_id)
        if os.path.isfile(p):
            got = _usable_desktop_path(p)
            if got:
                return got
            continue
        # FreeDesktop id with vendor dir: kde-foo.desktop → kde/foo.desktop (one segment).
        if "-" in desktop_id:
            vendor, rest = desktop_id.split("-", 1)
            p = os.path.join(apps, vendor, rest)
            if os.path.isfile(p):
                got = _usable_desktop_path(p)
                if got:
                    return got
        # Match list_applications() ids (full / → - rewrite), not only basenames.
        for root, _dirs, files in os.walk(apps):
            for name in files:
                if not name.endswith(".desktop"):
                    continue
                path = os.path.join(root, name)
                if name == desktop_id or desktop_id_for_path(path) == desktop_id:
                    got = _usable_desktop_path(path)
                    if got:
                        return got
    return None


def application_available(desktop_id):
    """True when desktop_id resolves or appears in list_applications() (same as the chooser)."""
    desktop_id = str(desktop_id or "").strip()
    if not desktop_id:
        return True
    if find_desktop_by_id(desktop_id):
        return True
    try:
        return any(a["id"] == desktop_id or a["id"] == desktop_id + ".desktop"
                   for a in list_applications())
    except OSError:
        return False


def list_applications(search=None):
    """Return sorted list of launchable Application desktop entries for Start.

    Each item: id, name, icon, path, categories, wm_class. Deduped by desktop id.

    Earlier XDG dirs win for a *usable* entry (user customizations). A Hidden=true
    stub in ~/.local does **not** remove a later system copy — SteamOS leaves those
    stubs to declutter Gaming Mode menus, but Frametop Start shows every launchable
    app. NoDisplay=true entries are included for the same reason.
    """
    search = (search or "").strip().lower()
    desktops = current_desktops()
    seen = {}
    claimed = set()
    for apps in applications_dirs():
        if not os.path.isdir(apps):
            continue
        for root, _dirs, files in os.walk(apps):
            for name in files:
                if not name.endswith(".desktop"):
                    continue
                path = os.path.join(root, name)
                did = desktop_id_for_path(path)
                if did in claimed:
                    continue
                info = read_desktop_entry(path)
                if not info or info["hidden"] or not shown_in(info, desktops):
                    continue
                claimed.add(did)
                if search and search not in info["name"].lower() and search not in info["id"].lower():
                    continue
                seen[did] = {
                    "id": info["id"],
                    "name": info["name"],
                    "icon": info["icon"],
                    "path": info["path"],
                    "categories": info["categories"],
                    "wm_class": info["wm_class"],
                }
    return sorted(seen.values(), key=lambda a: (a["name"].lower(), a["id"].lower()))


def icon_theme_dirs():
    """Candidate icon theme roots (breeze / hicolor / …)."""
    themes = []
    for data in xdg_data_dirs():
        themes.append(os.path.join(data, "icons"))
    themes.append("/usr/share/pixmaps")
    return themes


def _icon_basename_candidates(icon_name):
    icon_name = str(icon_name or "").strip()
    if not icon_name:
        return []
    if os.path.isabs(icon_name):
        return [icon_name]
    out = [icon_name]
    if icon_name.endswith((".png", ".svg", ".xpm", ".jpg", ".jpeg")):
        out.append(os.path.splitext(icon_name)[0])
    return out


def resolve_icon_path(icon_name, prefer_size=128, allow_svg=False):
    """Resolve a Desktop Entry Icon= value to a file path.

    Prefers PNG/XPM/JPEG (ft-screens stb path has no SVG). With allow_svg=True,
    returns an .svg path when no raster exists so callers can convert it.
    """
    icon_name = str(icon_name or "").strip()
    if not icon_name:
        return None
    if os.path.isabs(icon_name) and os.path.isfile(icon_name):
        ext = os.path.splitext(icon_name)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".xpm", ".gif"):
            return icon_name
        if ext == ".svg":
            png = os.path.splitext(icon_name)[0] + ".png"
            if os.path.isfile(png):
                return png
            return icon_name if allow_svg else None
        return None

    names = _icon_basename_candidates(icon_name)
    raster_exts = (".png", ".xpm", ".jpg", ".jpeg")
    size_dirs = [
        f"{prefer_size}x{prefer_size}",
        "128x128",
        "96x96",
        "64x64",
        "48x48",
        "256x256",
        "scalable",
        "32x32",
        "24x24",
        "16x16",
    ]
    theme_names = []
    for t in (
        os.environ.get("FRAMETOP_ICON_THEME"),
        "breeze",
        "breeze-dark",
        "hicolor",
        "Adwaita",
        "oxygen",
    ):
        if t and t not in theme_names:
            theme_names.append(t)

    candidates = []
    svg_candidates = []
    for root in icon_theme_dirs():
        if root.endswith("pixmaps") or os.path.basename(root) == "pixmaps":
            for n in names:
                for ext in raster_exts:
                    p = os.path.join(root, n if n.endswith(ext) else n + ext)
                    if os.path.isfile(p):
                        candidates.append((0, p))
                if allow_svg:
                    p = os.path.join(root, n if n.endswith(".svg") else n + ".svg")
                    if os.path.isfile(p):
                        svg_candidates.append((50, p))
            continue
        if not os.path.isdir(root):
            continue
        for theme in theme_names:
            tdir = os.path.join(root, theme)
            if not os.path.isdir(tdir):
                continue
            for si, size in enumerate(size_dirs):
                for cat in ("apps", "places", "devices", "mimetypes", "actions", "categories", "status"):
                    for n in names:
                        for ext in raster_exts:
                            p = os.path.join(tdir, size, cat, n if n.endswith(ext) else n + ext)
                            if os.path.isfile(p):
                                score = theme_names.index(theme) * 1000 + si
                                candidates.append((score, p))
                        if allow_svg:
                            p = os.path.join(tdir, size, cat, n if n.endswith(".svg") else n + ".svg")
                            if os.path.isfile(p):
                                score = theme_names.index(theme) * 1000 + si + 500
                                svg_candidates.append((score, p))
    if candidates:
        candidates.sort(key=lambda c: c[0])
        return candidates[0][1]
    if allow_svg and svg_candidates:
        svg_candidates.sort(key=lambda c: c[0])
        return svg_candidates[0][1]
    # Last resort: recursive name match under icon roots (slow path, capped).
    for root in icon_theme_dirs():
        if not os.path.isdir(root):
            continue
        count = 0
        for dirpath, _dirs, files in os.walk(root):
            count += 1
            if count > 4000:
                break
            for n in names:
                for ext in raster_exts:
                    fn = n if n.endswith(ext) else n + ext
                    if fn in files:
                        return os.path.join(dirpath, fn)
                if allow_svg:
                    fn = n if n.endswith(".svg") else n + ".svg"
                    if fn in files:
                        return os.path.join(dirpath, fn)
    return None


def convert_svg_to_png(svg_path, png_path, size=128):
    """Rasterize SVG → PNG using rsvg or ImageMagick. Returns png_path or None."""
    svg_path = os.path.abspath(svg_path)
    png_path = os.path.abspath(png_path)
    if not os.path.isfile(svg_path):
        return None
    os.makedirs(os.path.dirname(png_path) or ".", exist_ok=True)
    size = max(16, min(512, int(size)))
    attempts = []
    if shutil.which("rsvg-convert"):
        attempts.append(
            ["rsvg-convert", "-w", str(size), "-h", str(size), "-o", png_path, svg_path])
    if shutil.which("magick"):
        attempts.append(
            ["magick", "-background", "none", svg_path, "-resize", f"{size}x{size}", png_path])
    if shutil.which("convert"):
        attempts.append(
            ["convert", "-background", "none", svg_path, "-resize", f"{size}x{size}", png_path])
    for cmd in attempts:
        try:
            subprocess.run(
                cmd,
                check=True,
                timeout=20,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if os.path.isfile(png_path) and os.path.getsize(png_path) > 0:
                return png_path
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def ensure_raster_icon(icon_name, dest_png, prefer_size=128):
    """Resolve Icon= to a PNG at dest_png (converting SVG when needed). Return path or None."""
    icon = resolve_icon_path(icon_name, prefer_size=prefer_size, allow_svg=True)
    if not icon:
        return None
    ext = os.path.splitext(icon)[1].lower()
    if ext == ".svg":
        return convert_svg_to_png(icon, dest_png, size=prefer_size)
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".xpm"):
        return icon
    return None


def plasmashell_env_path(env=None):
    """Path to the NUL env snapshot written by ft-shell-watch ($XDG_RUNTIME_DIR/plasmashell.env)."""
    env = env or os.environ
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(runtime, "plasmashell.env")


def load_nul_env_file(path):
    """Load a NUL-separated KEY=VALUE file (plasmashell.env) into a dict."""
    out = {}
    with open(path, "rb") as f:
        blob = f.read()
    for entry in blob.split(b"\0"):
        if not entry or b"=" not in entry:
            continue
        k, _, v = entry.partition(b"=")
        try:
            key = k.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        out[key] = v.decode("utf-8", errors="surrogateescape")
    return out


def nested_launch_env(base=None):
    """Build an env dict for launching into nested Frametop Plasma (not outer ft-screens).

    ft-launch starts before Plasma, so its process env still has WAYLAND_DISPLAY pointed
    at the host compositor. Using that opens apps as extra ft-screens overlays (floating
    VR panels that Plasma cannot close). plasmashell.env has nested wayland-N.
    """
    env = dict(base or os.environ)
    path = plasmashell_env_path(env)
    if not os.path.isfile(path):
        raise RuntimeError(
            "nested Plasma not ready yet (no plasmashell.env) — wait for the desktop, then retry")
    loaded = load_nul_env_file(path)
    env.update(loaded)
    wl = str(env.get("WAYLAND_DISPLAY") or "")
    runtime = str(env.get("XDG_RUNTIME_DIR") or "")
    if wl.startswith("/") or not wl.startswith("wayland-"):
        raise RuntimeError(
            f"refusing launch: WAYLAND_DISPLAY={wl!r} is not nested KWin (see plasmashell.env)")
    if "frametop" not in runtime.replace("\\", "/"):
        raise RuntimeError(
            f"refusing launch: XDG_RUNTIME_DIR={runtime!r} is not the Frametop nested runtime")
    return env


def strip_exec_field_codes(exec_line):
    """Remove Desktop Entry field codes from Exec=; return cleaned string."""
    s = _FIELD_CODE_RE.sub("", exec_line or "")
    return re.sub(r"\s+", " ", s).strip()


def argv_from_desktop_exec(exec_line):
    """Parse Exec= into argv without invoking a shell. Raises ValueError on failure."""
    cleaned = strip_exec_field_codes(exec_line)
    if not cleaned:
        raise ValueError("empty Exec")
    try:
        argv = shlex.split(cleaned, posix=True)
    except ValueError as e:
        raise ValueError(f"cannot parse Exec: {e}") from e
    if not argv:
        raise ValueError("empty Exec argv")
    return argv


def spawn_detached(argv, env=None, cwd=None):
    """Start a process fully detached; do not wait; stdout/stderr to /dev/null."""
    if not argv:
        raise ValueError("empty argv")
    env = env or os.environ.copy()
    # Double-fork style via start_new_session; close stdio so pipes cannot fill.
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": env,
        "start_new_session": True,
        "close_fds": True,
    }
    if cwd:
        kwargs["cwd"] = cwd
    # Prefer absolute executable when PATH lookup works.
    exe = argv[0]
    if not os.path.isabs(exe):
        found = shutil.which(exe, path=env.get("PATH"))
        if found:
            argv = [found] + list(argv[1:])
    return subprocess.Popen(argv, **kwargs)


def launch_desktop_id(desktop_id, env=None, require_nested=True):
    """Launch an application by desktop id into nested Frametop Plasma.

    By default requires plasmashell.env (nested wayland-N). Launching with the
    pre-Plasma WAYLAND_DISPLAY (absolute ft-screens socket) creates extra host
    compositor surfaces — floating VR panels Plasma cannot close.
    """
    base = env or os.environ.copy()
    if require_nested:
        env = nested_launch_env(base)
    else:
        env = dict(base)
    path = find_desktop_by_id(desktop_id)
    if not path:
        raise FileNotFoundError(f"desktop entry not found: {desktop_id}")
    info = parse_desktop_file(path)
    if not info:
        raise FileNotFoundError(f"desktop entry unavailable or hidden: {desktop_id}")
    try_exec = info.get("try_exec") or ""
    if try_exec and not shutil.which(try_exec, path=env.get("PATH")) and not os.path.isfile(try_exec):
        raise FileNotFoundError(f"TryExec missing: {try_exec}")
    # Prefer Exec= under the nested env. Gio.DesktopAppInfo.launch / D-Bus activation
    # has been observed to attach clients to the outer ft-screens Wayland instead.
    argv = argv_from_desktop_exec(info["exec"])
    if info.get("terminal"):
        term = shutil.which("konsole", path=env.get("PATH")) or shutil.which("xterm", path=env.get("PATH"))
        if term:
            argv = [term, "-e"] + argv
    spawn_detached(argv, env=env)
    return


def launch_command_argv(argv, env=None, require_nested=True):
    argv = [str(a) for a in (argv or [])]
    if not argv:
        raise ValueError("empty command argv")
    base = env or os.environ.copy()
    env = nested_launch_env(base) if require_nested else dict(base)
    spawn_detached(argv, env=env)


def launch_command_shell(script, env=None, require_nested=True):
    """Expert path: run user-authored shell text via /bin/sh -c (explicitly a shell)."""
    script = str(script or "")
    if not script.strip():
        raise ValueError("empty shell command")
    base = env or os.environ.copy()
    env = nested_launch_env(base) if require_nested else dict(base)
    spawn_detached(["/bin/sh", "-c", script, "--"], env=env)
