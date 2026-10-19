#!/usr/bin/env python3
"""Offline FrameDepth-inspired stereoscopic preview tool for Frametop.

No SteamVR, compositor, GPU, model, service, or user settings are touched.
"demo" needs only stdlib; PNG and model estimation are optional imports.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from depth_core import (DepthMap, RGBImage, StereoSettings, demo_scene, read_pgm, read_ppm,
                        stereo_pair, write_pgm, write_ppm)

DEFAULT_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"


def open_rgb(path: Path) -> RGBImage:
    if path.suffix.lower() == ".ppm":
        return read_ppm(path)
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("PNG/JPG input requires Pillow; use .ppm or install pillow") from exc
    with Image.open(path) as opened:
        img = opened.convert("RGB")
        return RGBImage(img.width, img.height, img.tobytes())


def open_depth(path: Path) -> DepthMap:
    if path.suffix.lower() == ".pgm":
        return read_pgm(path)
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("PNG depth-map input requires Pillow; use .pgm or install pillow") from exc
    with Image.open(path) as opened:
        img = opened.convert("L")
        return DepthMap(img.width, img.height, tuple(v / 255.0 for v in img.tobytes()))


def save_rgb(path: Path, image: RGBImage) -> None:
    if path.suffix.lower() == ".ppm":
        write_ppm(path, image)
        return
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("PNG/JPG output requires Pillow; use .ppm or install pillow") from exc
    Image.frombytes("RGB", (image.width, image.height), image.pixels).save(path)


def estimate_depth(image: RGBImage, model_id: str, device: str, allow_download: bool) -> DepthMap:
    """Opt-in, unbenchmarked Transformers adapter; model files stay outside extension."""
    try:
        import torch
        from torch.nn import functional as F
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("model inference requires torch, transformers and Pillow") from exc
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    opts = {"local_files_only": not allow_download, "trust_remote_code": False}
    try:
        processor = AutoImageProcessor.from_pretrained(model_id, **opts)
        model = AutoModelForDepthEstimation.from_pretrained(model_id, **opts).to(device).eval()
    except (OSError, ValueError) as exc:
        raise RuntimeError("model unavailable; supply a local model path or explicitly use --download-model") from exc
    picture = Image.frombytes("RGB", (image.width, image.height), image.pixels)
    inp = processor(images=picture, return_tensors="pt")
    with torch.inference_mode():
        output = model(pixel_values=inp["pixel_values"].to(device)).predicted_depth
        output = F.interpolate(output.unsqueeze(1), size=(image.height, image.width),
                               mode="bicubic", align_corners=False).squeeze().float()
        values = output.cpu().flatten().tolist()
    ordered = sorted(values)
    low = ordered[int((len(ordered) - 1) * .02)]
    high = ordered[int((len(ordered) - 1) * .98)]
    span = max(1e-9, high - low)
    return DepthMap(image.width, image.height,
                    tuple(min(1.0, max(0.0, (v - low) / span)) for v in values))


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="FrameDepth-style stereo still-image experiment")
    sub = ap.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="generate a test scene + depth map + stereo pair, without dependencies")
    demo.add_argument("--output-dir", type=Path, required=True)
    demo.add_argument("--width", type=int, default=240)
    demo.add_argument("--height", type=int, default=135)
    render = sub.add_parser("render", help="render one image using a supplied depth map or opt-in model")
    render.add_argument("--input", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--depth-map", type=Path, help="greyscale depth, brighter is nearer")
    render.add_argument("--model", default=DEFAULT_MODEL, help="Hugging Face ID or local model directory")
    render.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    render.add_argument("--download-model", action="store_true", help="explicitly allow network model download")
    for cmd in (demo, render):
        cmd.add_argument("--strength", type=float, default=0.025)
        cmd.add_argument("--convergence", type=float, default=0.4)
        cmd.add_argument("--iterations", type=int, default=5)
        cmd.add_argument("--swap-eyes", action="store_true")
    sub.add_parser("doctor", help="show exactly which optional local libraries are available")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            from importlib.util import find_spec
            for package in ("PIL", "torch", "transformers"):
                print(f"{package}: {'available' if find_spec(package) else 'missing'}")
            print("Runtime integration: unavailable (Frametop has no stereo effect API)")
            return 0
        settings = StereoSettings(args.strength, args.convergence, args.iterations,
                                  args.swap_eyes)
        if args.command == "demo":
            args.output_dir.mkdir(parents=True, exist_ok=True)
            image, depth = demo_scene(args.width, args.height)
            write_ppm(args.output_dir / "source.ppm", image)
            write_pgm(args.output_dir / "depth.pgm", depth)
            output = args.output_dir / "stereo.ppm"
        else:
            image = open_rgb(args.input)
            depth = (open_depth(args.depth_map) if args.depth_map else
                     estimate_depth(image, args.model, args.device, args.download_model))
            output = args.output
        save_rgb(output, stereo_pair(image, depth, settings))
        print(f"Stereo preview: {output} ({image.width * 2}x{image.height}, side by side)")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"frame-depth: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
