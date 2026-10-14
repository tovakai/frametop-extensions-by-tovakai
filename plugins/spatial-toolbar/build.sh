#!/usr/bin/env bash
# Build independent OpenVR process in the same developer container as Frametop.
# Never recompiles or restarts ft-screens/SteamVR.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
core=${FRAMETOP_CORE_DIR:-"$HOME/frametop-api"}
if [[ ! -x "$core/scripts/in-box" ]]; then
    echo "toolbar build: set FRAMETOP_CORE_DIR to your installed Frametop fork path" >&2
    exit 1
fi

# The header is API source (Valve OpenVR v2.15.6) pinned exactly as in
# Frametop's legacy screens/build.sh, not an unspecified distribution version.
"$core/scripts/in-box" bash -lc '
set -euo pipefail
cd "$1"
mkdir -p build
if [[ ! -f build/openvr.h ]]; then
  if [[ -f "$HOME/frametop-api/screens/build/include/openvr.h" ]]; then
    cp "$HOME/frametop-api/screens/build/include/openvr.h" build/openvr.h
  else
    curl -fLsS --retry 2 "https://raw.githubusercontent.com/ValveSoftware/openvr/v2.15.6/headers/openvr.h" -o build/openvr.h
  fi
fi
g++ -std=c++17 -O2 -Wall -Wextra -Wno-unused-parameter -Ibuild \
   -o build/ft-toolbar toolbar.cpp \
   -L/opt/steamvr/bin/linuxarm64 -lopenvr_api \
   -Wl,-rpath,/opt/steamvr/bin/linuxarm64
echo "built independent OpenVR toolbar: $PWD/build/ft-toolbar"
' _ "$here"
