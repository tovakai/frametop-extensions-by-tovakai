# Frame Depth v0.1.0 (prototype)

An independent **offline stereoscopic renderer** inspired by [FrameDepth](https://github.com/its-ven/FrameDepth). Designed for eventual per-screen Frametop integration, **not yet a live VR effect**.

Accepts a 2D colour image and a relative greyscale depth map (white = near, black = far), and renders left-eye/right-eye side-by-side (SBS) views using iterative inverse depth warping. An opt-in [Depth Anything V2 Small](https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf) adapter estimates depth for **still images** with PyTorch and Transformers.

**Original implementation:** the FrameDepth repository was an inspiration, not copied code. No license was declared in FrameDepth at the time of this prototype.

## Smoke test, no packages and no headset

From the extensions repository checkout:

```sh
python3 plugins/frame-depth/ft_depth.py doctor
python3 plugins/frame-depth/ft_depth.py demo --output-dir /tmp/frame-depth-demo
# Open /tmp/frame-depth-demo/stereo.ppm in an SBS-capable viewer.
```

The demo writes only `source.ppm`, `depth.pgm`, and `stereo.ppm` in the chosen output directory. The PPM/PGM raster support is pure Python, no dependencies. Render your own PPM with a PGM depth map:

```sh
python3 plugins/frame-depth/ft_depth.py render \
  --input photo.ppm --depth-map depth.pgm --output photo-sbs.ppm \
  --strength 0.025 --convergence 0.4 --iterations 5
```

For PNG or JPEG I/O, install optional `Pillow` **in a separate virtual environment**. The same command accepts `.png` files.

## Optional machine-learned depth (experimental)

Run this only where a suitable PyTorch wheel/runtime is already installed, preferably a Linux PC first. In a separate virtual environment install Pillow, Transformers, and PyTorch with platform-appropriate builds.

```sh
python3 plugins/frame-depth/ft_depth.py render \
  --input photo.png --output photo-sbs.png \
  --model depth-anything/Depth-Anything-V2-Small-hf \
  --download-model
```

The `--download-model` flag explicitly authorizes Hugging Face model downloads. Without it, model loading uses only the local cache or a local model directory. No model dependencies are bundled, downloaded during extension discovery, or started by the manager. **This model path has not been benchmarked on the Steam Frame.**

## What works and does not

- Tested offline: synthetic scene, RGB/depth file I/O, per-eye generation, depth scaling, disparity/convergence, and swapped eye order.
- Opt-in model adapter is implemented but untested with real model weights on-device.
- A GLES2 shader reference lives at `gpu/stereo_warp.frag`, but is **not loaded**.
- Reference CPU render is deliberately slow at high resolutions and does not support video.
- The renderer is 2.5D stereo, not real 3D geometry. Missing/occluded edges may halo and positional head parallax is not reconstructed.
- **No compositor API exists yet** for a plugin to receive live screen frames or submit per-eye textures. The extension manager only stages files; installing/enabling this package does not activate any 3D effect.
- No desktop, SteamVR, settings, layout, services or compositor files are modified.

See [LIVE-INTEGRATION.md](LIVE-INTEGRATION.md) for the proposed native hookup and safety/performance acceptance gates.

Tests: `python3 -m unittest discover -s tests -v`.
