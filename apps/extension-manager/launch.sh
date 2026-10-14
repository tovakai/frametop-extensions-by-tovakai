#!/usr/bin/env bash
# Launch manager from SteamOS or Frametop nested Plasma, using core's existing box.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)

if python3 -c 'from PySide6.QtGui import QGuiApplication; from PySide6.QtQml import QQmlApplicationEngine' >/dev/null 2>&1; then
    exec python3 "$here/gui.py" "$@"
fi

# Follow the active Steam desktop installation; core is never modified.
launcher="$HOME/.local/share/applications/deckard-nested-desktop.desktop"
session=$(sed -n 's/^Exec=//p' "$launcher" 2>/dev/null | head -1)
core=${session%/session/frametop-session.sh}
if [[ "$core" == "$session" || ! -x "$core/scripts/in-box" ]]; then
    echo "Frametop Extension Manager: no host PySide6 and active Frametop container not found." >&2
    echo "Use: python3 $here/manager.py catalog" >&2
    exit 1
fi

wl=${WAYLAND_DISPLAY:-wayland-0}
case "$wl" in /*) ;; *) wl="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/$wl" ;; esac
nested_bus=${DBUS_SESSION_BUS_ADDRESS:-}
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
exec "$core/scripts/in-box" env \
    WAYLAND_DISPLAY="$wl" DISPLAY="${DISPLAY:-}" \
    XAUTHORITY="${XAUTHORITY:-}" \
    DBUS_SESSION_BUS_ADDRESS="$nested_bus" \
    QT_QPA_PLATFORM="wayland;xcb" \
    python3 "$here/gui.py" "$@"
