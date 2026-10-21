#!/usr/bin/env bash
# Compile the standalone OpenVR editor against Frametop's pinned SDK.
# No root, install, SteamVR restart, or desktop mutation.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
frametop=${FRAMETOP_ROOT:-"$HOME/frametop"}
if [[ ! -f "$frametop/scripts/openvr.sh" ]]; then
    echo "Missing Frametop pinned OpenVR SDK: $frametop/scripts/openvr.sh" >&2
    exit 1
fi
if [[ "${1:-}" != "--in-container" ]]; then
    if ! command -v distrobox >/dev/null; then
        echo "Run on Steam Frame with Frametop dev distrobox installed." >&2
        exit 1
    fi
    exec distrobox enter dev -- bash "$here/build.sh" --in-container
fi
cd "$here"
mkdir -p build/include
# shellcheck disable=SC1090
source "$frametop/scripts/openvr.sh"
g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Wno-unused-parameter \
    $OPENVR_CFLAGS ft-room-vr.cpp $OPENVR_LIBS -o build/ft-room-vr
echo "Built $here/build/ft-room-vr"
echo "Start with: python3 $here/../session.py"
