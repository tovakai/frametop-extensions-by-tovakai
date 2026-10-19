import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("frame_depth", ROOT / "plugins/frame-depth/depth.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FrameDepthTests(unittest.TestCase):
    def setUp(self):
        self.image = [[(x, 0, 0) for x in range(20)]]
        self.depth = [[x / 19 for x in range(20)]]

    def test_zero_strength_preserves_image(self):
        left, right = module.synthesize(self.image, self.depth, strength=0)
        self.assertEqual(left, self.image)
        self.assertEqual(right, self.image)

    def test_swap_eyes(self):
        left, right = module.synthesize(self.image, self.depth, strength=0.2)
        swapped_left, swapped_right = module.synthesize(
            self.image, self.depth, strength=0.2, invert=True
        )
        self.assertEqual(left, swapped_right)
        self.assertEqual(right, swapped_left)

    def test_disparity_produces_different_eyes(self):
        left, right = module.synthesize(self.image, self.depth, strength=0.2)
        self.assertNotEqual(left, right)

    def test_invalid_depth(self):
        with self.assertRaises(ValueError):
            module.synthesize(self.image, [[float("nan")] * 20])
        with self.assertRaises(ValueError):
            module.synthesize(self.image, [[0.5]])
        with self.assertRaises(ValueError):
            module.synthesize(self.image, [[2.0] * 20])

    def test_invalid_strength(self):
        with self.assertRaises(ValueError):
            module.synthesize(self.image, self.depth, strength=1)

    def test_nearer_pixel_wins_collision(self):
        image = [[(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]]
        depth = [[0.0, 0.0, 1.0, 0.0]]
        left, right = module.synthesize(image, depth, strength=0.25, convergence=0)
        self.assertEqual(right[3], (0, 0, 255))


if __name__ == "__main__":
    unittest.main()
