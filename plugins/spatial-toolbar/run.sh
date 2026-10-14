#!/usr/bin/env bash
# Explicit/manual start only; manager v0.1 only stages snapshots.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
core=${FRAMETOP_CORE_DIR:-"$HOME/frametop-api"}
if [[ ! -x "$core/scripts/in-box" ]]; then
  echo "Spatial Toolbar: FRAMETOP_CORE_DIR must point to the running API fork" >&2
  exit 1
fi
if [[ ! -x "$here/build/ft-toolbar" ]]; then
  echo "Spatial Toolbar: build first with bash plugins/spatial-toolbar/build.sh" >&2
  exit 1
fi

# Refuse to launch an interactive overlay against a non-API Frametop instance.
if ! PYTHONPATH="$here/../../sdk" python3 -c '
from frametop_ext import Frametop
ft = Frametop()
assert ft.api_version() >= 1
assert {"screen.status","screen.move","screen.opacity"} <= set(ft.capabilities())
' ; then
    echo "Spatial Toolbar: running Frametop extension API v1 is required." >&2
    exit 1
fi

runtime="/run/user/$(id -u)/frametop-spatial-toolbar"
mkdir -p -- "$runtime"
chmod 700 -- "$runtime"
# Only this independent plugin is stopped by Ctrl+C. No Frametop restart.
exec 9>"$runtime/lock"
if ! flock -n 9; then
    echo "Spatial Toolbar already running; refusing duplicate overlay keys." >&2
    exit 1
fi
echo "Running the independent Displays toolbar. Press Ctrl+C to stop."
echo "Fallback: python3 $here/control.py stop"
# Frametop's distrobox wrapper does NOT forward process signals reliably.
# On every launcher exit, ask the plugin process itself to dispose its overlays.
trap 'python3 "$here/control.py" stop >/dev/null 2>&1 || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"$core/scripts/in-box" env "XDG_RUNTIME_DIR=/run/user/$(id -u)" \
    "$here/build/ft-toolbar" "$here/menu.py" "$runtime"
