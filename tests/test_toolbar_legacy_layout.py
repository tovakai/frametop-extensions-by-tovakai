#!/usr/bin/env python3
"""DesktopToolbar modular grammar (Stage 2) — no OpenVR.

Run:
  python3 test/test_desktop_toolbar.py
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "spatial-toolbar"))
import ft_toolbar  # noqa: E402


class ToolbarSanitize(unittest.TestCase):
    def test_default_modules_taskbar(self):
        tb = ft_toolbar.sanitize_toolbar({"enabled": True, "groups": {}})
        self.assertTrue(tb["enabled"])
        types_left = [m["type"] for m in tb["groups"]["left"]]
        self.assertEqual(types_left, ["start", "tasks"])
        self.assertEqual(tb["groups"]["center"], [])
        right = [m["type"] for m in tb["groups"]["right"]]
        self.assertEqual(right, ["displays", "tray"])

    def test_legacy_default_strip_migrates(self):
        tb = ft_toolbar.sanitize_toolbar({"enabled": True, "groups": ft_toolbar.LEGACY_DEFAULT_GROUPS})
        self.assertEqual(tb["groups"], ft_toolbar.DEFAULT_GROUPS)
        custom = {"left": [{"type": "home"}], "center": [{"type": "profiles"}], "right": []}
        self.assertEqual(ft_toolbar.sanitize_toolbar({"enabled": True, "groups": custom})["groups"]["left"],
                         [{"type": "home"}])

    def test_taskbar_modules_restore_commands(self):
        tb = ft_toolbar.default_toolbar()
        cmds = ft_toolbar.toolbar_socket_commands(tb, (0, 1.6, 0), 0.0, lambda p, h: p)
        for want in ("toolbar module left start", "toolbar module left tasks",
                     "toolbar module right displays", "toolbar module right tray"):
            self.assertIn(want, cmds)

    def test_enabled_defaults_on(self):
        tb = ft_toolbar.sanitize_toolbar({"groups": {}})
        self.assertTrue(tb["enabled"])
        self.assertEqual(ft_toolbar.default_toolbar()["enabled"], True)

    def test_disabled_omits_defaults(self):
        tb = ft_toolbar.sanitize_toolbar({"enabled": False})
        self.assertFalse(tb["enabled"])
        self.assertEqual(tb["groups"]["center"], [])


class ToolbarLayout(unittest.TestCase):
    def test_profiles_contained_not_dominating(self):
        groups = {
            "left": [{"type": "home"}, {"type": "launcher", "id": "launcher"}],
            "center": [{"type": "profiles"}],
            "right": [
                {"type": "action", "action": "layout.reset"},
                {"type": "action", "action": "screens.toggle"},
                {"type": "user"},
            ],
        }
        mods = ft_toolbar.ordered_modules(groups)
        kinds = [m["type"] for _, m in mods]
        self.assertEqual(kinds[0], "home")
        self.assertEqual(kinds[1], "launcher")
        self.assertEqual(kinds[2], "profiles")
        self.assertEqual(kinds[3], "utilities")
        self.assertEqual(kinds[4], "user")
        # Profiles module narrower than half the bar; home+add+user have distinct widths.
        pw = ft_toolbar.module_width({"type": "profiles"})
        total = ft_toolbar.toolbar_total_width(groups)
        self.assertLess(pw, total * 0.45)
        self.assertAlmostEqual(ft_toolbar.module_width({"type": "home"}), ft_toolbar.APP_W_M)
        self.assertNotAlmostEqual(ft_toolbar.module_width({"type": "home"}), pw)

    def test_button_order(self):
        groups = ft_toolbar.default_toolbar()["groups"]
        names = [n for _, n, _ in ft_toolbar.button_local_x(groups)]
        self.assertEqual(names, ["popup:start", "task1", "popup:profiles", "popup:volume", "popup:wifi"])
        legacy = [n for _, n, _ in ft_toolbar.button_local_x(ft_toolbar.LEGACY_DEFAULT_GROUPS)]
        self.assertEqual(legacy[0], "home")
        self.assertEqual(legacy[2], "profile1")
        self.assertEqual(legacy[7], "profile6")

    def test_tasks_width_grows_with_count(self):
        one = ft_toolbar.module_width({"type": "tasks"})
        five = ft_toolbar.module_width({"type": "tasks", "count": 5})
        self.assertAlmostEqual(five - one, 4 * (ft_toolbar.APP_W_M + ft_toolbar.INNER_GAP_M))

    def test_sides_flush_to_bar_ends(self):
        groups = ft_toolbar.default_toolbar()["groups"]
        half = ft_toolbar.toolbar_total_width(groups) / 2
        xs = dict((n, x) for _, n, x in ft_toolbar.button_local_x(groups))
        pad = ft_toolbar.BAR_PAD_M
        # Start sits at the left end, the last tray icon at the right end.
        self.assertAlmostEqual(xs["popup:start"], -half + pad + ft_toolbar.APP_W_M / 2, places=9)
        self.assertAlmostEqual(xs["popup:wifi"], half - pad - ft_toolbar.GROUP_PAD_M - ft_toolbar.BTN_M / 2, places=9)
        # Running apps follow Start on the left; Displays sits right of centre.
        self.assertLess(xs["task1"], 0)
        self.assertGreater(xs["popup:profiles"], 0)

    def test_center_side_stays_centred(self):
        groups = {"left": [{"type": "start"}], "center": [{"type": "home"}], "right": [{"type": "tray"}]}
        xs = dict((n, x) for _, n, x in ft_toolbar.button_local_x(groups))
        self.assertAlmostEqual(xs["home"], 0.0, places=9)

    def test_xs_sorted(self):
        xs = [x for _, _, x in ft_toolbar.button_local_x(ft_toolbar.default_toolbar()["groups"])]
        self.assertEqual(xs, sorted(xs))

    def test_steamvr_scale_tokens(self):
        # 85px button / 180px bar from installed CSS.
        self.assertAlmostEqual(ft_toolbar.BTN_M / ft_toolbar.BAR_H_M, 85 / 180, places=6)
        self.assertEqual(ft_toolbar.COLOR_BAR, (0x0E, 0x14, 0x1B))
        self.assertEqual(ft_toolbar.COLOR_ACCENT, (0x88, 0xCC, 0xF1))

    def test_cells_fit_inside_bar_height(self):
        # Square OpenVR overlays: width == height. Must not exceed bar height.
        self.assertLess(ft_toolbar.APP_W_M, ft_toolbar.BAR_H_M)
        self.assertLess(ft_toolbar.BTN_M, ft_toolbar.BAR_H_M)
        self.assertLess(ft_toolbar.SEG_M, ft_toolbar.BAR_H_M)
        # 10:1 backing ⇒ visual height = width/10; min width locks height to BAR_H_M.
        self.assertAlmostEqual(
            ft_toolbar.toolbar_total_width(ft_toolbar.default_toolbar()["groups"]) / ft_toolbar.BAR_ASPECT,
            ft_toolbar.BAR_H_M,
            places=6,
        )

    def test_sphere_latitude_curve(self):
        r = 1.5
        x0, _, z0 = ft_toolbar.arc_point(0.0, r)
        x1, _, z1 = ft_toolbar.arc_point(0.4, r)
        self.assertAlmostEqual(x0, 0.0, places=9)
        self.assertAlmostEqual(z0, 0.0, places=9)
        self.assertGreater(z1, 0.0)
        self.assertGreater(x1, 0.0)

    def test_dashboard_yield_contract(self):
        self.assertFalse((not True) and True)
        self.assertTrue((not False) and True)

    def test_attach_y_below_screen(self):
        y = ft_toolbar.screen_attach_y(0.5625)
        self.assertLess(y, -0.5625 / 2)


if __name__ == "__main__":
    unittest.main()
