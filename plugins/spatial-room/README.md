# Spatial Room v0.2.0 (experimental VR frontend)

An **optional** Frametop extension for manually blocking out a room inside Steam Frame passthrough. No automatic scanning. No changes to the compositor, SteamVR files or running desktop. The HUD, cross-marker, and manual furniture placement have been exercised on Steam Frame; this remains an **experimental prototype**.

This is a first OpenVR overlay prototype, not yet a polished Quest room editor. The editor displays floor/ceiling/wall wireframes, furniture cubes, a controller-aim cross and an HMD-relative help panel. You point the **right controller at the floor** and pull trigger to put down corners. It reads controller actions via SteamVR, and stage-space geometry is saved by the Python backend.

## Build on Steam Frame (opt-in)

Prerequisites: the existing Frametop **dev** distrobox, SteamVR's ARM64 OpenVR library on the Frame, and a cloned extensions checkout at ~/frametop-extensions. **The Frametop source checkout is no longer required.** This is a separate build and makes no system changes.

    cd ~/frametop-extensions
    git fetch origin feat/spatial-room-manual-layout
    git switch feat/spatial-room-manual-layout
    bash plugins/spatial-room/native/build.sh

The build downloads and verifies the same pinned OpenVR SDK header (v2.15.6) Frametop uses, independent of its installation path, and links to SteamVR's libopenvr_api on the headset. It locates distrobox in ~/.local/bin as well as PATH. Compilation happens in the existing "dev" distrobox. Build does not install or restart anything.

Start in Frametop Desktop mode, ideally with passthrough visible:

    bash plugins/spatial-room/run.sh --export-frameport ~/Documents/Spatial-Room-Exports

The wrapper starts the Python editor and temporary OpenVR overlay **inside the dev distrobox**, matching the environment where the native binary was compiled. Do not start the native executable directly on the SteamOS host. The CLI starts a temporary OpenVR overlay process. **It does not restart SteamVR or enable controller-global input.** By default the controller watcher uses vrserver's local, read-only input feed on 127.0.0.1:27062; it does not claim any controller buttons. Its first run creates an in-memory unsaved draft. The right X button saves your JSON room under ~/.config/frametop-extensions/spatial-room/room.json. If you provided --export-frameport, it also exports a timestamped, FramePort-compatible room.txt into that folder after the outline is closed. This is **staging**, not automatic import.

If you prefer another room, use --file /path/to/different-room.json. A saved room with a different SteamVR universe ID is refused rather than applied at the wrong physical coordinates. If SteamVR returns universe ID 0, placement is blocked until tracking is identifiable.

### Prototype controller map

| Controller button | Action |
|---|---|
| Trigger (right) | Add wall corner; after walls close, first click starts furniture box, second ends it; in Erase mode, select a box footprint to delete |
| A (right) | Close the room (3+ corners). Afterward, aim at an existing furniture box's floor footprint and press A to select it for editing; press A over empty floor to deselect. With a pending furniture box, cancel its start |
| Grip (right) | After closing the walls, toggle **Add furniture / Erase furniture** |
| B (right) | Undo last geometry action |
| Bumper (right) | Cycle furniture label: TABLE, COUCH, BED, STORAGE, SCREEN, LAMP, PLANT, OTHER |
| Y (right) | Cycle coarse height presets (0.45 / 0.75 / 1.1 / 1.8 / 2.3 m) for selected furniture or the next box |
| Thumbstick click (right) | Rotate selected existing furniture **+5°**; otherwise rotate the next furniture box +5° |
| D-pad left/right (left controller) | Rotate selected furniture **−1° / +1°**; otherwise adjust the next furniture box's angle |
| D-pad up/down (left controller) | Adjust selected furniture height **+5 cm / −5 cm**, or set the next box's height in 5 cm increments |
| X (right) | Save room and optionally stage a FramePort export |

**To align an already placed couch:** look down and point the cross-marker at the couch's footprint. Press **right A** to select it (red wireframe). Press **left D-pad left/right** repeatedly to nudge the couch by 1° per press; press **right thumbstick click** for a faster +5° turn. The rotation changes the existing box around its center, not its size or location. Right B undoes a rotation. Aim at empty floor and press right A to deselect. Save with **right X**. This keeps each rotation as an undoable edit.

**To dial in the couch's height:** while it's selected, tap **left D-pad up** to add 5 cm or **down** to subtract 5 cm. The box's bottom stays put while its top moves. Press **right Y** to jump between the coarse height presets instead. If nothing is selected, these buttons set the *next* furniture box's height. The room ceiling and minimum 5 cm height are enforced, and existing-box height changes can be undone with right B.

Quit from the terminal with Ctrl+C. Uncommitted edits remain only in memory. The editor frontend automatically hides its overlays while an ordinary VR scene application is active.

**SteamVR input:** The Frame controllers don't expose normal evdev buttons. The default `readonly` input mode subscribes to vrserver's local websocket input feed using a standard-library client. It observes presses regardless of overlay focus, without enabling SteamVR global input or stealing actions from VR games. Steam/SteamVR can still react to buttons as normal. This undocumented endpoint may change after SteamVR updates. Check the terminal for `Spatial Room input: read-only input connected: ...`.

For diagnosing input, run `bash plugins/spatial-room/run.sh --input-debug --file /tmp/frametop-room-test.json`. Press right trigger and look for `Spatial Room input: controller press: place` on stderr. If the endpoint is unavailable you'll see an explicit failure instead of a mysteriously dead menu.

The previous OpenVR global-action implementation is available as `--input-mode global` for comparison, but it requires **Enable global input from overlays (Experimental)** and may compete with Frametop's controller bindings. It is no longer the default.

### How to test without risking existing rooms

Use a temporary draft:

    bash plugins/spatial-room/run.sh --file /tmp/frametop-room-test.json

Remove the JSON when finished. No background service is installed. Running the editor is voluntary. Until live testing confirms controller bindings and geometry alignment, use the editor for experiments, not as a protective guardian or obstacle detector. The wireframes are **not physical collision geometry** and cannot prevent you from walking into furniture.

## Internals and compatibility

- [room_model.py](room_model.py): versioned JSON source of truth; metres, right-handed SteamVR STAGE, +Y up, -Z forward, semantic furniture, finite input and polygon validation.
- [editor.py](editor.py): controller-ray to floor placement, undo, semantic boxes.
- [session.py](session.py): read/edit/render/save boundary, universe guard and explicit staged FramePort export.
- [native/ft-room-vr.cpp](native/ft-room-vr.cpp): temporary OpenVR overlays, right-controller tip transform and opt-in global action events; otherwise it accepts actions only from its parent's private stdin pipe.
- [vr_input.py](vr_input.py): default read-only SteamVR controller observer over vrserver's loopback websocket, based on Frametop's proven input/vrws.py technique.
- [room.py](room.py): headless CLI and explicit FramePort export, useful for testing/offline tooling.
- [room_api.py](room_api.py): read-only room snapshots, wall normals and poster-friendly wall anchors for dependent extensions; requires a matching SteamVR universe.

FramePort v1.3.0 accepts \`frameport-room 1\` files with \`source manual\`, a room outline, wall entities and furniture volumes, even with no scanned mesh. [Format contract](https://github.com/spoopyghosty0/frameport/blob/v1.3.0/docs/mr/ROOM_FORMAT.md). To import the exported file through FramePort, use FramePort's own supported interfaces and review the result on the headset; this extension does not auto-import anything.

Tracking alignment is a serious limitation. Matching universe IDs only prevents some invalid restores: inside a single tracking universe, SteamVR may still shift/recenter. Reconfirm visible overlays against real walls before trusting coordinates.

### Current limitations and next milestones

This is a **native source prototype only**, with CI compile validation against the pinned SDK and automated Python tests. The GitHub runner is not a Steam Frame and cannot validate graphics, controller capture, passthrough or latency. There is no point/drag resize UI, saved wall editing, persistent tracking-marker alignment, shared **live subscription** API for downstream extensions, or direct FramePort sync yet. Performance with many world-space overlays is unknown, so the renderer caps at 240 segments.

Next: real on-device input testing, a proper in-headset selection/edit palette, alignment reset, then a read-only spatial-room subscription API. Posters can already use the offline read-only wall anchors, but must confirm physical alignment.
