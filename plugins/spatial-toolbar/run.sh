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
exec "$core/scripts/in-box" env "XDG_RUNTIME_DIR=/run/user/$(id -u)" \
    "$here/build/ft-toolbar" "$here/menu.py" "$runtime"
