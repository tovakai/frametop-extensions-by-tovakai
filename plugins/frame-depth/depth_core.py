"""Portable, dependency-free *still-image* stereo renderer.

The renderer is intentionally independent of SteamVR, PyTorch, and Frametop's
compositor. It gives us a deterministic test oracle before a native GPU
pipeline is connected to Frametop. Depth is relative: 0 far, 1 near.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

MAX_PIXELS = 20_000_000


@dataclass(frozen=True)
class RGBImage:
    width: int
    height: int
    pixels: bytes

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1 or self.width * self.height > MAX_PIXELS:
            raise ValueError("image dimensions outside supported range")
        if len(self.pixels) != self.width * self.height * 3:
            raise ValueError("RGB image must contain exactly width * height * 3 bytes")


@dataclass(frozen=True)
class DepthMap:
    width: int
    height: int
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1 or self.width * self.height > MAX_PIXELS:
            raise ValueError("depth map dimensions outside supported range")
        if len(self.values) != self.width * self.height:
            raise ValueError("depth map shape mismatch")
        if any(not math.isfinite(v) or not 0.0 <= v <= 1.0 for v in self.values):
            raise ValueError("depth values must be finite and between 0 and 1")


@dataclass(frozen=True)
class StereoSettings:
    strength: float = 0.025  # normalized horizontal disparity per eye, not metres
    convergence: float = 0.4  # depth at the physical screen plane
    iterations: int = 5
    swap_eyes: bool = False

    def __post_init__(self) -> None:
        if not math.isfinite(self.strength) or not 0 <= self.strength <= 0.10:
            raise ValueError("strength must be in [0, 0.10]")
        if not math.isfinite(self.convergence) or not 0 <= self.convergence <= 1:
            raise ValueError("convergence must be in [0, 1]")
        if not isinstance(self.iterations, int) or not 1 <= self.iterations <= 16:
            raise ValueError("iterations must be in [1, 16]")


def _linear_sample(values: tuple[float, ...], width: int, height: int, u: float, v: float) -> float:
    x = max(0.0, min(1.0, u)) * (width - 1)
    y = max(0.0, min(1.0, v)) * (height - 1)
    x0, y0 = int(x), int(y)
    x1, y1 = min(x0 + 1, width - 1), min(y0 + 1, height - 1)
    tx, ty = x - x0, y - y0
    a = values[y0 * width + x0] * (1 - tx) + values[y0 * width + x1] * tx
    b = values[y1 * width + x0] * (1 - tx) + values[y1 * width + x1] * tx
    return a * (1 - ty) + b * ty


def _sample_rgb(image: RGBImage, x: float, y: int, output: bytearray, offset: int) -> None:
    x = max(0.0, min(image.width - 1, x))
    x0 = int(x)
    x1 = min(x0 + 1, image.width - 1)
    t = x - x0
    p0 = 3 * (y * image.width + x0)
    p1 = 3 * (y * image.width + x1)
    for k in range(3):
        output[offset + k] = round(image.pixels[p0 + k] * (1 - t) + image.pixels[p1 + k] * t)


def render_eye(color: RGBImage, depth: DepthMap, settings: StereoSettings, eye: int) -> RGBImage:
    """Inverse depth warp. eye=-1 left, +1 right; horizontal, no camera translation.

    Clamps exposed image boundaries; foreground edges may show occlusion halos.
    This reference implementation prioritizes testability over frame-rate.
    """
    if eye not in (-1, 1):
        raise ValueError("eye must be -1 (left) or +1 (right)")
    w, h = color.width, color.height
    out = bytearray(len(color.pixels))
    sign = -eye if settings.swap_eyes else eye
    for y in range(h):
        v = y / max(1, h - 1)
        for x in range(w):
            u = x / max(1, w - 1)
            src = u
            for _ in range(settings.iterations):
                d = _linear_sample(depth.values, depth.width, depth.height, src, v)
                src = u + sign * settings.strength * (d - settings.convergence)
            _sample_rgb(color, src * (w - 1), y, out, 3 * (y * w + x))
    return RGBImage(w, h, bytes(out))


def stereo_pair(color: RGBImage, depth: DepthMap, settings: StereoSettings) -> RGBImage:
    """Return full-width side-by-side image: left eye | right eye."""
    if color.width * color.height > MAX_PIXELS // 2:
        raise ValueError("stereo output would exceed pixel limit")
    left = render_eye(color, depth, settings, -1)
    right = render_eye(color, depth, settings, 1)
    row_bytes = 3 * color.width
    result = bytearray()
    for row in range(color.height):
        start = row * row_bytes
        end = start + row_bytes
        result.extend(left.pixels[start:end])
        result.extend(right.pixels[start:end])
    return RGBImage(color.width * 2, color.height, bytes(result))


def _read_pnm(path: str | Path, expected_magic: bytes) -> tuple[int, int, bytes]:
    """Strict P5/P6 parser. Supports comments in header, 8-bit maxval only."""
    blob = Path(path).read_bytes()
    pos = 0

    def token() -> bytes:
        nonlocal pos
        while pos < len(blob):
            if blob[pos] in b" \r\n\t":
                pos += 1
            elif blob[pos] == 35:
                n = blob.find(b"\n", pos)
                if n < 0:
                    raise ValueError("unfinished PNM comment")
                pos = n + 1
            else:
                break
        start = pos
        while pos < len(blob) and blob[pos] not in b" \r\n\t#":
            pos += 1
        if pos == start:
            raise ValueError("incomplete PNM header")
        return blob[start:pos]

    try:
        magic, w, h, maxval = token(), int(token()), int(token()), int(token())
    except (ValueError, OverflowError) as exc:
        raise ValueError("invalid PNM header") from exc
    if magic != expected_magic or maxval != 255:
        raise ValueError("expected 8-bit " + expected_magic.decode("ascii") + " image")
    if w < 1 or h < 1 or w * h > MAX_PIXELS:
        raise ValueError("invalid PNM dimensions")
    # Binary raster starts immediately after one mandatory separator. Do not skip
    # whitespace there: the first pixel itself may be whitespace.
    if pos >= len(blob) or blob[pos] not in b" \r\n\t":
        raise ValueError("missing PNM raster separator")
    pos += 1
    if blob[pos - 1:pos] == b"\r" and blob[pos:pos + 1] == b"\n":
        pos += 1
    channels = 3 if magic == b"P6" else 1
    data = blob[pos:]
    if len(data) != w * h * channels:
        raise ValueError("PNM raster size mismatch")
    return w, h, data


def read_ppm(path: str | Path) -> RGBImage:
    w, h, data = _read_pnm(path, b"P6")
    return RGBImage(w, h, data)


def read_pgm(path: str | Path) -> DepthMap:
    w, h, data = _read_pnm(path, b"P5")
    return DepthMap(w, h, tuple(v / 255.0 for v in data))


def write_ppm(path: str | Path, image: RGBImage) -> None:
    Path(path).write_bytes(f"P6\n{image.width} {image.height}\n255\n".encode() + image.pixels)


def write_pgm(path: str | Path, depth: DepthMap) -> None:
    pixels = bytes(round(max(0, min(1, v)) * 255) for v in depth.values)
    Path(path).write_bytes(f"P5\n{depth.width} {depth.height}\n255\n".encode() + pixels)


def demo_scene(width: int = 240, height: int = 135) -> tuple[RGBImage, DepthMap]:
    """Generate deterministic colours + depth with a foreground rectangle."""
    if width < 8 or height < 8 or width * height > MAX_PIXELS // 2:
        raise ValueError("demo dimensions must be >=8 and fit pixel limit")
    pixels = bytearray()
    depths: list[float] = []
    for y in range(height):
        for x in range(width):
            foreground = width // 4 <= x < (3 * width) // 4 and height // 4 <= y < (3 * height) // 4
            if foreground:
                pixels.extend((255, 194, 48))
                depths.append(0.88)
            else:
                pixels.extend((round(40 + 110 * x / (width - 1)),
                               round(70 + 90 * y / (height - 1)), 200))
                depths.append(0.14)
    return RGBImage(width, height, bytes(pixels)), DepthMap(width, height, tuple(depths))
