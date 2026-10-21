# Spatial Room v0.1.0 (prototype)

An independent, opt-in foundation for Quest 2-style **manual** room creation in Frametop. This commit implements the **room model and editor state machine**, **not** an in-headset UI. It neither scans the room nor alters Frametop, SteamVR, FramePort, or headset settings.

## Intended headset workflow

1. In passthrough, point at each floor corner and click; close the polygon.
2. Drag opposite corners to place furniture volumes; adjust height and rotation, then label them TABLE, COUCH, BED, STORAGE, SCREEN, LAMP, PLANT or OTHER.
3. Save the room in SteamVR Standing coordinates, check tracking alignment, optionally export it to FramePort.
4. Later Frametop extensions, including posters and spatial widgets, consume the same room data.

**Missing:** OpenVR overlay, controller input hooks, wireframe renderer, in-headset UI, tracking-universe lookup and recalibration, direct FramePort installation and device testing. Do not present this prototype as a usable in-headset editor.

Frametop extension API v1 currently provides screen controls, not arbitrary 3D geometry or tracked controller input. The planned VR frontend needs its own OpenVR overlay/input process; this plugin supplies its data model and ray-input state machine.

## Coordinates and compatibility

Right-handed SteamVR Standing/STAGE space, metres, +Y up and -Z forward. JSON is the extension's editable source of truth. Explicit export generates FramePort's frameport-room 1 text with source manual, floor, ceiling, polygon walls and semantic furniture volumes, **without a scanned mesh**. The generated anchor UUIDs remain stable for unchanged objects.

The room belongs to a SteamVR tracking universe and might drift/misalign after recentering or relocalization. Until live alignment checking exists, do **not** auto-load a saved room into other apps or assume persistent physical registration. Universe 0 explicitly means unknown, not a working anchor. Test alignment inside the headset before using room geometry.

## Offline CLI (Python 3.10+; standard library only)

Run from the extensions checkout:

    python3 plugins/spatial-room/room.py new /tmp/living-room.json --name "Living Room" --universe 0
    python3 plugins/spatial-room/room.py check /tmp/living-room.json
    python3 plugins/spatial-room/room.py edit /tmp/living-room.json
    python3 plugins/spatial-room/room.py export /tmp/living-room.json /tmp/room.txt

The **edit** command reads one JSON object per line from stdin. Events are status, corner, close, box_start, box_finish, set_ceiling, delete_box, undo, and save. Corner and box events accept the tracked ray as origin: [x,y,z] and unit direction: [dx,dy,dz]. For box_finish, provide optional label, height (metres) and yaw_deg. set_ceiling takes height above the floor. Responses are JSON objects reporting success or error. No edit is written until the explicit save event.

Export refuses to overwrite an existing file or publish an unfinished room, and does **not** touch FramePort's installed rooms. Check against [FramePort v1.3.0's room format](https://github.com/spoopyghosty0/frameport/blob/v1.3.0/docs/mr/ROOM_FORMAT.md).

Offline tests: python3 -m unittest discover -s tests -v.

## Next slice

Build a native overlay/input adapter that sends real controller rays and trigger events to this editor. Render in-room wireframes and an edit-mode panel over passthrough without modifying the Frametop compositor. It must identify the actual tracking universe, explicitly handle recentering, avoid intercepting unrelated SteamVR input, and never restart Steam/SteamVR on installation. Only mark the feature live-tested after headset tests pass.
