# Spatial Toolbar v0.1.0: full interactive shell restoration (experimental)

The independent OpenVR prototype has been extended following the first **actual
Steam Frame device test**. That test confirmed the old Displays-only prototype
rendered but was missing Start, running tasks and a drag handle. This revision
addresses those missing pieces; **the revised build still needs a new hardware
test**.

Implemented in the standalone process:

- **Start:** the original four-square glyph, its own correctly scaled
  clickable OpenVR tile, and the salvaged Pango/Cairo application grid,
  category chips and pages. Activates apps via Frametop's existing
  `@frametop_launch` nested-desktop service.
- **Running tasks:** the preserved KWin D-Bus scripting watcher now runs as
  an independent **SteamOS-host helper**, never edits Frametop's session.
  `ft_taskbar_model.merge_tasks` maps its windows to app IDs, and the salvaged
  Cairo renderer paints individual 128x128 RGBA app-icon tiles. The toolbar
  checks for task-feed changes every two seconds, pools the OpenVR overlay
  handles, and updates the actual model's packing. Clicking a task focuses or
  minimizes its window. Multiple windows currently focus the first; the
  original chooser is a later slice. Default pinned apps are not yet restored.
- **Displays:** the existing original profile popup and 450 ms switching
  adapter remain intact.
- **Grab handle:** a visible pale pill underneath the bar, with its own
  OpenVR hitbox, grabs a valid controller pose on trigger-down and updates
  the entire toolbar's spatial transform until release. Scroll adjusts
  controller-relative depth while dragging.
- **Input policy:** the arched dark backing stays NON-interactive. Every
  real control owns a separate OpenVR mouse overlay with texture-accurate
  mouse scale; blank bar areas **should** be click-through. Never replace
  this with a giant, invisible blocking surface.
- **Isolation:** opt-in running process and host task helper; no core
  modifications, SteamVR dashboard reparenting, Frametop restart or service
  autostart. Private stop control cleans up our overlays.

Not restored yet: original tray (Wi-Fi / volume), right-click task context
menu, multi-window chooser, profile rename GUI, pinned apps, per-frame soft
follow, or screen docking. Those remain separate slices, not dummy controls.

## Next hardware test

From the same test worktree, once the branch is updated:

```sh
cd ~/frametop-toolbar-test
git fetch origin feature/toolbar-openvr-host
git switch --detach origin/feature/toolbar-openvr-host
bash plugins/spatial-toolbar/build.sh
bash plugins/spatial-toolbar/run.sh
```

Verify that **Start**, **running task icons**, **Displays**, and the **grab
pill** appear as individual interactive controls. Try Start → Applications →
launch an app; change between saved Displays profiles; drag the pill to move
the bar. Missing task icons can indicate the standalone KWin watcher couldn't
connect to the *nested* Plasma session D-Bus. Inspect the independent log:

```sh
cat /run/user/$(id -u)/frametop-spatial-toolbar/tasks.log
```

This helper is launched by `run.sh` and stopped automatically on exit. It
is intentionally never run from the OpenVR Fedora box, since the nested KWin
session bus belongs to the SteamOS host.

### Startup speed and nested KWin D-Bus (second device iteration)

The first hardware test with Start restored found two independent problems:

1. **Slow Start/category switches.** The original extracted `menu.py` used
   two nested Python loops over each rendered Cairo image to swap BGRA to RGBA.
   Now it uses memoryview/bytearray extended channel slices implemented in
   native code, preserving the exact colors and alpha. Its smoke test converts
   a 700×900 surface in milliseconds. The Python menu adapter also keeps an
   atomic 60-second on-disk catalog of FreeDesktop applications so every
   category click doesn't rescan the entire installed application tree.
   Icons are still rendered through the original Cairo/Pango painter.

2. **No running apps from KWin** with
   `org.freedesktop.DBus.Error.ServiceUnknown: The name is not activatable`.
   The core's nested Plasma runs in a separate `dbus-run-session`, not the
   host D-Bus inherited by SSH or the outer terminal. The standalone watcher
   now reads the **existing nested KWin process's** limited environment
   (only bus address, Wayland display and nested runtime) and connects
   explicitly to that bus after checking `org.kde.KWin` owns its name.
   It does not launch/modify KWin, create a new bus, or change Frametop core.
   It retries briefly if Plasma is still starting.

To check the task watcher after this update:

```sh
cat /run/user/$(id -u)/frametop-spatial-toolbar/tasks.log
```

Expected: `using nested Frametop KWin private session bus`, then
`KWin task script loaded`. If those appear but task icons do not,
check whether `tasks.json` is receiving the actual window list.

For opt-in **timings** of subsequent Start/category renders:

```sh
FT_TOOLBAR_TRACE=1 bash plugins/spatial-toolbar/run.sh
```

The terminal prints time spent in app discovery/layout, Cairo painting,
and RGBA conversion/file writes separately; this doesn't change core state.

### Warm menu rendering: third device iteration

The first optimization (Cairo BGRA→RGBA slicing + disk app catalog) removed
expensive image conversion, but Start/category switching still launched
`python3 menu.py` separately for each controller click. Worse, changing a
category waited synchronously for one Python activation and then another cold
renderer launch. The OpenVR thread was blocked throughout.

The independent toolbar now starts **one persistent Cairo/Pango renderer** in
its existing Fedora container (`menu_worker.py`), reusing the original popup
painter, loaded typelibs, icon caches and catalog across requests. The host
talks to the renderer over `menu.sock` in the toolbar's private 0700 runtime
directory. A request has a strict whitelist (render / activate / ping / stop),
is bounded and has a 3-second timeout, never shells out to the user input, and
never alters Frametop's core. Start/profile content and the original visual
design remain unchanged.

- **Opening a menu** waits for the warm renderer instead of forking Python.
- **Changing Start category/page** uses two short socket requests to the same
  warm process. The original model handles category selection and pagination.
- **Launching an app/profile selection** queues an activation without blocking
  the OpenVR loop for the launch itself.
- **Running-task refresh** uses the same worker and keeps the pooled overlay
  handles, rather than repeatedly starting Python.
- **Closing the launcher** sends a private worker stop command, so no always-on
  orphan service or compositor restart is required.

For performance diagnostics run with `FT_TOOLBAR_TRACE=1`, then view:

```sh
cat /run/user/$(id -u)/frametop-spatial-toolbar/menu.log
```

This now includes warm worker request times and the original breakdown of
catalog/layout, Cairo painting and RGBA/file writes. The log helps distinguish
Python rendering from OpenVR texture upload latency.

**This new version changes toolbar.cpp. Rebuild before hardware testing.**

### Seamless Start category switches (fourth device iteration)

The latest device feedback confirmed that Start is responsive, but category
selection visibly flashed the popup away for a frame. The warm-renderer change
fixed menu generation latency; the remaining issue was presenting a new raw
texture directly on the already-visible OpenVR popup overlay.

The toolbar now uses **two pooled OpenVR popup handles**. On a Start
category/page change, it renders the replacement into the *hidden* overlay,
updates its exact mouse scale and pose, presents it above the current menu,
and leaves the old image visible underneath for 55 ms. The old overlay
becomes **non-interactive immediately**, so it cannot block pointer clicks
behind the new menu. The background toolbar remains click-through.
The original overlay is then hidden, not destroyed, and is reused for the
next page.

If the replacement render, upload or presentation fails, the old popup remains
visible and usable. Fast repeated selections reclaim the retired overlay
without ever writing the active overlay's texture. Both handles are hidden
when the menu closes or SteamVR Dashboard takes over.

**Requires a new C++ build:**

```sh
cd ~/frametop-toolbar-test
git fetch origin feature/toolbar-openvr-host
git switch --detach origin/feature/toolbar-openvr-host
bash plugins/spatial-toolbar/build.sh
bash plugins/spatial-toolbar/run.sh
```

Check that Start stays continuously visible while selecting categories and
paging, that only the currently displayed page responds to clicks, and that
opening/closing Start and Displays still works. This behavior is covered by
offline regression and C++ syntax tests but needs Steam Frame visual
verification before merging the experimental toolbar branch.

### Upstream-style grab handle and thumbstick depth dragging

The Steam Frame hardware feedback confirmed the toolbar grab handle can move
the toolbar, but its initial bright-blue chunky pill didn't match upstream
Frametop's display grab bars, and it could not push/pull the toolbar with
the thumbstick while holding the controller trigger.

The **standalone toolbar** now copies the actual upstream
[Frametop grab chrome and Push() geometry](https://github.com/Frametop/frametop/blob/main/screens/vr.cpp)
without modifying the Frametop core:

- 256 × 24 pill texture, 0.30 m wide; translucent light grey when idle,
  blue while hovered or carried. Matches upstream `BarTexture()`.
- The grab overlay opts into `VROverlayFlags_SendVRDiscreteScrollEvents`
  and handles `VREvent_ScrollDiscrete` **while held**. On Steam Frame,
  thumbstick up/down should send repeating scroll notches through OpenVR
  while held, just like upstream's screen grab bar.
- `push_drag` applies upstream's head-to-panel distance scaling:
  `next = clamp(current * (1 + 0.08 * notches), 0.3 m, 10 m)`.
  The headset-to-toolbar vector determines push direction, **not**
  the controller's local axis.
- After each depth step the saved controller-relative grip offset is
  recalculated, preserving arm movement and reducing jumping.
- The static overlay key, mouse scale, and 16 ms tracking loop stay intact;
  textures are uploaded only when the grip's highlight actually changes.

The source compile and unit regression tests validate the geometry and
event contract. Device testing is still required to confirm SteamVR routes
repeating held-thumbstick scroll to this standalone overlay.

**Requires a rebuild** in your current isolated test worktree:

```sh
cd ~/frametop-toolbar-test
git fetch origin feature/toolbar-openvr-host
git switch --detach origin/feature/toolbar-openvr-host
bash plugins/spatial-toolbar/build.sh
bash plugins/spatial-toolbar/run.sh
```

Test moving the toolbar by dragging the grey pill, then **keep holding the
grab trigger** and hold the thumbstick forward/backward. The bar should
move toward/away from your head, and stay in its new world position when
you release. The pill should glow blue while active and return to light
grey when released. If thumbstick scroll never arrives, the next hardware
diagnostic is to log grab-overlay scroll events rather than guessing at an
OpenVR action binding.

### Running task icons: recovery beyond Start-menu matching

Some valid applications appear in the taskbar as two-letter placeholders
(e.g. **IN**). This is the *last-resort* label from the legacy task tile
painter, not a deliberate icon. The original app matching only looked at
entries exposed to the Start menu, and the extracted painter could decode
PNGs but not common SVG/JPEG/XPM icons.

The independent extension now builds an icon candidate list for each
running application from **KWin's `desktopFileName` and `resourceClass`**
as well as any matched Start entry. It resolves actual `.desktop`
metadata even when `OnlyShowIn` excluded that application from the Start
menu, then tries the real `Icon=` and alternative theme names.
Flatpak/host absolute paths are translated through the distrobox
`/run/host` mount when needed. The painter now rasterizes icons through
GdkPixbuf (or `rsvg-convert` for SVG); task overlays continue using the
existing pooled handles.

**One-time opt-in container dependency refresh**, to make sure the Fedora
renderer can decode SVG and XPM as well as PNG:

```sh
cd ~/frametop-toolbar-test
git fetch origin feature/toolbar-openvr-host
git switch --detach origin/feature/toolbar-openvr-host
bash plugins/spatial-toolbar/install-renderer-deps.sh
```

The installer modifies only the existing Frametop **Fedora dev container**,
not SteamOS or the Frametop core. Then **restart the standalone toolbar**
so its warm renderer reloads GdkPixbuf:

```sh
bash plugins/spatial-toolbar/run.sh
```

No C++ rebuild is needed for this icon-only change.

If a task still shows initials, the renderer reports the missing icon identity
and the names it tried **once per application**:

```sh
grep 'unresolved task icon' /run/user/$(id -u)/frametop-spatial-toolbar/menu.log
```

That output identifies cases needing an exact app-specific icon mapping.
It does not include full window captions or the contents of applications.

### Original popup renderer dependencies

The legacy toolbar's Pango/Cairo painter originally ran on the **SteamOS
host**. This independent OpenVR build runs it inside Frametop's existing
Fedora distrobox, where the original container package list did not include
the PyGObject/Cairo Python bindings. This can manifest as
`AttributeError: module 'gi' has no attribute 'require_version'`.

One-time, explicitly install the Fedora packages **inside the distrobox**:

```sh
cd ~/frametop-toolbar-test
bash plugins/spatial-toolbar/install-renderer-deps.sh
```

This is a deliberate, opt-in package change **to the dev container only**,
not SteamOS and not Frametop core source. The script checks the actual
`gi.require_version`, Pango/PangoCairo and `cairo` imports afterward.
The regular `run.sh` performs a popup render preflight before OpenVR startup
and explains how to install the missing dependencies; it will never run
`dnf` or `sudo` itself.

No C++ rebuild or SteamVR restart is required when adding these Python
renderer packages.

## First Frame hardware test (without changing your main checkout)

```sh
cd ~/frametop-extensions
git fetch origin feature/toolbar-openvr-host
git worktree add --detach ~/frametop-toolbar-test origin/feature/toolbar-openvr-host

cd ~/frametop-toolbar-test
bash plugins/spatial-toolbar/build.sh
bash plugins/spatial-toolbar/run.sh
```

Requirements: running Frametop API core and SteamVR on the Frame, with
`~/frametop-api` as the API fork checkout. If it lives elsewhere, set
`FRAMETOP_CORE_DIR` to that path. The build runs in **Frametop's existing
distrobox**, compiles only `toolbar.cpp`, and links against SteamVR's
ARM64 `libopenvr_api` using the same pinned Valve OpenVR header as the
legacy fork. It never builds/restarts `ft-screens`.

The bar should initially appear around 75 cm ahead and 40 cm below
eye level. It stays world-anchored after you release the grab handle. The
passive backing **does not** capture controller clicks; aim at an actual
tile. Press **Ctrl+C** in the launching terminal to stop the overlay.
Because distrobox doesn't always forward signals, the runner also sends an
extension-owned shutdown message when it exits. If the terminal disconnects
or the overlays remain visible, use the **safe fallback**:

```sh
python3 ~/frametop-toolbar-test/plugins/spatial-toolbar/control.py stop
```

This requests graceful shutdown through `@tovakai_toolbar_control`.
Only the toolbar's own overlays are destroyed; Frametop and SteamVR continue
running. Unlike `pkill`, it cannot accidentally match another program.

The plugin intentionally hides its overlays while the Steam Dashboard or a
SteamVR scene application is active to avoid invisible controller hitboxes.
If you're certain no game is running and the bar is inexplicably hidden,
temporarily retry with `FT_TOOLBAR_ALLOW_SCENE=1 bash plugins/spatial-toolbar/run.sh`
as a diagnostic. This disables *only* the scene-app visibility gate; do not
leave it running over games. Popup click handling uses the original OpenVR
bottom-left origin conversion. Opening the popup refreshes saved profiles.

The profile store and all your existing Frametop layouts are unchanged
except when you actually click **Save current arrangement** or select a
profile. The first command creates no services, desktop launchers or
system configurations. The compiled executable is written only to
`plugins/spatial-toolbar/build/`.

### Remove the test checkout afterward

```sh
# Stop toolbar with Ctrl+C before removing the working tree.
cd ~/frametop-extensions
git worktree remove ~/frametop-toolbar-test
```

No Frametop restart or rollback of core required.

---

# Preserved legacy implementation and extraction notes

**Goal:** independently run the existing Frametop toolbar as a SteamVR OpenVR
overlay process, without adding feature-specific code to the core fork.
This is an extraction, not a redesign.

Original: https://github.com/tovakai/frametop/blob/legacy/docs/README/DESKTOP_TOOLBAR.md

## What was salvaged

| Legacy original | In this plugin | Status |
| --- | --- | --- |
| layout/ft_toolbar.py | ft_toolbar.py | Copied unchanged, active pure-Python layout model |
| layout/ft_taskbar_model.py | ft_taskbar_model.py | Copied unchanged, active popup/task model |
| layout/ft_desktop.py | ft_desktop.py | Copied unchanged, FreeDesktop helpers |
| screens/desktop_toolbar.inc | reference/desktop_toolbar.inc | Source reference pending standalone extraction |
| screens/toolbar_taskbar.inc | reference/toolbar_taskbar.inc | Popup, events, hover and texture source reference |
| screens/toolbar_dock.inc | reference/toolbar_dock.inc | Dock/fly transition source reference |
| screens/spatial.inc | reference/spatial.inc | Follow/attention/drag source reference |
| session/ft-taskbar.py | reference/ft-taskbar.py | Pango/Cairo renderer and providers, source reference |
| session/frametop-session.sh | reference/frametop-session.sh | Historical wiring, reference ONLY |
| test/test_desktop_toolbar.py | tests/test_toolbar_legacy_layout.py | Ported offline behavior tests |
| test/test_taskbar_model.py | tests/test_toolbar_legacy_taskbar.py | Ported model and source-guard tests |

All originals from `tovakai/frametop` branch `legacy`, commit
`843d2c162ff8e2fe5d2763c964434bddf71e7ba9`. Nothing in `reference/`
is compiled or run as a plugin; the original included C++ assumed compositor
globals. The standalone process must adapt the original functions while keeping
their behavior.

## First integration: existing Displays menu ↔ Spatial Profiles

`toolbar_profiles.py` reuses **exactly** the original
`ft_taskbar_model.profiles_layout` layout geometry, current-profile highlight
and six slot badges, but reads the independent Spatial Profiles store at
`~/.config/frametop-extensions/spatial-profiles.json`.

Activating a profile row calls the existing Spatial Profiles runtime's
`switch` operation with the 450 ms default. The original menu footer
"Display Settings…" would edit upstream's own layout, so here it becomes
**Save current arrangement**. Until text entry is ported, it saves
`Arrangement 1`, `Arrangement 2`, etc.

The original popup adapter is now also used by the opt-in standalone
OpenVR host described above. Its behavior is unit-tested; the visual
Steam Frame test is still pending.

Offline tests from the extensions repo root:

`~sh
python3 -m unittest discover -s tests -v
`~

Read-only inspect the menu layout JSON:

`~sh
PYTHONPATH=plugins/spatial-toolbar python3 -c \
  'import toolbar_profiles; print(toolbar_profiles.state_json())'
`~

## Architecture

`~text
SteamVR / OpenVR
  └── independent Spatial Toolbar process (own overlay handles, no Valve UI ownership)
        ├── bar geometry + OpenVR mouse input  [reference/desktop_toolbar.inc]
        ├── popup rendering/events             [reference/toolbar_taskbar.inc]
        ├── app, task, tray providers          [reference/ft-taskbar.py]
        └── Displays popup → toolbar_profiles.py → Spatial Profiles runtime
                                                     └── @ft_screens API v1

Frametop core = upstream + generic API (unchanged).
`~

Spatial Profiles itself stays headless and usable with its CLI. **The GUI
depends on the profile backend, not vice versa.**

## Do NOT repeat our old bugs

1. **Pool and reuse overlay handles.** Legacy `cellPool` survives task
   rebuilds. Hide/reuse, never destroy/recreate on every task change.
   Hover updates alpha rather than re-uploading textures. Preserve a good
   texture when SteamVR rejects an update. This avoids the invisible black bar.
2. **Match mouse-scale aspect to texture.** `SetOverlayMouseScale` must use
   actual texture width and height. Default 1×1 hit testing on a 10:1 bar
   produced a huge invisible clickable area.
3. **Keep the original visuals:** 1800×180 bar grammar, arched ±15° and
   tilted back 20°, dark `#0e141b` backing, `#88ccf1` accent,
   Start / Tasks on the left, Displays / Tray on the right.
4. **Keep original popup rules:** only one open, facing the headset,
   popup and hover layers in front of cells, mouse Y flipped,
   click-away closes, yield to SteamVR Dashboard.
5. **Never reparent/modify Valve's Dashboard UI.** The toolbar owns its
   OpenVR overlay keys, at conservative sort order.
6. **Do not reintroduce feature logic into core.** Generic screen
   positioning/opacity come through `@ft_screens`. Per-frame follow,
   gaze attention and screen docking cannot be restored without
   additional generic APIs or independently owned overlay surfaces.

## Next device-testable slices

1. Build the standalone OpenVR process displaying the **original bar +
   Displays button**, with mouse hitbox diagnostics and dashboard yield.
2. Port the original Pango/Cairo popup renderer and mouse events to make
   Displays selections and Save current actions clickable in VR.
3. Restore Start, Tasks, Volume and Wi-Fi from `ft-taskbar.py`, reusing
   its KWin D-Bus task feed, icons, popup renderer and model.
4. Move follow/drag behavior into the independent overlay host. Only then
   add screen docking against a generic attachment API.
5. Add opt-in, reversible user-service installation and hardware
   regressions for the black bar, pointer click, overlay cleanup, and
   SteamVR restart.

The original UI lives on in these source references. No fresh GUI design
until the old one has been properly extracted.
