#!/usr/bin/env bash
# Run Spatial Room within the same dev container used to build its native OpenVR frontend.
# No background service, no auto-install, no SteamVR restart.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ "${FRAME_IN_BOX:-0}" == "1" || "${1:-}" == "--in-container" ]]; then
    if [[ "${1:-}" == "--in-container" ]]; then shift; fi
    exec python3 "$root/session.py" "$@"
fi
distrobox_bin="${DISTROBOX_BIN:-}"
if [[ -z "$distrobox_bin" && -x "$HOME/.local/bin/distrobox" ]]; then
    distrobox_bin="$HOME/.local/bin/distrobox"
fi
if [[ -z "$distrobox_bin" ]]; then distrobox_bin=$(command -v distrobox || true); fi
if [[ -z "$distrobox_bin" || ! -x "$distrobox_bin" ]]; then
    echo "Cannot find distrobox; expected ~/.local/bin/distrobox or distrobox on PATH." >&2
    exit 1
fi
box="${FRAME_BOX:-dev}"
if [[ ! "$box" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
    echo "Invalid container name: $box" >&2
    exit 2
fi
# Where available, Frametop starts its container in an independent user systemd
# scope so it stays alive after this CLI exits. These are optional paths, not requirements.
for frametop_root in "${FRAMETOP_ROOT:-}" "$HOME/dev/frametop" "$HOME/frametop"; do
    [[ -n "$frametop_root" && -f "$frametop_root/scripts/container-up.sh" ]] || continue
    XDG_RUNTIME_DIR="/run/user/$(id -u)" bash "$frametop_root/scripts/container-up.sh" "$box"
    break
done
exec "$distrobox_bin" enter "$box" -- python3 "$root/session.py" "$@"
