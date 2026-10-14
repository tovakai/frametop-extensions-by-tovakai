#!/usr/bin/env bash
# Reversible user-level settings app entry; never edits Frametop core or system files.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
app="$root/apps/extension-manager"
target="$HOME/.local/share/applications/frametop-extension-manager.desktop"
action=${1:-install}
case "$action" in
    install)
        test -f "$app/gui.py" && test -f "$app/main.qml" && test -f "$app/manager_core.py" ||
            { echo "Incomplete extension-manager checkout" >&2; exit 1; }
        command -v python3 >/dev/null || { echo "Python3 is required" >&2; exit 1; }
        mkdir -p -- "$(dirname "$target")"
        if test -e "$target" && ! grep -q '^X-Frametop-Extension-Manager=1$' "$target"; then
            echo "Refusing to replace someone else's desktop entry: $target" >&2; exit 1
        fi
        # Exec invokes Bash explicitly: files added by GitHub Contents API are
        # mode 0644, and installation must not require chmod or git metadata.
        cat > "$target" <<EOF
[Desktop Entry]
Type=Application
Name=Frametop Extensions
GenericName=Manage Frametop extensions
Comment=Find, review, install, update and remove optional Frametop extensions
Exec=/usr/bin/bash "$app/launch.sh"
Icon=preferences-plugin
Terminal=false
Categories=Settings;System;
Keywords=frametop;extension;plugin;settings;repository;
X-Frametop-Extension-Manager=1
EOF
        echo "Installed Frametop Extensions settings app: $target"
        echo "Launch from Plasma's Settings applications, or run:"
        echo "  bash '$app/launch.sh'"
        echo "No plugins, services or Frametop settings have been changed."
        ;;
    uninstall)
        if test -f "$target" && grep -q '^X-Frametop-Extension-Manager=1$' "$target"; then
            rm -- "$target"
            echo "Removed extension manager application shortcut."
        else
            echo "No manager-owned desktop entry to remove."
        fi
        echo "Repository sources, installed extension snapshots, and settings were retained."
        ;;
    *)
        echo "Usage: bash apps/extension-manager/install.sh [install|uninstall]" >&2
        exit 2
        ;;
esac
