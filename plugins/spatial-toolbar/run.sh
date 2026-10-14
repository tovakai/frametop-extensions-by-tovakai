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
# Stale tasks from a crashed previous launch must never be presented as live.
rm -f -- "$runtime/tasks.json"
# Catch missing Pango/Cairo, Start, task tile and profile layout errors BEFORE
# attaching our OpenVR overlays. Never install packages automatically.
echo "Checking salvaged Start, Tasks and Displays rendering in Frametop's container..."
if ! "$core/scripts/in-box" env "XDG_RUNTIME_DIR=/run/user/$(id -u)" \
    python3 "$here/menu.py" render --kind profiles --dir "$runtime" || \
   ! "$core/scripts/in-box" env "XDG_RUNTIME_DIR=/run/user/$(id -u)" \
    python3 "$here/menu.py" render --kind start --dir "$runtime" || \
   ! "$core/scripts/in-box" env "XDG_RUNTIME_DIR=/run/user/$(id -u)" \
    python3 "$here/menu.py" render --kind toolbar --dir "$runtime"; then
    echo "Spatial Toolbar: the original popup renderer failed its preflight." >&2
    echo "If Python 'gi' lacks require_version or Cairo is missing, run:" >&2
    echo "  bash '$here/install-renderer-deps.sh'" >&2
    echo "Then re-run this toolbar; no rebuild or SteamVR restart is needed." >&2
    exit 1
fi
echo "Running the independent Spatial Toolbar. Press Ctrl+C to stop."
echo "Fallback: python3 $here/control.py stop"
# The old KWin watcher must run on the SteamOS host's NESTED Plasma session
# bus, not inside the OpenVR build container. It never edits Frametop core.
task_pid=""
python3 "$here/tasks.py" > "$runtime/tasks.log" 2>&1 &
task_pid=$!
sleep .2
if ! kill -0 "$task_pid" 2>/dev/null; then
    echo "Toolbar task watcher did not start (running app icons unavailable):" >&2
    cat "$runtime/tasks.log" >&2
    task_pid=""
else
    echo "Standalone KWin task provider started (PID $task_pid)."
fi
# Frametop's distrobox wrapper does NOT forward process signals reliably.
# Cleanup both independently owned helpers; do not touch ft-screens/SteamVR.
cleanup() {
    python3 "$here/control.py" stop >/dev/null 2>&1 || true
    if [[ -n "$task_pid" ]]; then
        kill "$task_pid" 2>/dev/null || true
        wait "$task_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
"$core/scripts/in-box" env "XDG_RUNTIME_DIR=/run/user/$(id -u)" \
    "$here/build/ft-toolbar" "$here/menu.py" "$runtime"
