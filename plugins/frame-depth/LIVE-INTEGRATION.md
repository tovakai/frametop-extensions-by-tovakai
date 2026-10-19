# Live per-screen Frame Depth: integration proposal

**Not implemented.** Frametop's current extension API v1 includes screen status, opacity and movement, but **no** screen-frame export or GPU effect injection. The extension manager is a metadata/file manager, not a plugin process runner.

Frametop already has an internal stereo compositing precedent: `screens/handcut.cpp` synthesizes side-by-side eye buffers for hand passthrough cutouts; `screens/vr.cpp` presents those with OpenVR's `VROverlayFlags_SideBySide_Parallel` flag. It is *not* an extension API.

## Intended architecture

```
KWin -> ft-screens DMA-BUF -> native GPU effect hook -> existing OpenVR display overlay
                                    ^
                                    | current depth texture (relative near=1)
                           extension depth worker
```

Compositor core should own only a **generic** effect API plus texture lifetime and final presentation. All model-specific inference, user settings, throttling and quality modes belong in the optional Frame Depth extension. Do not vendor `vr.cpp`, run a competing OpenVR scene app, or replace a display with a second overlay.

### Proposed capability negotiations (names are placeholders)

- `screen.effect.stereo`: capability to activate/deactivate a left/right per-eye effect for a specific screen; query compatibility with other compositing stages.
- `screen.frame.read`: explicitly authorized, bounded screen-frame access. Restrict readers to the trusted user; never expose desktop pixels to a manifest-only plugin just by discovering it.
- `screen.effect.depth.submit`: send validated/timestamped low-resolution depth frames via authenticated private IPC, ideally DMA-BUF/memfd with FD passing. **Never** transport unbounded frames through the existing `@ft_screens` command datagram socket.

On any missing capability, fail closed and preserve the untouched mono display.

### Composition and safety

1. Mono DMA-BUF is the default and always the rollback texture.
2. The renderer uses the original colour frame and its matching depth texture to synthesize a left and a right view.
3. An owner in the core arbitrates the SBS overlay flag: the hand-cutout path **already uses it**. Stereo should be applied first, then eye-specific hand masks. Neither feature may blindly toggle flags while the other owns a stereo texture.
4. Preserve screen pose, curvature, chrome, dragging, attention, pinning, laser input and click coordinate semantics. Geometry remains the same as before.
5. Floating windows, window crops and popups remain unsupported until texture bounds can be handled correctly.
6. Ensure the extension cannot intercept gaze/controllers or start hand tracking as a side effect.
7. If inference fails, frames are stale, device is sleeping, or plugin is disabled/uninstalled, return atomically to the original mono texture and flags.

### Performance gates on Steam Frame

Start with **one** visible display and Depth Anything V2 Small at low resolution. Downsample source before inference, normalize per scene (e.g. 2nd/98th percentiles), smooth temporally, and reset at scene cuts. Reuse cached maps between inference frames; focus gets priority, out-of-view/paused panels suspend work. Do not run inference at the compositor's refresh rate without measurements.

Benchmark native ARM64 inference pathways (ncnn/Vulkan, CPU alternatives, and NPU only if usable drivers actually exist). Measure frame times, headset latency, screen text quality, worker resource use, thermals, standby and visible flicker on-device.

### v0.2 acceptance checklist

- One regular Frametop display goes mono <-> SBS without losing mouse/laser input or moving a screen.
- Stereo eyes and colour/depth alignment verified on real hardware.
- Switching effect on/off under concurrent hand cutouts is safe (or explicitly refuses with a visible reason).
- Visual stability across scene cuts; acceptable FPS/latency and clear comfort defaults.
- Disabled/failed effect returns to mono even if worker crashes.
- Install/uninstall changes only extension-owned paths; no SteamVR restart or session mutation during discovery.

The current extension provides a standalone **reference renderer and test oracle** only. It deliberately does not assert any of these hooks exist.
