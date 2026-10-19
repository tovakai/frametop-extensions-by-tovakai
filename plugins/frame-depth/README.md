# FrameDepth (prototype)

An **offline reference prototype** for turning a flat image plus a normalized depth map into separate eye views. Inspired by [its-ven/FrameDepth](https://github.com/its-ven/FrameDepth). This implementation is independent and does not copy FrameDepth code or bundle any model weights.

**Current reality:** The included renderer works on nested Python pixel arrays. It does **not** capture screens, estimate depth, upload GPU textures, install hooks, or change the SteamVR scene. Do not advertise it as a working VR plugin yet.

## Run

```sh
python3 plugins/frame-depth/depth.py --demo
python3 -m unittest discover -s tests -v
```

## Planned architecture

1. Frametop provides a versioned, read-only frame-texture sharing API (DMA-BUF with explicit synchronization and ownership), per-screen lifecycle and display dimensions.
2. A native ARM64 worker estimates a depth map asynchronously, ideally using GPU/NPU acceleration after benchmarking on the Frame. Start with synthetic depth and a recorded-map mode before deploying model inference.
3. A GPU compositor renders two eye textures from the original frame and depth map. Keep original flat frames available as a zero-overhead fallback.
4. A generic compositor stereo-submit hook accepts the eye views and reports support through an explicit capability; no monkey-patching SteamVR overlays.
5. Per-screen settings, saved independently from spatial profiles, control enablement, disparity strength, convergence, eye swap, inference resolution and frame budget.

## Constraints

- **No core modifications in this repository.** Required generic API hooks must be reviewed in the separate Frametop core repository.
- **Fail closed:** if texture sharing, stereo submission or synchronization is unsupported, stay in ordinary 2D mode.
- **Do not block the compositor render loop** waiting for inference. Reuse the latest completed depth map, discard stale jobs, and rate-limit the worker.
- **No surprise install actions:** never touch SteamVR configuration, services, existing layouts or other extensions.
- **Safety:** clamp stereo disparity and validate inputs. Avoid stale textures, crashes and visual instability.
- **Licensing:** verify rights for every inference model and runtime before packaging. FrameDepth upstream's source license must be clarified before copying any of its code.
- **Device verification pending:** CPU/NPU/Vulkan inference performance and real stereo overlay behavior remain unmeasured.

## Acceptance gates

- [x] Manifest and offline reference stereo renderer
- [x] Unit tests for zero strength, inversion, invalid inputs and occlusion
- [ ] Generic compositor texture and stereo capabilities designed/reviewed
- [ ] Native GPU stereo renderer on a test texture
- [ ] ARM64 depth inference benchmarks
- [ ] Real Frame display tested with input, handcut, curvature and profile transitions
- [ ] Independent enable/disable and uninstall tested on-device
