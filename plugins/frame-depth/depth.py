#!/usr/bin/env python3
"""Offline reference depth-image-based rendering. No compositor writes."""
import argparse
import json
import math
from pathlib import Path


def synthesize(image, depth, strength=0.035, convergence=0.5, invert=False):
    """Return left/right RGB rows using forward depth splatting and hole filling.

    image: H x W RGB tuples; depth: H x W normalized [0,1] floats.
    Nearer pixels are assumed to have larger depth values. This is a
    reference renderer, not a production-quality disocclusion algorithm.
    """
    if not image or not image[0]:
        raise ValueError("empty image")
    h, w = len(image), len(image[0])
    if len(depth) != h or any(len(row) != w for row in depth):
        raise ValueError("depth dimensions differ")
    if any(len(row) != w for row in image):
        raise ValueError("ragged image")
    if not 0 <= strength <= 0.25 or not 0 <= convergence <= 1:
        raise ValueError("strength must be 0..0.25 and convergence 0..1")
    for row in depth:
        if any(not math.isfinite(v) or v < 0 or v > 1 for v in row):
            raise ValueError("depth must contain finite values in [0,1]")
    results = []
    for sign in (-1, 1):
        if invert:
            sign *= -1
        eye = [[None] * w for _ in range(h)]
        zbuf = [[-1.0] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                z = depth[y][x]
                offset = round(sign * (z - convergence) * strength * w)
                xx = x + offset
                if 0 <= xx < w and z >= zbuf[y][xx]:
                    eye[y][xx] = tuple(image[y][x])
                    zbuf[y][xx] = z
        # Fill disocclusion holes from the nearest populated horizontal pixel.
        for y in range(h):
            known = [x for x, pixel in enumerate(eye[y]) if pixel is not None]
            if not known:
                eye[y] = [tuple(pixel) for pixel in image[y]]
                continue
            for x in range(w):
                if eye[y][x] is None:
                    closest = min(known, key=lambda k: abs(k - x))
                    eye[y][x] = eye[y][closest]
        results.append(eye)
    return tuple(results)


def main():
    parser = argparse.ArgumentParser(description="Offline FrameDepth reference renderer")
    parser.add_argument("--demo", action="store_true", help="print a synthetic stereo example")
    parser.add_argument("--strength", type=float, default=0.035)
    parser.add_argument("--convergence", type=float, default=0.5)
    parser.add_argument("--invert", action="store_true")
    args = parser.parse_args()
    if not args.demo:
        parser.print_help()
        return
    image = [[(x * 20, y * 40, 80) for x in range(12)] for y in range(3)]
    depth = [[x / 11 for x in range(12)] for _ in range(3)]
    left, right = synthesize(image, depth, args.strength, args.convergence, args.invert)
    print(json.dumps({"left": left, "right": right}))


if __name__ == "__main__":
    main()
