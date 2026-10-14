#!/bin/bash
# Runs on the Frame host (not in the container). Starts a Plasma desktop with several
# screens, each its own SteamVR panel. Modeled on /usr/bin/steamos-nested-desktop, which
# does the same with one screen in gamescope.
#
# Backends (BACKEND in ~/.config/frametop.conf):
#   screens    (default) ft-screens (screens), our own compositor: KWin opens a
#              window per screen, ft-screens gives each its size (from the layout, see
#              layout) and shows it as its own panel. Any resolution and shape.
#   gamescope  gamescope in PerWindow mode: every screen one size, at most 1920x1080
#              worth of pixels, panels owned by the SteamVR dashboard.
#
# Settings come from ~/.config/frametop.conf (see frametop.conf.example) and, for the
# screens backend, ~/.config/frametop-layout.json (Frametop Display Settings writes both).
# FT_BACKEND, FT_SCREENS, FT_WIDTH, FT_HEIGHT, and FT_PHYS_WIDTH override them.
set -eu

here=$(dirname "$(readlink -f "$0")")

# Started from the VR launcher, the desktop inherits the Steam client's environment. Apps in
# it should see the system as a normal login does, so drop the client's runtime: its
# LD_LIBRARY_PATH put Steam's own libraries ahead of the system's (Steam's libavcodec has no
# H.264 decoder, so VLC couldn't play most videos), and its overlay and launch settings are
# meant for games. SteamOS's own defaults (/usr/share/deckard/mesavars.sh) stay. The
# gamescope session also puts QT_IM_MODULE=xim and GTK_IM_MODULE=xim in the systemd user
# environment, and with those, Qt and GTK apps never tell KWin a text field has focus, so
# Frametop's keyboard (input/ft-textinput) never opens for them.
for var in $(compgen -e); do
  case $var in
    LD_LIBRARY_PATH | LD_PRELOAD | STEAM_* | Steam* | SRT_* | PRESSURE_VESSEL_* | MANGOHUD_* | \
      ENABLE_VK_LAYER_VALVE_steam_overlay_* | STEAMVIDEOTOKEN | QT_IM_MODULE | GTK_IM_MODULE | \
      XMODIFIERS) unset "$var" ;;
  esac
done

conf=$HOME/.config/frametop.conf
BACKEND=screens SCREENS=2 WIDTH=1920 HEIGHT=1080 PHYS_WIDTH=1.6 REMOTE=0 FLOAT_SLOTS=8 FLOAT_MARGIN=300
# shellcheck disable=SC1090
[ -f "$conf" ] && . "$conf"
backend=${FT_BACKEND:-$BACKEND}
screens=${FT_SCREENS:-$SCREENS}
width=${FT_WIDTH:-$WIDTH}
height=${FT_HEIGHT:-$HEIGHT}
phys_width=${FT_PHYS_WIDTH:-$PHYS_WIDTH}
remote=${FT_REMOTE:-$REMOTE}
# Spare KWin outputs for floating windows (docs/floating-windows.md). Changing FLOAT_SLOTS
# needs a desktop restart. Zero when not using ft-screens.
float_slots=${FT_FLOAT_SLOTS:-$FLOAT_SLOTS}
[[ $float_slots =~ ^[0-9]+$ ]] || float_slots=8
[ "$float_slots" -le 16 ] || float_slots=16
[ "$backend" = screens ] || float_slots=0
if [ "$backend" = gamescope ] && [ $((width * height)) -gt $((1920 * 1080)) ]; then
  # gamescope's VR backend aborts above 1920x1080 worth of pixels (its upload buffer;
  # see docs/design.md). Shrink a bigger size to fit, keeping its shape.
  read -r width height < <(awk -v w="$width" -v h="$height" 'BEGIN { k = sqrt(1920 * 1080 / (w * h));
    printf "%d %d\n", int(w * k / 8) * 8, int(h * k / 8) * 8 }')
  echo "frametop: resolution too big for gamescope's VR mode; using ${width}x${height}" >&2
fi

if [ "${1:-}" != --inner ]; then
  # One instance at a time. The launcher can be clicked twice.
  if pgrep -f '[v]r-overlay-key frametop ' >/dev/null || pgrep -x ft-screens >/dev/null; then
    echo "Frametop is already running" >&2
    exit 0
  fi
  set -a; . /usr/share/deckard/mesavars.sh; set +a
  # Flatpak apps (Chromium) publish their launcher entries under the Flatpak
  # exports dirs. SSH and launcher environments may lack XDG_DATA_DIRS, and then
  # Plasma can't find them and opens Discover instead.
  export XDG_DATA_DIRS=${XDG_DATA_DIRS:-/usr/local/share:/usr/share}
  set +u; . /etc/profile.d/flatpak.sh; set -u
  # Arrange the screens in the saved layout once they're up (layout; skipped
  # when auto-arrange is off).
  setsid "$here/../layout/ft-layout" apply --wait 90 > /tmp/frametop-layout.log 2>&1 < /dev/null &

  if [ "$backend" = gamescope ]; then
    export ENABLE_GAMESCOPE_WSI=1 GAMESCOPE_MANGOAPP_SOCKET_DISABLE=1
    exec gamescope --backend openvr --virtual-connector-strategy PerWindow \
      -W "$width" -H "$height" -w "$width" -h "$height" \
      --vr-overlay-key frametop --vr-overlay-default-name frametop \
      --vr-overlay-physical-width "$phys_width" \
      --vr-overlay-show-immediately --vr-overlay-enable-click-stabilization \
      --vr-overlay-enable-control-bar --vr-overlay-enable-control-bar-keyboard \
      --expose-wayland \
      --cursor-hotspot 5,3 --cursor /usr/share/steamos/steamos-cursor.png \
      -- "$0" --inner
  fi

  # ft-screens runs in the dev container (it's built against Fedora's wlroots); KWin and
  # Plasma stay on the host and connect to its socket.
  socket=ft-screens-0
  read -ra screen_args <<< "$("$here/../layout/ft-layout" screen-args)"
  export FT_SCREEN_COUNT=$(( ${#screen_args[@]} / 2 )) FT_FLOAT_SLOTS=$float_slots
  
  "$here/../scripts/container-up.sh"  # not owned by this desktop, or stopping it would stop the container
  "$HOME/.local/bin/distrobox" enter dev -- "$here/../screens/build/ft-screens" --socket "$socket" \
    "${screen_args[@]}" --spares "$float_slots" > /tmp/frametop-screens.log 2>&1 < /dev/null &
  stop_screens() { pkill -x ft-screens 2>/dev/null || true; }
  trap stop_screens EXIT
  for _ in $(seq 100); do [ -S "$XDG_RUNTIME_DIR/$socket" ] && break; sleep 0.2; done
  [ -S "$XDG_RUNTIME_DIR/$socket" ] || { echo "ft-screens didn't start (see /tmp/frametop-screens.log)" >&2; exit 1; }
  WAYLAND_DISPLAY=$XDG_RUNTIME_DIR/$socket "$0" --inner
  exit
fi

# Inside the host compositor (ft-screens or gamescope) from here on. The desktop isn't a
# gamescope client with ft-screens, so the gamescope session's Vulkan layer stays off, and
# the gamescope session's portal config isn't Plasma's.
[ "$backend" = gamescope ] || unset ENABLE_GAMESCOPE_WSI
unset XDG_DESKTOP_PORTAL_DIR
[ "$backend" = gamescope ] || screens=${FT_SCREEN_COUNT:-$screens}

host_runtime=$XDG_RUNTIME_DIR
runtime=$host_runtime/frametop

cleanup() {
  pkill -f '[k]rdpserver --plasma' 2>/dev/null || true
  pkill -f '[X]vnc :20 ' 2>/dev/null || true
  pkill -f '[x]freerdp /v:.*:3390' 2>/dev/null || true
  fusermount3 -u -z "$runtime/doc" 2>/dev/null || true
  umount --recursive "$runtime" 2>/dev/null || true
  rm -rf "$runtime"
}
trap cleanup EXIT
cleanup
mkdir -m 0700 "$runtime" "$runtime/pulse" "$runtime/bin"
ln -s "$host_runtime/pulse/native" "$runtime/pulse/native"
ln -s "$host_runtime"/pipewire* "$runtime/"

# plasma-session starts KWin through kwin_wayland_wrapper. Shadow it to add our outputs
# (desktop screens plus spare slots for floating windows).
# With ft-screens the size is only the starting one: ft-screens sets each screen's own.
# Our input method tells the input relay when a text field has focus, for Frametop's
# keyboard (input/ft-textinput).
textinput=$(readlink -f "$here/../input/ft-textinput")
cat > "$runtime/bin/kwin_wayland_wrapper" <<EOF
#!/bin/sh
exec /usr/bin/kwin_wayland_wrapper --width $width --height $height --output-count $((screens + float_slots)) --no-lockscreen \\
  --inputmethod $textinput "\$@"
EOF
chmod +x "$runtime/bin/kwin_wayland_wrapper"
export PATH=$runtime/bin:$PATH

# Keep the host compositor's Wayland socket reachable after moving XDG_RUNTIME_DIR.
case ${WAYLAND_DISPLAY:-gamescope-0} in
  /*) ;;
  *) export WAYLAND_DISPLAY=$host_runtime/${WAYLAND_DISPLAY:-gamescope-0} ;;
esac
export XDG_RUNTIME_DIR=$runtime

# Separate Plasma/KWin config and state, so this session and the built-in
# desktop never overwrite each other's screen layout or panels.
export XDG_CONFIG_HOME=$HOME/.config/frametop
export XDG_STATE_HOME=$HOME/.local/state/frametop
mkdir -p "$XDG_CONFIG_HOME" "$XDG_STATE_HOME"

# Remote desktop over VNC: session/remote-desktop.sh captures the desktop with
# krdp on 127.0.0.1, and session/vnc-bridge.sh re-serves it over VNC. krdpserver runs from the container, so KWin can't
# match it to an installed app. KWin's permission check for screencast and fake
# input is turned off for this nested session only.
if [ "$remote" = 1 ]; then
  export KWIN_WAYLAND_NO_PERMISSION_CHECKS=1
  "$here/remote-desktop.sh" "$runtime" > /tmp/frametop-remote.log 2>&1 &
  "$here/vnc-bridge.sh" "$width" "$height" > /tmp/frametop-vnc.log 2>&1 &
fi

# Marker for ft-shell-watch: when this file disappears (cleanup), stop respawning plasmashell.
touch "$runtime/session-active"

# ft-floatd (floating windows) runs inside the Plasma session, on its D-Bus: started from
# the session's autostart, which only this desktop reads (XDG_CONFIG_HOME above).
autostart=$XDG_CONFIG_HOME/autostart/frametop-floatd.desktop
if [ "$float_slots" -gt 0 ]; then
  mkdir -p "$(dirname "$autostart")"
  cat > "$autostart" <<EOF
[Desktop Entry]
Type=Application
Name=Frametop floating windows
Exec=sh -c 'exec "$here/../float/ft-floatd" --screens $screens --slots $float_slots > /tmp/frametop-floatd.log 2>&1'
X-KDE-autostart-phase=2
NoDisplay=true
EOF
else
  rm -f "$autostart"
fi

# Launch as Standalone in every app's right-click menu (float/ft_apps.py): copies of the
# apps' desktop files with that action, first in XDG_DATA_DIRS, so only this desktop sees
# them. Written now, before Plasma reads them; ft-floatd keeps them up to date.
if [ "$float_slots" -gt 0 ]; then
  python3 "$here/../float/ft_apps.py" >/dev/null 2>&1 || true
  export XDG_DATA_DIRS=$HOME/.local/share/frametop/apps:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}
fi

# With floating windows, the session's windows get Frametop's own decoration: Breeze's look
# plus a float button left of Close (decoration/). Copied, not linked. Desktop Mode keeps
# its own kwinrc / Breeze.
deco=kwin4_decoration_qml_frametop
deco_dir=${XDG_DATA_HOME:-$HOME/.local/share}/kwin/decorations/$deco
kwinrc=$XDG_CONFIG_HOME/kwinrc
if [ "$float_slots" -gt 0 ]; then
  rm -rf "$deco_dir" "$deco_dir"_try*
  mkdir -p "$(dirname "$deco_dir")"
  cp -r "$here/../decoration" "$deco_dir"
  rm -f "$deco_dir/apply.sh"
  kwriteconfig6 --file "$kwinrc" --group org.kde.kdecoration2 --key library org.kde.kwin.aurorae
  kwriteconfig6 --file "$kwinrc" --group org.kde.kdecoration2 --key theme "$deco"
elif [ "$(kreadconfig6 --file "$kwinrc" --group org.kde.kdecoration2 --key theme 2>/dev/null)" = "$deco" ]; then
  kwriteconfig6 --file "$kwinrc" --group org.kde.kdecoration2 --key library --delete
  kwriteconfig6 --file "$kwinrc" --group org.kde.kdecoration2 --key theme --delete
fi

# Private D-Bus session (no systemd1 on this bus — Plasma falls back to direct launches).
# Watchdog starts first, waits for the real nested plasmashell, then snapshots its /proc
# environ (wayland-0 under …/frametop) for respawns — never the pre-Plasma outer display.
# ft-mpris bridges session MPRIS players to @frametop_mpris for the Media instrument.
# ft-launch bridges Launcher instrument activations to nested Plasma (@frametop_launch).
# ft-taskbar feeds the spatial toolbar (tasks from nested KWin, Start, profiles, tray).
# Drop any leftover bridge from a prior session (abstract socket is exclusive).
pkill -f '[p]ython3 .*/ft-mpris.py' 2>/dev/null || true
pkill -f '[p]ython3 .*/ft-launch.py' 2>/dev/null || true
# argv0 match: a looser pattern also hits this script's own dbus-run-session command line.
pkill -f '^ft-taskbar ' 2>/dev/null || true
dbus-run-session -- bash -c '
  set -eu
  here=$1
  python3 "$here/ft-mpris.py" > /tmp/frametop-mpris.log 2>&1 &
  mpris=$!
  # argv0 ft-launch (≤15 chars) so keep-apps / pgrep -x can find it.
  bash -c "exec -a ft-launch python3 \"$here/ft-launch.py\"" > /tmp/frametop-launch.log 2>&1 &
  launch=$!
  bash -c "exec -a ft-taskbar python3 \"$here/ft-taskbar.py\"" > /tmp/frametop-taskbar.log 2>&1 &
  taskbar=$!
  bash "$here/ft-shell-watch.sh" &
  watch=$!
  set +e
  startplasma-wayland
  status=$?
  set -e
  kill "$mpris" 2>/dev/null || true
  kill "$launch" 2>/dev/null || true
  kill "$taskbar" 2>/dev/null || true
  kill "$watch" 2>/dev/null || true
  wait "$mpris" 2>/dev/null || true
  wait "$launch" 2>/dev/null || true
  wait "$taskbar" 2>/dev/null || true
  wait "$watch" 2>/dev/null || true
  exit "$status"
' bash "$here"
