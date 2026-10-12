#!/usr/bin/env python3
"""Small standard-library client for Frametop's versioned extension commands.

No install, background daemon, OpenVR dependency or direct config-file edits.
The control socket is the existing abstract AF_UNIX datagram @ft_screens.
"""
from __future__ import annotations

import argparse
import math
import os
import secrets
import socket


class ExtensionError(RuntimeError):
    """Extension API is unavailable or rejected a command."""


class Frametop:
    def __init__(self, control: str = "ft_screens", timeout: float = 1.5) -> None:
        if not control or "\0" in control or len(control.encode()) > 90:
            raise ValueError("invalid abstract socket name")
        self.control = control
        self.timeout = timeout

    def request(self, command: str) -> str:
        payload = command.encode("utf-8")
        if not payload or len(payload) > 512 or b"\0" in payload or b"\n" in payload:
            raise ValueError("invalid control command")
        # The client must bind its own (different) abstract address for replies.
        local = "\0ft-ext-" + str(os.getpid()) + "-" + secrets.token_hex(6)
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.bind(local)
            sock.settimeout(self.timeout)
            try:
                sock.sendto(payload, "\0" + self.control)
                data, _, flags, _ = sock.recvmsg(4096)
            except (OSError, socket.timeout) as exc:
                raise ExtensionError(f"Frametop control socket unavailable: {exc}") from exc
        if flags & socket.MSG_TRUNC:
            raise ExtensionError("truncated Frametop reply")
        reply = data.decode("utf-8", errors="replace")
        if reply.startswith("error "):
            raise ExtensionError(reply)
        if not (reply == "ok" or reply.startswith("ok ")):
            raise ExtensionError(f"unexpected Frametop reply: {reply!r}")
        return reply

    def api_version(self) -> int:
        version = self.request("ext api").split()
        if len(version) != 2 or not version[1].isdigit():
            raise ExtensionError("unsupported extension API reply")
        return int(version[1])

    def capabilities(self) -> set[str]:
        return set(self.request("ext caps").split()[1:])

    def screen_status(self, number: int) -> dict[str, str]:
        reply = self.request(f"ext status {self._number(number)}").split()[1:]
        if len(reply) % 2:
            raise ExtensionError("malformed screen status")
        return dict(zip(reply[::2], reply[1::2]))

    @staticmethod
    def _number(number: int) -> int:
        if type(number) is not int or number < 1:
            raise ValueError("screen numbers start at 1")
        return number

    @staticmethod
    def _duration(ms: int) -> int:
        if type(ms) is not int or not 0 <= ms <= 10000:
            raise ValueError("duration must be 0..10000 milliseconds")
        return ms

    def opacity(self, number: int, alpha: float, duration_ms: int = 0) -> None:
        if not math.isfinite(alpha) or not 0 <= alpha <= 1:
            raise ValueError("opacity must be between 0 and 1")
        self.request(f"ext opacity {self._number(number)} {alpha:.6f} {self._duration(duration_ms)}")

    def move(self, number: int, x: float, y: float, z: float,
             yaw: float, pitch: float, roll: float, duration_ms: int = 0) -> None:
        pose = (x, y, z, yaw, pitch, roll)
        if not all(math.isfinite(v) for v in pose):
            raise ValueError("pose must have finite coordinates and angles")
        values = " ".join(f"{v:.6f}" for v in pose)
        self.request(f"ext move {self._number(number)} {values} {self._duration(duration_ms)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Call Frametop's extension API")
    parser.add_argument("--control", default="ft_screens", help="abstract control socket (default: ft_screens)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="show API version and capabilities")
    status = sub.add_parser("status", help="read a desktop screen's extension state")
    status.add_argument("screen", type=int)
    opacity = sub.add_parser("opacity", help="set or fade a screen's opacity")
    opacity.add_argument("screen", type=int)
    opacity.add_argument("alpha", type=float)
    opacity.add_argument("--ms", type=int, default=0)
    move = sub.add_parser("move", help="move a screen in world space (degrees for angles)")
    move.add_argument("screen", type=int)
    for name in ("x", "y", "z", "yaw", "pitch", "roll"):
        move.add_argument(name, type=float)
    move.add_argument("--ms", type=int, default=0)
    args = parser.parse_args()
    client = Frametop(control=args.control)
    try:
        if args.command == "info":
            print("Extension API:", client.api_version())
            print("Capabilities:", " ".join(sorted(client.capabilities())))
        elif args.command == "status":
            print(client.screen_status(args.screen))
        elif args.command == "opacity":
            client.opacity(args.screen, args.alpha, args.ms)
            print("ok")
        elif args.command == "move":
            client.move(args.screen, args.x, args.y, args.z,
                        args.yaw, args.pitch, args.roll, args.ms)
            print("ok")
    except (ExtensionError, ValueError) as exc:
        parser.exit(1, f"ft-ext: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
