"""Read-only Steam Frame controller events from the local vrserver input feed.

Adapted from Frametop's input/vrws.py design. Uses Python standard library only.
This is an undocumented SteamVR loopback API, so errors must fail closed. Unlike
OpenVR global action sets, subscriptions do not claim buttons from other apps.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import select
import socket
import struct
import time
import urllib.request

HOST = "127.0.0.1"
PORT = 27062
ORIGIN = f"http://{HOST}:{PORT}"
HEADERS = {"Referer": f"{ORIGIN}/dashboard/controllerbinding.html"}
# These are the buttons actually present on each Frame controller.
BUTTON_ACTIONS = {
    ("right", "trigger"): "place",
    ("right", "grip"): "mode",
    ("right", "a"): "confirm",
    ("right", "b"): "undo",
    ("right", "bumper"): "label",
    ("right", "thumbstick"): "rotate",
    ("right", "y"): "height",
    ("right", "x"): "save",
    ("left", "dpad_left"): "rotate_left",
    ("left", "dpad_right"): "rotate_right",
}


def controllers(timeout: float = 2.0) -> dict[str, str]:
    """Map current Frame controller device roots to left/right. No state changes."""
    req = urllib.request.Request(f"{ORIGIN}/input/getstate.json", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        document = json.load(response)
    if not isinstance(document, dict):
        raise ValueError("vrserver returned an invalid controller state")
    found = {}
    for device in document.get("devices", []):
        if not isinstance(device, dict):
            continue
        if device.get("controller_type") != "frame_controller":
            continue
        path, side = device.get("root_path"), device.get("side")
        if isinstance(path, str) and path.startswith("/") and side in ("left", "right"):
            found[path] = side
    return found


class VrSocket:
    """Minimal RFC 6455 reader for SteamVR's local input_server mailbox."""
    def __init__(self, *, timeout: float = 3.0):
        self.sock = socket.create_connection((HOST, PORT), timeout=timeout)
        try:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            request = (f"GET / HTTP/1.1\r\nHost: {HOST}:{PORT}\r\n"
                       "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                       f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                       f"Origin: {ORIGIN}\r\nReferer: {HEADERS['Referer']}\r\n\r\n")
            self.sock.sendall(request.encode("ascii"))
            response = b""
            while b"\r\n\r\n" not in response:
                if len(response) > 16384:
                    raise OSError("oversized vrserver websocket handshake")
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise OSError("vrserver closed connection during handshake")
                response += chunk
            headers, initial = response.split(b"\r\n\r\n", 1)
            lines = headers.decode("iso-8859-1").split("\r\n")
            if " 101 " not in lines[0] + " ":
                raise OSError(f"vrserver refused websocket: {lines[0]}")
            pairs = {}
            for line in lines[1:]:
                if ":" in line:
                    field, value = line.split(":", 1)
                    pairs[field.lower()] = value.strip()
            expected = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest()).decode("ascii")
            if pairs.get("sec-websocket-accept") != expected:
                raise OSError("vrserver websocket handshake signature mismatch")
        except BaseException:
            self.sock.close()
            raise
        self.sock.settimeout(None)
        self.data = bytearray(initial)
        self.fragment = bytearray()
        self.mailbox = ""

    def close(self):
        try:
            self._send_frame(8, b"")
        except OSError:
            pass
        self.sock.close()

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        size = len(payload)
        head = bytes((0x80 | opcode,))
        if size < 126:
            head += bytes((0x80 | size,))
        elif size < 65536:
            head += bytes((0x80 | 126,)) + struct.pack(">H", size)
        else:
            head += bytes((0x80 | 127,)) + struct.pack(">Q", size)
        mask = os.urandom(4)
        self.sock.sendall(head + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload)))

    def send(self, message: str) -> None:
        self._send_frame(1, message.encode("utf-8"))

    def open(self, mailbox: str) -> None:
        self.send(f"mailbox_open {mailbox}")
        self.mailbox = mailbox

    def subscribe(self, path: str) -> None:
        self.send("mailbox_send input_server " + json.dumps({
            "type": "request_input_state_updates",
            "device_path": path,
            "returnAddress": self.mailbox
        }))

    def messages(self, *, timeout: float = 0.25) -> list[str]:
        messages = self._parse()
        if messages:
            return messages
        if not select.select([self.sock], [], [], timeout)[0]:
            return []
        chunk = self.sock.recv(65536)
        if not chunk:
            raise OSError("vrserver closed controller input stream")
        self.data.extend(chunk)
        return self._parse()

    def _parse(self) -> list[str]:
        out, pos, buf = [], 0, self.data
        while len(buf) - pos >= 2:
            first, second = buf[pos], buf[pos + 1]
            length, header = second & 0x7f, 2
            if length == 126:
                if len(buf) - pos < 4:
                    break
                length, header = struct.unpack_from(">H", buf, pos + 2)[0], 4
            elif length == 127:
                if len(buf) - pos < 10:
                    break
                length, header = struct.unpack_from(">Q", buf, pos + 2)[0], 10
            if length > 1024 * 1024:
                raise OSError("oversized vrserver input message")
            masked = bool(second & 0x80)
            if masked:
                header += 4
            if len(buf) - pos < header + length:
                break
            payload = bytes(buf[pos + header:pos + header + length])
            if masked:
                mask = buf[pos + header - 4:pos + header]
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            pos += header + length
            opcode = first & 0x0f
            if opcode == 8:
                raise OSError("vrserver closed controller input stream")
            if opcode == 9:
                self._send_frame(10, payload)
            elif opcode in (0, 1, 2):
                self.fragment.extend(payload)
                if len(self.fragment) > 1024 * 1024:
                    raise OSError("oversized fragmented vrserver message")
                if first & 0x80:
                    out.append(self.fragment.decode("utf-8", errors="replace"))
                    self.fragment.clear()
        del buf[:pos]
        return out


class ButtonMapper:
    """Translate changed components into one action per rising edge."""
    def __init__(self):
        self.down: dict[tuple[str, str], bool] = {}

    def feed(self, message: str, sides: dict[str, str]) -> list[str]:
        try:
            event = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(event, dict) or event.get("type") != "update_component_states":
            return []
        side = sides.get(event.get("device"))
        if side is None:
            return []
        components = event.get("components", {})
        if not isinstance(components, dict):
            return []
        result = []
        for component, pressed in components.items():
            if not isinstance(component, str) or not component.startswith("/input/") or \
               not component.endswith("/click") or type(pressed) is not bool:
                continue
            button = component[len("/input/"):-len("/click")]
            action = BUTTON_ACTIONS.get((side, button))
            if action is None:
                continue
            key = (side, button)
            previous = self.down.get(key, False)
            self.down[key] = pressed
            if pressed and not previous:
                result.append(action)
        return result


def watch(stop, on_press, on_status=lambda message: None, *, debug: bool = False) -> None:
    """Watch controller presses until stop is set; reconnect without modifying SteamVR."""
    failures = 0
    while not stop.is_set():
        try:
            sides = controllers()
            if not sides:
                raise OSError("no tracked Frame controllers in vrserver input state")
            ws = VrSocket()
            try:
                ws.open(f"spatial_room_{os.getpid()}_{time.monotonic_ns()}")
                for path in sides:
                    ws.subscribe(path)
                on_status("read-only input connected: " + ", ".join(sorted(set(sides.values()))))
                mapper = ButtonMapper()
                last_check = time.monotonic()
                failures = 0
                while not stop.is_set():
                    if time.monotonic() - last_check > 15:
                        last_check = time.monotonic()
                        latest = controllers(timeout=1)
                        if latest != sides:
                            raise OSError("controller roots changed; reconnecting")
                    for raw in ws.messages(timeout=0.25):
                        for action in mapper.feed(raw, sides):
                            if debug:
                                on_status(f"controller press: {action}")
                            on_press(action)
            finally:
                ws.close()
        except (OSError, ValueError) as exc:
            failures += 1
            if failures <= 3 or failures % 10 == 0:
                on_status(f"read-only SteamVR input unavailable: {exc}")
            stop.wait(1.5)
