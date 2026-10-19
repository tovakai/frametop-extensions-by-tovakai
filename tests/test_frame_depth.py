"""Headset-free stereo tests. No model downloads or services."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "frame-depth"
sys.path.insert(0, str(PLUGIN))
from depth_core import (DepthMap, RGBImage, StereoSettings, demo_scene, read_pgm, read_ppm,
                        render_eye, stereo_pair, write_pgm, write_ppm)  # noqa: E402


class FrameDepthTests(unittest.TestCase):
    def test_neutral_convergence(self):
        image, _ = demo_scene(32, 16)
        depth = DepthMap(32, 16, (0.4,) * (32 * 16))
        result = stereo_pair(image, depth, StereoSettings())
        row = 32 * 3
        for y in range(16):
            self.assertEqual(result.pixels[y * 2 * row:(y + 1) * 2 * row],
                             image.pixels[y * row:(y + 1) * row] * 2)

    def test_zero_disparity_and_eye_symmetry(self):
        img, d = demo_scene(40, 20)
        zero = stereo_pair(img, d, StereoSettings(strength=0))
        self.assertEqual(zero.width, 80)
        self.assertEqual(zero.height, 20)
        self.assertEqual(zero.pixels[:40 * 3], img.pixels[:40 * 3])
        settings = StereoSettings(strength=0.06)
        normal = stereo_pair(img, d, settings)
        swapped = stereo_pair(img, d, StereoSettings(strength=.06, swap_eyes=True))
        row = img.width * 3
        for y in range(img.height):
            a = normal.pixels[y * row * 2:(y + 1) * row * 2]
            b = swapped.pixels[y * row * 2:(y + 1) * row * 2]
            self.assertEqual(a[:row], b[row:])
            self.assertEqual(a[row:], b[:row])
        self.assertNotEqual(render_eye(img, d, settings, -1).pixels,
                            render_eye(img, d, settings, +1).pixels)

    def test_depth_resolution_independence(self):
        img, _ = demo_scene(20, 10)
        depth = DepthMap(1, 1, (.6,))
        self.assertEqual(stereo_pair(img, depth, StereoSettings()).width, 40)

    def test_invalid_data_fails_closed(self):
        with self.assertRaises(ValueError):
            RGBImage(20, 10, b"x")
        with self.assertRaises(ValueError):
            DepthMap(2, 1, (float("nan"), 0))
        with self.assertRaises(ValueError):
            StereoSettings(strength=-1)
        with self.assertRaises(ValueError):
            StereoSettings(convergence=1.2)
        with self.assertRaises(ValueError):
            StereoSettings(iterations=0)
        img, d = demo_scene()
        with self.assertRaises(ValueError):
            render_eye(img, d, StereoSettings(), 0)

    def test_pnm_roundtrip_pixel_start_whitespace(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            img = RGBImage(1, 1, b"\x20\x0a\xff")
            depth = DepthMap(1, 1, (0.5,))
            write_ppm(root / "i.ppm", img)
            write_pgm(root / "d.pgm", depth)
            self.assertEqual(read_ppm(root / "i.ppm"), img)
            self.assertAlmostEqual(read_pgm(root / "d.pgm").values[0], .5, delta=.003)
            (root / "comment.ppm").write_bytes(b"P6\n# test\n1 1\n255\n" + img.pixels)
            self.assertEqual(read_ppm(root / "comment.ppm"), img)
            (root / "bad.ppm").write_bytes(b"P6\n1 1\n255\nX")
            with self.assertRaises(ValueError):
                read_ppm(root / "bad.ppm")

    def test_cli_demo_and_explicit_depth(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            entry = PLUGIN / "ft_depth.py"
            proc = subprocess.run([sys.executable, str(entry), "demo", "--output-dir", str(root)],
                                  capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(read_ppm(root / "stereo.ppm").width, 480)
            proc = subprocess.run([sys.executable, str(entry), "render", "--input",
                                   str(root / "source.ppm"), "--depth-map", str(root / "depth.pgm"),
                                   "--output", str(root / "second.ppm")],
                                  capture_output=True, text=True, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            a = read_ppm(root / "stereo.ppm").pixels
            b = read_ppm(root / "second.ppm").pixels
            self.assertLessEqual(max(abs(x - y) for x, y in zip(a, b)), 2)

    def test_import_does_not_start_inference_or_write(self):
        module = importlib.util.spec_from_file_location("ft_depth", PLUGIN / "ft_depth.py")
        loaded = importlib.util.module_from_spec(module)
        module.loader.exec_module(loaded)
        self.assertIsNotNone(loaded.estimate_depth)


if __name__ == "__main__":
    unittest.main()
