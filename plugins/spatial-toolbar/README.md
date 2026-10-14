# Spatial Toolbar v0.1.0: first standalone OpenVR slice

The first **runnable** toolbar prototype is now on branch
`feature/toolbar-openvr-host`. It is **not yet hardware-verified**.
It launches as its own OpenVR overlay process, outside Frametop core.

**Implemented:** original arched bar silhouette and spatial placement,
the original `ft_toolbar` model's Displays-button position, the monitor
glyph, a clickable Displays button, the original Pango/Cairo popup painter,
profile names/current highlight/slot badges, and clicking a profile to switch
via the independent Spatial Profiles runtime. The footer captures a new
automatically numbered arrangement. The overlay keys are namespaced
`tovakai.spatial-toolbar.*`.

**Not yet implemented:** the rest of Start/Tasks/Tray, text-entry naming,
toolbar grab/move/follow, direct screen docking, outside-click handling beyond
the popup and button, and a managed build/start/stop lifecycle. Do not mistake
the preserved reference source below for active features.

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

The bar should appear around 75 cm in front of your initial headset pose,
40 cm below eye level, then remain **world-anchored** for this first test.
The backdrop does **not** capture controller clicks. Aim at **Displays**
(the monitor glyph), open the familiar popup, and select a saved profile.
Press **Ctrl+C** in the launching terminal to stop the independent overlay.

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
