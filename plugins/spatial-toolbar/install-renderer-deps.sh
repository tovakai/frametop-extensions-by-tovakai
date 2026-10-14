#!/usr/bin/env bash
# Explicit opt-in: install original toolbar painter's Python libraries into
# Frametop's Fedora distrobox ONLY. No changes to host SteamOS or core source.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
core=${FRAMETOP_CORE_DIR:-"$HOME/frametop-api"}
if [[ ! -x "$core/scripts/in-box" ]]; then
  echo "renderer-deps: Frametop container launcher missing: $core/scripts/in-box" >&2
  exit 1
fi
echo "Installing original Pango/Cairo popup dependencies into Frametop's Fedora container."
echo "This does not touch the SteamOS host or the Frametop source tree."
"$core/scripts/in-box" bash -lc '
set -euo pipefail
sudo -n dnf install -y python3-gobject python3-cairo pango gdk-pixbuf2 gdk-pixbuf2-modules-extra librsvg2-tools
python3 -c "import gi; assert callable(gi.require_version); gi.require_version(\"Pango\", \"1.0\"); gi.require_version(\"PangoCairo\", \"1.0\"); gi.require_version(\"GdkPixbuf\", \"2.0\"); from gi.repository import Pango, PangoCairo, GdkPixbuf; import cairo; print(\"Pango/Cairo/GdkPixbuf renderer dependencies OK\")"
'
