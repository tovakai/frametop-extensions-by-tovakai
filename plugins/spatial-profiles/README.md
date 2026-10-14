# Spatial Profiles v0.1.0 (experimental)

**First independent Frametop extension.** Saves and switches **world-anchored** spatial screen arrangements through [Frametop extension API v1](https://github.com/tovakai/frametop/blob/rebuild/extension-api/docs/extensions.md).

The extension lives here, not in the Frametop core fork. Core stays upstream + general-purpose APIs.

## Run it on Steam Frame

You need the API-enabled Frametop fork installed and its desktop running (ft-screens). Clone this repo independently:

```sh
git clone https://github.com/tovakai/frametop-extensions-by-tovakai.git ~/frametop-extensions
cd ~/frametop-extensions
python3 tools/list_extensions.py
python3 plugins/spatial-profiles/profiles.py check-api
```

New profiles use **their own** store at `~/.config/frametop-extensions/spatial-profiles.json`. The original `~/.config/frametop-layout-profiles.json` is **never modified**. Frametop's upstream layout and application profiles are also left alone.

```sh
p="python3 plugins/spatial-profiles/profiles.py"

# Arrange your screens in VR using their normal controls, then capture:
$p save "Work"

# Move/resize the screens in VR to create another layout:
$p save "Reading"

# Review what you've saved:
$p saved
$p saved --json

# Preview world-space targets using the *current* HMD pose, no changes:
$p preview "Work"

# Switch (450ms default; --ms 0 for instant):
$p switch "Work"
$p switch "Reading" --ms 450

# Map six numbered slots:
$p slot 1 "Work"
$p slot 2 "Reading"
$p use-slot 1
$p use-slot 2 --ms 600
$p slot 2 -                # clear slot
$p delete "Reading"        # also clears matching slots
```

For a one-off test of a different store:

```sh
$p --store /tmp/spatial-test.json save "Temporary"
$p --store /tmp/spatial-test.json saved
```

## What v0.1.0 actually captures

- Same number of screens in each profile (1..9), with independent position, facing, roll, physical width, curvature, visible/hidden state and opacity.
- **Head-relative positions and facing**, like legacy Frametop. Switching uses the headset's current world position and yaw, so your workspaces appear in front of you wherever you're sitting.
- Smooth compositor-native **450 ms** screen movement and opacity transitions; width/curve/hidden flags are applied immediately through Frametop's existing generic commands.
- Six assignable slots, explicit CLI activation, atomic writes, owner-only saved profile file, and best-effort rollback if a command fails during application.
- No background daemon or hotkey integration yet. These are CLI profiles, not startup/app-session profiles. The upstream layout applies normally on desktop restart. Switching may need to be re-run after restart.

## Deliberate limits

**v0.1.0 refuses pinned/head-locked screens** during saving or switching. The legacy soft-follow, yaw-follow, position-follow and wrist modes require a separate generic motion/anchoring API. Gaze attention, idle opacity, instruments and toolbar are not silently dropped from legacy profiles: they are simply not accepted for application yet.

Screen count must match exactly. Width refers to physical screen size in metres, **not** a KWin resolution change. SteamVR must have a valid HMD pose to capture/switch.

For read-only inspection of existing legacy profile data:

```sh
$p list
$p show "Desk"
$p plan "Desk"

# Optional exported copy
$p --file /path/to/frametop-layout-profiles.json list --json
```

There is **no import/migration of legacy profiles yet**, and the new store uses a strict versioned format. Old profiles are safe in their original path.

Before switching in VR, manually position the displays in a recoverable arrangement. Do not assume this is production-stable before the first on-device save/switch validation. If a command fails halfway, the client attempts to restore the snapshot from before the switch, but a compositor failure can make rollback impossible. You can always reset the core layout with Frametop's normal reset command.

## Test locally (no headset needed)

```sh
python3 -m unittest discover -s tests -v
```

All current tests use a fake compositor, not SteamVR. The API discovery and opacity commands have already been exercised on the actual Steam Frame; this **profile-switching implementation still needs hardware verification**.
