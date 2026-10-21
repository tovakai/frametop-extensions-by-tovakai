# Spatial Room v0.2.0 (experimental VR frontend)

An **optional** Frametop extension for manually blocking out a room inside Steam Frame passthrough. No automatic scanning. No changes to the compositor, SteamVR files or running desktop. This branch is **not device-tested**.

This is a first OpenVR overlay prototype, not yet a polished Quest room editor. The editor displays floor/ceiling/wall wireframes, furniture cubes, a controller-aim cross and an HMD-relative help panel. You point the **right controller at the floor** and pull trigger to put down corners. It reads controller actions via SteamVR, and stage-space geometry is saved by the Python backend.

## Build on Steam Frame (opt-in)

Prerequisites: Frametop checkout at ~/frametop, its existing dev distrobox, and a cloned extensions checkout at ~/frametop-extensions. This is a **separate build** and makes no system changes.

    cd ~/frametop-extensions
    git fetch origin feat/spatial-room-manual-layout
    git switch feat/spatial-room-manual-layout
    bash plugins/spatial-room/native/build.sh

The build uses Frametop's pinned OpenVR SDK 2.15.6 and SteamVR's libopenvr_api on the headset. If your checkout is somewhere else, set FRAMETOP_ROOT to its path. Compilation happens in the existing "dev" distrobox. Test/build has no automatic install step.

Start in Frametop Desktop mode, ideally with passthrough visible:

    python3 plugins/spatial-room/session.py --export-frameport ~/Documents/Spatial-Room-Exports

The CLI starts a temporary OpenVR overlay process. **It does not restart SteamVR or enable controller-global input.** Its first run creates an in-memory unsaved draft. The X button saves your JSON room under ~/.config/frametop-extensions/spatial-room/room.json. If you provided --export-frameport, it also exports a timestamped, FramePort-compatible room.txt into that folder after the outline is closed. This is **staging**, not automatic import.

If you prefer another room, use --file /path/to/different-room.json. A saved room with a different SteamVR universe ID is refused rather than applied at the wrong physical coordinates. If SteamVR returns universe ID 0, placement is blocked until tracking is identifiable.

### Prototype controller map

| Right controller | Action |
|---|---|
| Trigger | Add wall corner; after walls close, first click starts furniture box, second ends it; in Erase mode, select a box footprint to delete |
| A | Close polygon (3+ valid corners); with a pending furniture box, cancel its start |
| Grip | After closing the walls, toggle **Add furniture / Erase furniture** |
| B | Undo last geometry action |
| Bumper | Cycle furniture label: TABLE, COUCH, BED, STORAGE, SCREEN, LAMP, PLANT, OTHER |
| Y | Cycle furniture height: 0.45 / 0.75 / 1.1 / 1.8 / 2.3 m |
| Thumbstick click | Rotate next furniture box 15 degrees |
| X | Save room and optionally stage a FramePort export |

Quit from the terminal with Ctrl+C. Uncommitted edits remain only in memory. The editor frontend automatically hides its overlays while an ordinary VR scene application is active.

**Important SteamVR limitation:** The Frame controllers don't expose normal evdev buttons. The standalone OpenVR client uses a hidden action set at overlay-global priority. SteamVR's **Enable global input from overlays (Experimental)** must be on for the mappings to work. Frametop's own controller mappings may compete for buttons. This prototype deliberately does **not** toggle that preference or force controller bindings. If the overlay is visible but buttons don't work, inspect terminal stderr and SteamVR bindings.

### How to test without risking existing rooms

Use a temporary draft:

    python3 plugins/spatial-room/session.py --file /tmp/frametop-room-test.json

Remove the JSON when finished. No background service is installed. Running the editor is voluntary. Until live testing confirms controller bindings and geometry alignment, use the editor for experiments, not as a protective guardian or obstacle detector. The wireframes are **not physical collision geometry** and cannot prevent you from walking into furniture.

## Internals and compatibility

- [room_model.py](room_model.py): versioned JSON source of truth; metres, right-handed SteamVR STAGE, +Y up, -Z forward, semantic furniture, finite input and polygon validation.
- [editor.py](editor.py): controller-ray to floor placement, undo, semantic boxes.
- [session.py](session.py): read/edit/render/save boundary, universe guard and explicit staged FramePort export.
- [native/ft-room-vr.cpp](native/ft-room-vr.cpp): temporary OpenVR overlays, right-controller tip transform and action events; no direct filesystem writes.
- [room.py](room.py): headless CLI and explicit FramePort export, useful for testing/offline tooling.
- [room_api.py](room_api.py): read-only room snapshots, wall normals and poster-friendly wall anchors for dependent extensions; requires a matching SteamVR universe.

FramePort v1.3.0 accepts \`frameport-room 1\` files with \`source manual\`, a room outline, wall entities and furniture volumes, even with no scanned mesh. [Format contract](https://github.com/spoopyghosty0/frameport/blob/v1.3.0/docs/mr/ROOM_FORMAT.md). To import the exported file through FramePort, use FramePort's own supported interfaces and review the result on the headset; this extension does not auto-import anything.

Tracking alignment is a serious limitation. Matching universe IDs only prevents some invalid restores: inside a single tracking universe, SteamVR may still shift/recenter. Reconfirm visible overlays against real walls before trusting coordinates.

### Current limitations and next milestones

This is a **native source prototype only**, with CI compile validation against the pinned SDK and automated Python tests. The GitHub runner is not a Steam Frame and cannot validate graphics, controller capture, passthrough or latency. There is no point/drag resize UI, saved wall editing, persistent tracking-marker alignment, shared **live subscription** API for downstream extensions, or direct FramePort sync yet. Performance with many world-space overlays is unknown, so the renderer caps at 240 segments.

Next: real on-device input testing, a proper in-headset selection/edit palette, alignment reset, then a read-only spatial-room subscription API. Posters can already use the offline read-only wall anchors, but must confirm physical alignment.
