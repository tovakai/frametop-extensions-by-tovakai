#!/usr/bin/env python3
"""Stop only the independent Spatial Toolbar using its extension-owned socket."""
from __future__ import annotations
import argparse
import socket
import sys

ADDRESS = b"\0tovakai_toolbar_control"


def stop_toolbar():
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.sendto(b"stop", ADDRESS)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stop",))
    parser.parse_args(argv)
    try:
        stop_toolbar()
    except OSError as exc:
        print(f"toolbar control: {exc} (toolbar may already be stopped)", file=sys.stderr)
        return 1
    print("Stop requested for the independent Spatial Toolbar only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
