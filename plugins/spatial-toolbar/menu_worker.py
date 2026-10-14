#!/usr/bin/env python3
"""Persistent local Cairo/Pango renderer for the independent OpenVR toolbar.

The old toolbar fork paid Python startup, GI typelibs, Pango setup, icon
discovery and full catalog scan on EVERY Start/category click. This helper
imports the actual salvaged renderer once, then handles commands on a private
Unix socket. It never touches the Frametop core compositor.

Protocol: one UTF-8 request line with TAB-separated action, kind, item.
A response is exactly "ok\n" or "error <summary>\n".
Only the single user-owned run.sh instance starts the worker.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import stat
import sys
import time

SOCKET_NAME = "menu.sock"
VALID_ACTIONS = frozenset({"render", "activate", "stop", "ping"})
VALID_KINDS = frozenset({"start", "profiles", "toolbar", "task"})
MAX_REQUEST = 2048


def socket_path(runtime: Path) -> Path:
    return runtime / SOCKET_NAME


def request(runtime: Path, action: str, kind: str = "profiles",
            item: str = "", timeout: float = 3.0) -> str:
    """Client API usable from host Python, without importing Cairo/gi.

    Explicitly bounded payload, newline-safe framing, and a timeout to avoid
    trapping the OpenVR process if the helper crashes or hangs.
    """
    if action not in VALID_ACTIONS or kind not in VALID_KINDS:
        raise ValueError("unsupported toolbar menu command")
    if len(item.encode("utf-8")) > 400 or any(ch in item for ch in "\r\n\t"):
        raise ValueError("invalid menu item")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(str(socket_path(runtime)))
        conn.sendall(f"{action}\t{kind}\t{item}\n".encode("utf-8"))
        response = bytearray()
        while b"\n" not in response and len(response) < 1024:
            chunk = conn.recv(1024)
            if not chunk:
                break
            response.extend(chunk)
    line = response.split(b"\n", 1)[0].decode("utf-8", "replace")
    if not line.startswith("ok") or line != "ok":
        raise RuntimeError(line or "menu helper disconnected")
    return line


def parse_command(payload: bytes) -> tuple[str, str, str]:
    if len(payload) > MAX_REQUEST or not payload.endswith(b"\n"):
        raise ValueError("invalid menu request length")
    try:
        action, kind, item = payload[:-1].decode("utf-8").split("\t", 2)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("invalid menu request encoding") from exc
    if action not in VALID_ACTIONS or kind not in VALID_KINDS:
        raise ValueError("unsupported toolbar action or kind")
    if len(item.encode("utf-8")) > 400 or any(ch in item for ch in "\r\n\t"):
        raise ValueError("invalid menu item")
    if action == "activate" and not item:
        raise ValueError("missing activation item")
    return action, kind, item


def serve(runtime: Path) -> None:
    runtime = runtime.resolve(strict=True)
    if not runtime.is_dir() or runtime.stat().st_uid != os.getuid():
        raise RuntimeError("toolbar runtime directory must belong to this user")
    if runtime.stat().st_mode & 0o077:
        raise RuntimeError("toolbar runtime directory must be private (0700)")
    dest = socket_path(runtime)
    if dest.is_symlink():
        raise RuntimeError("refusing a symlinked menu socket")
    if dest.exists():
        # run.sh single-instance lock prevents replacing a live socket from
        # another toolbar. This path is always in our own private runtime dir.
        if not stat.S_ISSOCK(dest.stat().st_mode):
            raise RuntimeError("refusing to overwrite a non-socket menu path")
        dest.unlink()
    import menu  # expensive GI/Pango/Cairo imports occur ONCE here

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(dest))
        dest.chmod(0o600)
        server.listen(8)
        server.settimeout(1.)
        print("toolbar-menu: warm renderer ready (persistent Pango/Cairo)",
              file=sys.stderr, flush=True)
        try:
            running = True
            while running:
                try:
                    client, _ = server.accept()
                except socket.timeout:
                    continue
                with client:
                    client.settimeout(3.)
                    try:
                        payload = bytearray()
                        while b"\n" not in payload and len(payload) <= MAX_REQUEST:
                            part = client.recv(1024)
                            if not part:
                                break
                            payload.extend(part)
                        action, kind, item = parse_command(bytes(payload))
                        if action == "stop":
                            running = False
                        elif action not in ("ping",):
                            started = time.perf_counter()
                            argv = [action, "--dir", str(runtime), "--kind", kind]
                            if item:
                                argv.extend(["--item", item])
                            status = menu.main(argv)
                            if status != 0:
                                raise RuntimeError(f"renderer failed with status {status}")
                            if os.environ.get("FT_TOOLBAR_TRACE") == "1":
                                print(f"toolbar-menu: warm {action}/{kind} "
                                      f"{time.perf_counter()-started:.3f}s",
                                      file=sys.stderr, flush=True)
                        response = "ok\n"
                    except Exception as exc:
                        response = f"error {str(exc)[:260]}\n"
                        print(f"toolbar-menu: {response.strip()}", file=sys.stderr,
                              flush=True)
                    try:
                        client.sendall(response.encode("utf-8", "replace"))
                    except (OSError, BrokenPipeError):
                        pass
        finally:
            if dest.is_socket():
                dest.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("serve", "ping", "stop"))
    parser.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "serve":
        serve(args.dir)
    else:
        request(args.dir, args.command, timeout=2.)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
