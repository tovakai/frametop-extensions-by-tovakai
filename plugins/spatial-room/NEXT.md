# Spatial Room 0.3: alignment, floor authority, visibility and inspector

Status: proposed engineering plan; not implemented unless explicitly marked below.

## User-tested baseline

Steam Frame successfully saved `~/Documents/room-test.json` and staged a FramePort `room.txt`. The OpenVR HUD, controller ray and read-only vrserver button feed work in physical headset testing. This proves export staging, not a FramePort import or persistent physical registration. Existing user room files **must never be overwritten without explicit save**.

### Delivered small improvements for this milestone

- Left D-pad up/down now nudges furniture **1 cm** in place or sets the next object's height; right Y retains coarse presets.
- With an existing furniture box selected via right A, right bumper changes its semantic type without recreating its box. Undo persists until editor exit.

## First real milestone: registered room alignment

Problem: stored geometry currently sits directly in OpenVR `TrackingUniverseStanding` coordinates. `universe` equality is not sufficient proof of real-world alignment after playspace recenter, chaperone changes, floor recalibration or inside-out relocalization. All walls/boxes should move as one rigid assembly.

**Model**
- Keep existing room-local corners, box IDs, dimensions, angles and labels intact; introduce a separately serialized **alignment transform** with horizontal translation (x,z), yaw and explicitly separated vertical/floor treatment. Identity default must load existing v1 files without losing data; use backwards-compatible optional data and tests, or a versioned v2 migration with explicit fixture tests.
- Apply the exact same local→standing transform to rendering, hit testing, editor rays, wall anchors/snapshot consumers and staged FramePort exports. Never transform an already transformed object twice. Rotation pivot defaults to a stable room center, not the HMD position.
- Alignment mode: preview whole room with controller drag across floor and +/−1° nudges, Save, Cancel, Reset, Undo; support 1 cm x/z nudges. No mutations while another VR scene is active.
- **Do not edit SteamVR chaperone settings.** Let SteamVR own floor calibration. Its standing origin is defined at the floor (Y=0); our room floor derives from this, with a separate explicit user correction only if the runtime's floor really is off. Do not stack an arbitrary hard-coded offset on top of SteamVR's height adjustment.
- Capture an origin/calibration signature at save, using read-only OpenVR `GetRawZeroPoseToStandingAbsoluteTrackingPose()` and current universe where supported; monitor `VREvent_ChaperoneDataHasChanged`, tracking-universe changes, and standing/raw transform changes. Compare after calibration/recenter. On uncertainty **flag room unverified and request realignment**, rather than silently trusting matching universe IDs or auto-warping geometry.
- Note Steam Frame's dashboard-only recenter is separate from Playspace recenter and should not affect world-space outlines.
- Never treat virtual outlines as collision protection or automatic physical anchors; an optional manual/AR fiducial calibration may come later.

**Device acceptance checks**
- Start with a backup copy of the saved room. Rotate/slide whole assembly and Save; exit/relaunch; verify every wall and furniture volume retains relative dimensions and labels.
- Recenter dashboard only: geometry should not move. Recenter Playspace: detect any changed origin, or preserve physical alignment through a proven transform; do not silently show false registration.
- Change floor height using SteamVR's own Playspace menu; world geometry should remain coherent with the new floor calibration or explicitly ask for recalibration. No duplicate Y shift.
- Stage a new FramePort export and independently verify walls, furniture and floor are transformed once.

## Second: on-demand outline visibility

Goal: a tiny **Spatial Room** button in Frametop's toolbar (or standalone extension UI while the toolbar host is not yet device-ready), with `Show outlines`, `Hide outlines`, `Align` and `Edit`.

- Factor the renderer from the editor. Visibility is a separate state; hiding leaves saved room data intact and consumes no controller actions. Don't run two OpenVR clients with the same overlay keys.
- A room-specific opt-in user process may expose a narrow authenticated local Unix socket supporting `status`, `show`, `hide`, `toggle`, `open_editor`, `open_alignment`; implement lifecycle safely (avoid auto-start on discovery) and clean up OpenVR overlays on exit.
- Have the **Spatial Toolbar extension** call that service. The current Frametop extension API only exposes screen controls, and Spatial Toolbar's click handling is not yet production-ready. Do not insert feature code into Frametop core.
- Default outlines off. Preserve existing behavior of hiding in ordinary VR scene games; optional passthrough MR scene opt-in only after testing, not an unconditional `GetCurrentSceneProcessId` exception.

**Acceptance:** one click shows outlines, another hides them; session restart doesn't lose the room; no accidental SteamVR button capture.

## Third: selected-object inspector

The selection state already exists and currently supports rotation, height adjustment, and (this milestone) semantic relabel. Expand it into a compact, contextual inspector rather than making users redraw objects.

- Select existing object via right A and highlight it; show `Type`, `Height`, `Rotation`, `Width`, `Depth`, and `Position`. Avoid reshaping the object merely by opening its inspector.
- Right bumper cycles selected type, right Y large height preset, left D-pad up/down 1 cm, left/right 1°; later give size and position their own distinct tool mode and responsive previews.
- All changes are per-object and Undoable; selecting another object must not accidentally change the default type/height of new boxes. Values must be validated against the model and physical ceiling constraints.
- Separate a read-only viewer from editor input while games are running.

## Recommended implementation order

1. Alignment transform data model + geometry helpers + migration/undo/export tests.
2. Read-only standing-origin and chaperone-change detection + explicit unverified warning.
3. Headset **Align Room** drag/rotate UX and revalidation against real couch/walls.
4. Renderer lifecycle and show/hide API, then opt-in toolbar toggle.
5. Full object inspector, size/position editing, and eventually persistent external room anchors.

No automatic import to FramePort, SteamVR configuration writes, room overwrites or background service installation as part of this design alone.
