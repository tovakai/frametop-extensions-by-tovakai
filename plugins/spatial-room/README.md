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

If you prefer another room, use --file /path/to/different-room.json. By default, a saved room with a different SteamVR universe ID is **strictly refused** rather than applied at the wrong physical coordinates. SteamVR universe 0 is also rejected.

### Recovery after a SteamVR tracking-universe change

SteamVR can assign a new tracking universe ID after a restart, recenter or playspace recalibration. This does **not** mean the room measurements were deleted. Do not manually replace the ID in JSON: the old coordinates may no longer match physical space.

Only for a **closed, previously saved** room, launch recovery explicitly:

```bash
bash plugins/spatial-room/run.sh --recover-universe --input-debug \
  --file ~/Documents/room-test.json \
  --export-frameport ~/Documents/Spatial-Room-Exports
```

1. Recovery initially displays **UNIVERSE MISMATCH** and **hides every old room outline**. Room edits, saves and FramePort exports are blocked. Nothing touches SteamVR's floor or playspace settings.
2. Press **left trigger** to deliberately preview the old layout in the warning color, understanding that it may be in the wrong physical position. If the old room is far away or behind you, carefully reorient/recenter your attention without relying on outlines as a safety boundary.
3. **Hold right trigger** and point/move it along the floor to slide the whole room. Release, then use left D-pad left/right (±1°) or right thumbstick click (+5°) to fine-tune rotation. Left D-pad up/down shifts standing Z by 1 cm.
4. **Right A** explicitly confirms that this is the room you have visually realigned to the *new* tracking universe. The new universe ID and live raw-to-standing origin signature are committed together in memory. **Right B** or **left trigger** cancels the preview without changes.
5. **Right X** then saves the corrected room. Before overwriting the original, the editor creates a **lossless owner-only backup** next to it, named `room-test.json.universe-OLDID.bak`; existing backups are never overwritten. A FramePort export is staged only after a verified alignment confirmation.

If you **undo the confirmed recovery before saving**, the old universe ID comes back and recovery locks itself again. If the universe changes again mid-session, the native client exits and all uncommitted recovery is discarded. No automatic remapping, manual JSON ID tampering, or calibration writes occur.

This is an experimental realignment tool, not a physical calibration guarantee. Treat the imported outline as an untrusted visual reference until you've checked the visible corners against your actual room.

### Prototype controller map

| Controller button | Action |
|---|---|
| Trigger (right) | Add wall corner; after walls close, first click starts furniture box, second ends it; in Erase mode, select a box footprint to delete |
| A (right) | Close the room (3+ corners). Afterward, aim at an existing furniture box's floor footprint and press A to select it for editing; press A over empty floor to deselect. With a pending furniture box, cancel its start |
| Grip (right) | After closing the walls, toggle **Add furniture / Erase furniture** |
| B (right) | Undo last geometry action |
| Bumper (right) | Cycle furniture type on the selected box (undoable), or set the next box's type: TABLE, COUCH, BED, STORAGE, SCREEN, LAMP, PLANT, OTHER |
| Y (right) | Cycle coarse height presets (0.45 / 0.75 / 1.1 / 1.8 / 2.3 m) for selected furniture or the next box |
| Thumbstick click (right) | Rotate selected existing furniture **+5°**; otherwise rotate the next furniture box +5° |
| D-pad left/right (left controller) | Rotate selected furniture **−1° / +1°**; otherwise adjust the next furniture box's angle |
| D-pad up/down (left controller) | Adjust selected furniture height **+1 cm / −1 cm**, or set the next box's height in 1 cm increments |
| X (right) | Save room and optionally stage a FramePort export |
| Trigger (left) | Enter **Align Room** mode, or cancel its current preview |

### Align the entire room in your headset (experimental)

**Back up an important saved room first** (the new format is backward-compatible, but native on-device alignment still needs validation):

```bash
cp ~/Documents/room-test.json ~/Documents/room-test.pre-alignment.json
```

With the editor running and the room outline closed:

1. Press **left trigger** to enter **Align Room**. A preview is now active; no saved geometry changes yet.
2. Aim the **right controller** at the floor. **Hold its trigger** and move the cross-marker along the floor to slide the **entire** room and every furniture box. Release to stop dragging. The source wall points and furniture dimensions remain unchanged.
3. Use **left D-pad left/right** for −1°/+1° room rotation about its original room center; **right thumbstick click** rotates +5°. In Align mode, **left D-pad up/down** nudges the whole room along standing Z by 1 cm (not furniture height).
4. Press **right A** to **accept** the preview (undoable) or **right B** / **left trigger** to cancel all preview changes. Finally press **right X** to persist the corrected room and stage a newly aligned FramePort export.

Aligned selections, hover/erase hit testing, outline previews, wall anchor APIs and FramePort exports all operate in the effective world coordinates, while the saved wall and furniture identities remain stable. We do **not** edit SteamVR's playspace/chaperone calibration or add any extra vertical shift: standing floor Y remains the runtime's floor reference.

The native client checks OpenVR's raw-to-standing tracking-origin transform roughly once per second. An origin change or previously saved room without an accepted calibration is marked **ALIGNMENT UNVERIFIED** in the HUD. While unverified, saving the room still preserves its JSON geometry, but new FramePort exports are **not staged** until the alignment has been accepted with right A. This is a signal to manually check or realign, **not** an automatic correction or proof of physical registration. Dashboard-only recentering normally doesn't affect standing geometry. Inside-out tracking drift might go undetected; the outlines are never a physical safety boundary.

**To align an already placed couch:** look down and point the cross-marker at the couch's footprint. Press **right A** to select it (red wireframe). Press **left D-pad left/right** repeatedly to nudge the couch by 1° per press; press **right thumbstick click** for a faster +5° turn. The rotation changes the existing box around its center, not its size or location. Right B undoes a rotation. Aim at empty floor and press right A to deselect. Save with **right X**. This keeps each rotation as an undoable edit.

**To change furniture type without redrawing it:** aim at the existing box, press right A to select it, then press the right bumper. The label cycles through furniture types without changing size or position, and right B undoes the change. If nothing is selected, the bumper changes the next box's type.

**To dial in the couch's height:** while it's selected, tap **left D-pad up** to add 1 cm or **down** to subtract 1 cm. The box's bottom stays put while its top moves. Press **right Y** to jump between the coarse height presets instead. If nothing is selected, these buttons set the *next* furniture box's height. The room ceiling and minimum 5 cm height are enforced, and existing-box height changes can be undone with right B.

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
- [session.py](session.py): read/edit/render/save boundary, origin/universe guard, undoable whole-room alignment preview and staged FramePort export.
- [native/ft-room-vr.cpp](native/ft-room-vr.cpp): temporary OpenVR overlays, right-controller tip transform and opt-in global action events; otherwise it accepts actions only from its parent's private stdin pipe.
- [vr_input.py](vr_input.py): default read-only SteamVR controller observer over vrserver's loopback websocket, based on Frametop's proven input/vrws.py technique.
- [room.py](room.py): headless CLI and explicit FramePort export, useful for testing/offline tooling.
- [room_api.py](room_api.py): read-only room snapshots, wall normals and poster-friendly wall anchors for dependent extensions; requires a matching SteamVR universe.

FramePort v1.3.0 accepts \`frameport-room 1\` files with \`source manual\`, a room outline, wall entities and furniture volumes, even with no scanned mesh. [Format contract](https://github.com/spoopyghosty0/frameport/blob/v1.3.0/docs/mr/ROOM_FORMAT.md). To import the exported file through FramePort, use FramePort's own supported interfaces and review the result on the headset; this extension does not auto-import anything.

Tracking alignment remains a serious limitation. Matching universe IDs and a raw-to-standing origin signature detect many recalibrations but **cannot guarantee** physical registration. After recentering or tracking drift, manually compare the outline against your real walls before trusting its placement.

### Current limitations and next milestones

This remains an **experimental native OpenVR prototype**, with CI compile validation and automated Python tests. The GitHub runner is not a Steam Frame and cannot validate graphics, controller capture, passthrough or latency. There is no per-wall edit/resize tool, persistent external tracking-marker alignment, shared **live subscription** API for downstream extensions, or direct FramePort sync yet. A first whole-room alignment drag exists but still needs device validation. Performance with many world-space overlays is unknown, so the renderer caps at 240 segments.

Next: on-device alignment and floor-recalibration tests, then a separate show/hide outline service and the Frametop toolbar toggle. Posters can already use the offline read-only wall anchors, but must confirm physical alignment.
