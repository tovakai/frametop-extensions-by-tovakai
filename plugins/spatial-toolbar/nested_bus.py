"""Find the running nested Frametop Plasma/KWin D-Bus, not the host bus.

The upstream Frametop session uses:
  XDG_RUNTIME_DIR=/run/user/UID/frametop dbus-run-session startplasma-wayland

Because a toolbar launched from SSH or host terminal inherits the host bus,
we must locate the *existing* nested KWin environment without starting a bus,
modifying Frametop, or making an arbitrary process into a D-Bus owner.
"""
from __future__ import annotations

import os
from pathlib import Path


class NestedSessionError(RuntimeError):
    pass


def _env_from_proc(pid_dir: Path) -> dict[str, str]:
    try:
        if pid_dir.stat().st_uid != os.getuid():
            return {}
        name = (pid_dir / "comm").read_text(encoding="utf-8").strip()
        if name not in {"kwin_wayland", "plasmashell", "startplasma-wayland"}:
            return {}
        # Only extract the three essential values, never log or retain other
        # contents of another process's environment (tokens/secrets may exist).
        raw = (pid_dir / "environ").read_bytes()[:256 * 1024]
    except (OSError, UnicodeError):
        return {}
    wanted = {"XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY"}
    env = {}
    for field in raw.split(b"\0"):
        if b"=" not in field:
            continue
        key, value = field.split(b"=", 1)
        try:
            key = key.decode("ascii")
            if key in wanted:
                env[key] = value.decode("utf-8")
        except UnicodeError:
            continue
    return env


def candidates(proc_root: Path, uid: int, host_runtime: Path):
    nested = str(host_runtime / "frametop")
    for pid in proc_root.iterdir():
        if not pid.name.isdigit():
            continue
        env = _env_from_proc(pid)
        if env.get("XDG_RUNTIME_DIR") != nested:
            continue
        addr = env.get("DBUS_SESSION_BUS_ADDRESS", "")
        if not addr.startswith(("unix:path=", "unix:abstract=")):
            continue
        yield env


def discover(proc_root: Path = Path("/proc"), uid: int | None = None,
             host_runtime: Path | None = None) -> dict[str, str]:
    """Discover, and require exactly one live nested session address.

    Reject host D-Bus and ambiguous sessions. No automatic fallback to the
    caller's bus: that was the cause of ServiceUnknown for org.kde.KWin.
    """
    uid = os.getuid() if uid is None else uid
    host_runtime = Path(f"/run/user/{uid}") if host_runtime is None else host_runtime
    if not (host_runtime / "frametop").is_dir():
        raise NestedSessionError("Frametop's nested runtime directory is absent")
    try:
        found = list(candidates(proc_root, uid, host_runtime))
    except OSError as exc:
        raise NestedSessionError(f"Cannot inspect nested KWin session: {exc}") from exc
    addresses = {env["DBUS_SESSION_BUS_ADDRESS"] for env in found}
    if len(addresses) != 1:
        raise NestedSessionError(
            "Could not uniquely discover nested KWin D-Bus. "
            f"Found {len(addresses)} private bus addresses among {len(found)} nested Plasma processes. "
            "The nested Plasma desktop must be fully started."
        )
    address = next(iter(addresses))
    # Prefer the KWin process's matching environment, but only three safe keys
    # are propagated. No LD_PRELOAD, PATH, SSH_*, or untrusted execution state.
    matched = next(env for env in found if env["DBUS_SESSION_BUS_ADDRESS"] == address)
    return {key: matched[key] for key in (
        "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "WAYLAND_DISPLAY"
    ) if key in matched}
