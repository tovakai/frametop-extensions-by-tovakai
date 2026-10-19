# FrameDepth (experimental stereo preview)

An independently installable **control-plane extension** for Frametop's opt-in
GPU stereo preview. Inspired by [its-ven/FrameDepth](https://github.com/its-ven/FrameDepth).
All implementation in this repository is independent; it does not reuse the
original project's code or ship model weights.

**Implemented:** a capability-checked CLI to enable and disable a live per-screen
SBS stereo diagnostic in the [Frametop core preview branch](https://github.com/tovakai/frametop/tree/feature/stereo-preview-extension).
The renderer uses image **brightness as fake depth**. This can make flat UI look
strange and is **not** Depth Anything, actual 3D reconstruction or a usable
monocular depth estimation system yet. The core branch is NOT device-tested.

## First, test the GPU without changing the desktop

On 2026-10-19, the experimental `ft-screens` compiled on Steam Frame ARM64
and the isolated headless compositor advertised `screen.stereo.preview`.
However, starting that checkout as an **entire desktop** caused a black
display; restarting SteamVR recovered it. Its root cause is **unknown**.

**Do not replace your installed compositor just to test the preview.** The
matching core branch now provides an independent timed stereo smoke overlay,
based on its existing `ft-handtest` tool. It needs no hand tracking, no
extension repo installed and makes no changes to the launcher.

```sh
cd ~/frametop-stereo-test
git pull --ff-only
./screens/build.sh
./scripts/frame.sh -C screens './build/ft-handtest --stereo-preview --seconds 20'
```

The test now draws an **explicit stereoscopic calibration scene**: an
unshifted grid, an orange square with foreground disparity, a cyan circle
with background disparity, and eye-order markers (red in LEFT eye, blue in
RIGHT eye). It uses the **same renderer** as the intended extension; it vanishes
automatically after 20 seconds, or immediately on Ctrl+C. Default strength
is 0.006, with optional `--stereo-strength` and `--stereo-swap` to diagnose
perception or eye-order problems. Use `--stereo-luminance` to reproduce the
original checkerboard test. Maximum runtime is 60 seconds.

This calibrates known stereo disparity, not depth inference or a desktop
screen. It doesn't prove that arbitrary desktop buffers, cutouts or input
are working correctly.

## Then, enable a per-screen preview (only on a verified matching compositor)

Once the isolated panel has been verified, **and** a matching Frametop
compositor is running without disturbing the existing desktop:

```sh
cd ~/frametop-depth-test
python3 plugins/frame-depth/preview.py check-api
python3 plugins/frame-depth/preview.py status 1
python3 plugins/frame-depth/preview.py on 1 --strength 0.003
python3 plugins/frame-depth/preview.py off 1
```

If the extension API is missing, the controller **refuses** to enable the effect.
Use `off` to get back to normal 2D. Only local desktop screens are supported.
The compositor owns the state and forgets it when restarted. The extension
writes no persistent settings, SteamVR files, startup services or layouts.

## Offline reference renderer

`depth.py` is an independent pure-Python forward-splat reference that accepts
an RGB image array plus a separate normalized depth map. This is **not** the
live GPU renderer, which currently uses brightness as its temporary depth.

```sh
python3 plugins/frame-depth/depth.py --demo
python3 -m unittest discover -s tests -v
```

## Current architecture

- FrameDepth CLI -> Frametop extension API -> per-screen preview settings.
- Frametop's **existing** GPU cutout pipeline imports each desktop frame, samples
  shifted views into one DRM/GBM side-by-side texture and hands it to OpenVR.
- Hand cutouts, when available, are composited in the same pass. Turning off
  stereo returns the original frame directly when no cutouts are needed.
- The preview mode is optional and starts disabled, including after restart.
- No frame sharing, arbitrary depth-map submission, actual inference, background
  worker or third-party OpenVR overlay takeover exists yet.

## Next engineering steps

1. Test the matching compositor and extension branches on the Frame; verify eye
   order, OpenVR flags, mouse mapping, alpha cutouts, buffer lifetimes and fallback.
2. Benchmark a native ARM64 Depth Anything V2 Small pipeline independently.
   NPU access under SteamOS is unproven; measure GPU, CPU and frame-time cost.
3. Design a **new** permissioned, synchronized depth-map transport capability
   with well-defined size, format, security, backpressure, epoch and ownership.
   Do not overload the debug CLI with raw images.
4. Replace the diagnostic shader with true depth-texture sampling, edge-aware
   warping, hole filling, temporal smoothing and bounds against eye strain.
5. Add per-screen settings and proper extension manager integration. Preserve
   the six spatial slots, attention, floating-window behavior and existing input.

## Safety and release gates

- [x] Extension manifest, client, CLI, offline reference and unit tests authored
- [x] Core-side opt-in rendering path authored on a separate branch
- [x] Extension and core *offline* CI checks confirmed passing
- [x] Original compositor branch built on ARM64 Steam Frame before adding the
      separate smoke-test mode (this new mode still needs an ARM64 rebuild)
- [ ] Standalone stereo smoke overlay built and visually validated on-device
- [ ] Live per-screen stereo preview device validation
- [ ] Performance and eye comfort evaluation
- [ ] Real depth map inference/transport with hardware benchmarks
- [ ] Independent install/disable/uninstall and rollback verified on-device

**Licensing:** The original FrameDepth repository should not be vendored without
explicit permission. The reference algorithm here is independently written.
