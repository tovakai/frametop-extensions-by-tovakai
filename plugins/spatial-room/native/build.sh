#!/usr/bin/env bash
# Build the standalone Steam Frame OpenVR room editor without needing a Frametop source checkout.
# No root, SteamVR restart, host package installation or compositor mutation.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

# Frametop's own build scripts use ~/.local/bin/distrobox because non-interactive
# SteamOS shells may not have that directory on PATH.
if [[ "${1:-}" != "--in-container" && "${FRAME_IN_BOX:-0}" != "1" ]]; then
    distrobox_bin="${DISTROBOX_BIN:-}"
    if [[ -z "$distrobox_bin" && -x "$HOME/.local/bin/distrobox" ]]; then
        distrobox_bin="$HOME/.local/bin/distrobox"
    fi
    if [[ -z "$distrobox_bin" ]]; then
        distrobox_bin=$(command -v distrobox || true)
    fi
    if [[ -z "$distrobox_bin" || ! -x "$distrobox_bin" ]]; then
        echo "Cannot find distrobox; expected ~/.local/bin/distrobox or distrobox on PATH." >&2
        echo "Build on the Steam Frame after setting up Frametop's dev container." >&2
        exit 1
    fi
    exec "$distrobox_bin" enter "${FRAME_BOX:-dev}" -- bash "$root/build.sh" --in-container
fi

cd "$root"
mkdir -p build/include

# Same pinned OpenVR SDK header and SHA-256 Frametop uses (v2.15.6).
# Cache it per extension, so it works regardless of where Frametop was cloned.
header=build/include/openvr.h
expected=1e6ed57199896cc1f7c5484e50fa18955e97be15be690beb28d998c877ead7fd
if ! printf "%s  %s\n" "$expected" "$header" | sha256sum -c --status; then
    part=$(mktemp "$header.XXXXXXXX")
    trap 'rm -f -- "$part"' EXIT
    curl -fsSL --retry 2 "https://raw.githubusercontent.com/ValveSoftware/openvr/v2.15.6/headers/openvr.h" -o "$part"
    printf "%s  %s\n" "$expected" "$part" | sha256sum -c --status || {
        echo "OpenVR header checksum mismatch: refusing to compile." >&2
        exit 1
    }
    mv -- "$part" "$header"
    trap - EXIT
fi

# Steam Frame native ARM64 SteamVR library. Override only for a custom dev environment.
libdir="${OPENVR_LIB:-/opt/steamvr/bin/linuxarm64}"
if [[ ! -f "$libdir/libopenvr_api.so" ]]; then
    echo "Missing SteamVR libopenvr_api.so in $libdir." >&2
    echo "If it lives somewhere else, set OPENVR_LIB=/path/to/library/folder." >&2
    exit 1
fi

g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Wno-unused-parameter \
    -Ibuild/include ft-room-vr.cpp -L"$libdir" -lopenvr_api \
    "-Wl,-rpath,$libdir" -o build/ft-room-vr
echo "Built $root/build/ft-room-vr"
echo "Start with: python3 $root/../session.py"
