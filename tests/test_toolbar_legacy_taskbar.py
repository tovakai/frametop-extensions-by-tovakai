#!/usr/bin/env python3
"""Taskbar model tests: task merge/dedupe, click decisions, popup exclusivity, layouts,
provider parsers, network safety rules and the ft-screens wire formats. Pure Python."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "plugins", "spatial-toolbar"))

import ft_taskbar_model as m  # noqa: E402

APPS = [
    {"id": "org.kde.konsole.desktop", "name": "Konsole", "icon": "utilities-terminal",
     "categories": ["System", "TerminalEmulator"], "wm_class": ""},
    {"id": "firefox.desktop", "name": "Firefox", "icon": "firefox", "categories": ["Network"],
     "wm_class": "firefox"},
    {"id": "code.desktop", "name": "Code", "icon": "vscode", "categories": ["Development"],
     "wm_class": "Code"},
]


def win(i, desktop="", cls="", caption="w", minimized=False):
    return {"id": str(i), "desktop": desktop, "cls": cls, "caption": caption, "minimized": minimized}


class Tasks(unittest.TestCase):
    def test_pinned_first_then_running_deduped(self):
        tasks = m.merge_tasks(["firefox.desktop"],
                              [win(1, "org.kde.konsole"), win(2, "firefox"), win(3, "", "firefox")],
                              APPS, active="3")
        self.assertEqual([t["id"] for t in tasks], ["firefox", "org.kde.konsole"])
        ff = tasks[0]
        self.assertTrue(ff["pinned"])
        self.assertEqual([w["id"] for w in ff["windows"]], ["2", "3"])
        self.assertTrue(ff["focused"])
        self.assertFalse(tasks[1]["pinned"])

    def test_match_by_wm_class_and_short_id(self):
        tasks = m.merge_tasks([], [win(1, "", "Code"), win(2, "konsole")], APPS)
        self.assertEqual([t["desktop_id"] for t in tasks], ["code.desktop", "org.kde.konsole.desktop"])

    def test_unknown_window_gets_own_task(self):
        tasks = m.merge_tasks([], [win(9, "", "xterm", "shell")], APPS)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["name"], "shell")

    def test_pin_without_app_kept(self):
        tasks = m.merge_tasks(["gone.desktop"], [], APPS)
        self.assertEqual(tasks[0]["desktop_id"], "gone.desktop")
        self.assertEqual(m.task_click(tasks[0]), ("launch", "gone.desktop"))

    def test_click_launch_focus_expose(self):
        t0 = m.merge_tasks(["firefox.desktop"], [], APPS)[0]
        self.assertEqual(m.task_click(t0), ("launch", "firefox.desktop"))
        t1 = m.merge_tasks([], [win(5, "firefox")], APPS)[0]
        self.assertEqual(m.task_click(t1), ("focus", "5"))
        t2 = m.merge_tasks([], [win(5, "firefox"), win(6, "firefox")], APPS)[0]
        self.assertEqual(m.task_click(t2), ("expose", "firefox"))

    def test_click_focused_task_minimizes(self):
        t = m.merge_tasks([], [win(5, "firefox")], APPS, active="5")[0]
        self.assertEqual(m.task_click(t), ("minimize", "5"))
        t = m.merge_tasks([], [win(5, "firefox", minimized=True)], APPS, active="5")[0]
        self.assertEqual(m.task_click(t), ("focus", "5"))  # minimized: restore it

    def test_output_order_is_screen_order(self):
        self.assertEqual(m.output_order(["WL-10", "WL-1", "WL-0", "WL-2", ""]), ["WL-0", "WL-1", "WL-2", "WL-10"])


class TaskMenu(unittest.TestCase):
    ACTIONS = [{"id": "new-private-window", "name": "New Private Window", "exec": "firefox --private"}]

    def task(self, *wins, pinned=()):
        return m.merge_tasks(list(pinned), list(wins), APPS)[0]

    def ids(self, layout):
        return [it["id"] for it in layout["items"]]

    def test_running_window(self):
        w = dict(win(5, "firefox"), output="WL-0")
        lay = m.task_menu_layout(self.task(w), self.ACTIONS, ["WL-0", "WL-1", "WL-2"], True)
        self.assertEqual(self.ids(lay), ["act:new-private-window", "new", "min", "max", "above", "full",
                                         "send:2", "send:3", "pin", "close"])
        labels = {it["id"]: it["label"] for it in lay["items"]}
        self.assertEqual(labels["send:2"], "Send to desktop 2")
        self.assertEqual(labels["pin"], "Pin to taskbar")
        self.assertEqual(labels["close"], "Close window")
        for it in lay["items"]:
            self.assertTrue(inside(it, lay), it)

    def test_app_new_window_replaces_ours(self):
        acts = [{"id": "new-window", "name": "New Window", "exec": "chromium"}]
        lay = m.task_menu_layout(self.task(dict(win(5, "firefox"), output="WL-0")), acts, ["WL-0"], True)
        self.assertEqual(self.ids(lay)[:2], ["act:new-window", "min"])

    def test_state_labels(self):
        w = dict(win(5, "firefox", minimized=True), output="WL-1", maximized=True, above=True)
        lay = m.task_menu_layout(self.task(w, pinned=["firefox.desktop"]), [], ["WL-0", "WL-1"], True)
        items = {it["id"]: it for it in lay["items"]}
        self.assertEqual(items["min"]["label"], "Restore")
        self.assertEqual(items["max"]["label"], "Restore size")
        self.assertTrue(items["above"]["active"])
        self.assertFalse(items["full"]["active"])
        self.assertEqual(items["pin"]["label"], "Unpin from taskbar")
        self.assertIn("send:1", items)
        self.assertNotIn("send:2", items)  # already there

    def test_windows_on_several_desktops_offer_all(self):
        a, b = dict(win(5, "firefox"), output="WL-0"), dict(win(6, "firefox"), output="WL-1")
        lay = m.task_menu_layout(self.task(a, b), [], ["WL-0", "WL-1"], True)
        self.assertIn("send:1", self.ids(lay))
        self.assertIn("send:2", self.ids(lay))
        self.assertEqual(lay["items"][-1]["label"], "Close all 2 windows")

    def test_pinned_not_running(self):
        lay = m.task_menu_layout(self.task(pinned=["firefox.desktop"]), self.ACTIONS, ["WL-0"], True)
        self.assertEqual(self.ids(lay), ["act:new-private-window", "new", "pin"])
        self.assertEqual(lay["items"][1]["label"], "Open")

    def test_unknown_app_has_window_commands_only(self):
        lay = m.task_menu_layout(self.task(win(7, "", "someclass")), [], ["WL-0", "WL-1"], False)
        self.assertEqual(self.ids(lay), ["min", "max", "above", "full", "send:1", "send:2", "close"])

    def test_toggle_pin(self):
        p = m.toggle_pin([], "firefox.desktop")
        self.assertEqual(p, ["firefox.desktop"])
        self.assertEqual(m.toggle_pin(p, "FIREFOX"), [])


class Popups(unittest.TestCase):
    def test_one_at_a_time_and_toggle(self):
        s = m.PopupState()
        self.assertTrue(s.open("start"))
        self.assertTrue(s.open("volume"))
        self.assertEqual(s.kind, "volume")
        self.assertFalse(s.open("volume"))
        self.assertFalse(s.is_open())
        self.assertRaises(ValueError, s.open, "bogus")

    def test_click_away_and_visibility(self):
        s = m.PopupState()
        s.open("wifi")
        s.on_click_elsewhere(on_popup=True, on_toolbar=False)
        self.assertTrue(s.is_open())
        s.on_click_elsewhere(on_popup=False, on_toolbar=True)
        self.assertTrue(s.is_open())
        s.on_click_elsewhere(on_popup=False, on_toolbar=False)
        self.assertFalse(s.is_open())
        s.open("profiles")
        s.on_visibility(False)
        self.assertFalse(s.is_open())


def inside(item, layout):
    return 0 <= item["x"] and 0 <= item["y"] and item["x"] + item["w"] <= layout["w"] and \
        item["y"] + item["h"] <= layout["h"]


class Layouts(unittest.TestCase):
    def check(self, layout):
        for it in layout["items"]:
            self.assertTrue(inside(it, layout), it)
        ids = [it["id"] for it in layout["items"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_start(self):
        apps = [dict(APPS[i % 3], id=f"a{i}.desktop", name=f"App {i}") for i in range(40)]
        cats = m.start_categories(apps)
        self.assertEqual(cats[0], ("All", ""))
        self.assertIn(("Internet", "Network"), cats)
        self.assertNotIn(("Games", "Game"), cats)
        page, p, pages = m.start_page(apps, "", 9)
        self.assertEqual((p, pages, len(page)), (2, 3, 8))
        net, _, _ = m.start_page(apps, "Network", 0)
        self.assertTrue(all("Network" in a["categories"] for a in net))
        lay = m.start_layout(page, cats, "", p, pages, ["a33.desktop"])
        self.check(lay)
        pins = {it["id"]: it["pinned"] for it in lay["items"] if it["kind"] == "pin"}
        self.assertTrue(pins["pin:a33.desktop"])
        self.assertFalse(pins["pin:a34.desktop"])
        nav = {it["id"]: it["enabled"] for it in lay["items"] if it["kind"] == "nav"}
        self.assertEqual(nav, {"page:prev": True, "page:next": False})

    def test_lists(self):
        self.check(m.volume_layout(0.4, False, "Speakers"))
        nets = m.merge_networks([{"ssid": "Home", "strength": 70, "secure": True}], {"Home"}, "Home")
        self.check(m.wifi_layout(True, nets))
        off = m.wifi_layout(False, nets)
        self.assertFalse(any(it["kind"] == "network" for it in off["items"]))
        prof = m.profiles_layout(["desk", "couch"], "couch", [None, "desk", None])
        self.check(prof)
        rows = {it["id"]: it for it in prof["items"]}
        self.assertTrue(rows["profile:couch"]["active"])
        self.assertEqual(rows["profile:desk"]["badge"], "2")
        self.assertIn("settings", rows)
        self.assertEqual(m.profiles_layout(["a"], "", {"3": "a"})["items"][0]["badge"], "3")
        empty = m.profiles_layout([], "", [])
        self.assertEqual(empty["items"][0]["enabled"], False)
        wl = m.windows_layout({"name": "Firefox", "windows": [{"id": "1", "caption": "A"},
                                                              {"id": "2", "caption": "B", "minimized": True}]})
        self.check(wl)
        self.assertEqual([it["id"] for it in wl["items"]], ["win:1", "win:2"])


class Providers(unittest.TestCase):
    def test_wpctl(self):
        self.assertEqual(m.parse_wpctl_volume("Volume: 0.45\n"), (0.45, False))
        self.assertEqual(m.parse_wpctl_volume("Volume: 0.30 [MUTED]\n"), (0.30, True))
        self.assertEqual(m.parse_wpctl_volume(""), (0.0, False))
        self.assertEqual(m.parse_wpctl_description('  * node.description = "Frame Speakers"\n'), "Frame Speakers")
        self.assertEqual(m.parse_wpctl_description('node.nick = "Nick"'), "Nick")
        self.assertEqual([m.volume_glyph_level(v, False) for v in (0, 0.2, 0.5, 0.9)], [0, 1, 2, 3])
        self.assertEqual(m.volume_glyph_level(0.9, True), 0)

    def test_networks(self):
        self.assertEqual([m.signal_bars(s) for s in (0, 20, 50, 70, 95)], [0, 1, 2, 3, 4])
        aps = [{"ssid": "Cafe", "strength": 40, "secure": False},
               {"ssid": "Home", "strength": 30, "secure": True},
               {"ssid": "Home", "strength": 80, "secure": True},
               {"ssid": "Neighbour", "strength": 90, "secure": True},
               {"ssid": "", "strength": 99, "secure": False}]
        nets = m.merge_networks(aps, {"Home"}, "Home")
        self.assertEqual([n["ssid"] for n in nets], ["Home", "Neighbour", "Cafe"])
        self.assertEqual(nets[0]["strength"], 80)
        self.assertEqual(m.merge_networks(aps, set(), "")[0]["key"],
                         m.merge_networks(aps, set(), "")[0]["key"])  # stable keys
        by = {n["ssid"]: n for n in nets}
        self.assertEqual(m.network_click(by["Home"]), "activate")
        self.assertEqual(m.network_click(by["Cafe"]), "connect-open")
        # A secured network we have no secret for never gets a password prompt here.
        self.assertEqual(m.network_click(by["Neighbour"]), "settings")


class Wire(unittest.TestCase):
    def test_items_text(self):
        lay = m.profiles_layout(["my desk"], "my desk", [])
        txt = m.items_text("profiles", 7, lay, lay["w"] / m.PX_PER_M).splitlines()
        self.assertEqual(txt[0].split()[:3], ["popup", "profiles", "7"])
        self.assertIn("item profile:my%20desk", txt[1])
        self.assertTrue(all(len(line.split()) == 6 for line in txt[1:]))
        disabled = m.items_text("profiles", 1, m.profiles_layout([], "", []), 0.42)
        self.assertNotIn("item none", disabled)

    def test_tasks_text(self):
        tasks = m.merge_tasks(["firefox.desktop"], [win(1, "firefox"), win(2, "firefox")], APPS, "1")
        txt = m.tasks_text(3, tasks, {"firefox": "/run/x/firefox.png"}).splitlines()
        self.assertEqual(txt[0], "tasks 3 1")
        self.assertEqual(txt[1].split("\t"), ["task", "firefox", "1", "2", "1", "/run/x/firefox.png", "Firefox"])


class DesktopActions(unittest.TestCase):
    def test_listed_actions_in_order(self):
        import tempfile
        import ft_desktop
        body = ("[Desktop Entry]\nType=Application\nName=Chromium\nExec=chromium %U\n"
                "Actions=new-window;new-private-window;broken;\n\n"
                "[Desktop Action new-private-window]\nName=New Incognito Window\nName[de]=Neues Inkognito-Fenster\n"
                "Exec=chromium --incognito\n\n"
                "[Desktop Action new-window]\nName=New Window\nExec=chromium\n\n"
                "[Desktop Action broken]\nName=No exec\n\n"
                "[Desktop Action unlisted]\nName=Hidden\nExec=x\n")
        with tempfile.NamedTemporaryFile("w", suffix=".desktop", delete=False) as f:
            f.write(body)
        try:
            acts = ft_desktop.desktop_actions(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual([(a["id"], a["name"]) for a in acts],
                         [("new-window", "New Window"), ("new-private-window", "New Incognito Window")])
        self.assertEqual(ft_desktop.argv_from_desktop_exec(acts[1]["exec"]), ["chromium", "--incognito"])
        self.assertEqual(ft_desktop.desktop_actions("/nonexistent.desktop"), [])


class Guards(unittest.TestCase):
    """Things the spec rules out, checked in the sources."""

    def read(self, rel):
        # Assert original behavior against preserved legacy source, not core.
        path = os.path.join(ROOT, "plugins", "spatial-toolbar", "reference",
                            os.path.basename(rel))
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_task_menu_wiring(self):
        bar = self.read("screens/desktop_toolbar.inc")
        inc = self.read("screens/toolbar_taskbar.inc")
        src = self.read("session/ft-taskbar.py")
        # Right-click on a task tile opens its menu; popups face the head, upright.
        self.assertIn('OpenPopup("taskmenu", b.action.substr(5), b.action);', bar)
        self.assertIn("VRMouseButton_Right", bar)
        self.assertIn("return PanelPose(x, y, z, yaw, pitch, 0);", inc)
        self.assertIn("Mul(FacingHead(at),", inc)
        # The KWin side: window state for the menu, one-shot ops, outputs by name.
        for s in ("maximized: maximized(w)", "outputs: workspace.screens", "workspace.sendClientToScreen(w,",
                  '"minimize": "w.minimized = true;"', 'self.kwin.window_op("minimize", [arg])'):
            self.assertIn(s, src)

    def test_no_password_or_scraping(self):
        src = self.read("session/ft-taskbar.py")
        self.assertNotIn("psk", src.lower())
        self.assertNotIn("password", src.lower().replace("never a password prompt", ""))
        self.assertNotIn("/proc", src)
        self.assertNotIn('"ps"', src)
        self.assertIn("org.frametop.Taskbar", src)
        self.assertIn("workspace.windowList()", src)

    def test_cpp_popup_rules(self):
        inc = self.read("screens/toolbar_taskbar.inc")
        bar = self.read("screens/desktop_toolbar.inc")
        # One popup at a time: opening another closes the current one first.
        open_body = inc.split("void OpenPopup(")[1].split("\n}\n")[0]
        self.assertIn("ClosePopup(true);", open_body)
        # Closes when the toolbar hides (dashboard / desktop mode) and on click-away.
        self.assertIn("if (TaskbarPopupOpen() && !g_toolbar.visible) ClosePopup(true);", bar)
        self.assertIn("CheckPopupClickAway(", bar)
        self.assertIn("!g_taskbar.hoverPopup && !onToolbar", inc)
        # Above the toolbar cells (3), highlight above the popup; no input on the highlight.
        self.assertIn("kSortPopup = 4, kSortHilite = 5", inc)
        self.assertIn("SetOverlayInputMethod(g_taskbar.hilite, vr::VROverlayInputMethod_None)", inc)
        # OpenVR mouse y is bottom-up; hit test flips it, and the last (topmost) rect wins.
        self.assertIn("g_taskbar.texH - ev.data.mouse.y", inc)
        self.assertIn("for (int i = int(g_taskbar.items.size()) - 1; i >= 0; --i)", inc)
        # Follows the toolbar: placed from PlaceToolbar with the bar's visual pose.
        self.assertIn("PlaceTaskbarPopup(p, u);", bar)
        # Interaction keeps the toolbar awake while a popup is open (attention).
        self.assertIn("TaskbarPopupOpen()", bar.split("bool ToolbarInteracting()")[1].split("}")[0])
        self.assertIn("interactUntil", bar.split("bool ToolbarInteracting()")[1].split("}")[0])
        # Never Valve's dashboard overlay; no gaze cursor overlay.
        for src in (inc, bar):
            self.assertNotIn("gamepadui.main", src)
            self.assertNotIn("gaze.cursor", src)

    def test_cpp_defaults_match_python(self):
        import ft_toolbar
        bar = self.read("screens/desktop_toolbar.inc")
        body = bar.split("void ToolbarDefaultMods()")[1].split("\n}\n")[0]
        for side in ("left", "right"):
            line = [l for l in body.splitlines() if f"{side}Mods" in l][0]
            kinds = [k.lower() for k in __import__("re").findall(r"ToolbarModKind::(\w+)", line)]
            self.assertEqual(kinds, [m["type"] for m in ft_toolbar.DEFAULT_GROUPS[side]])
        for t in ("start", "tasks", "displays", "tray"):
            self.assertIn(f'!std::strcmp(type, "{t}")', bar)

    def test_session_starts_taskbar(self):
        src = self.read("session/frametop-session.sh")
        self.assertIn("exec -a ft-taskbar", src)
        self.assertIn('kill "$taskbar"', src)
        # Leftover cleanup matches argv0 only, never the session's own command line.
        self.assertIn("pkill -f '^ft-taskbar '", src)
        self.assertNotIn("/ft-taskbar.py' 2>/dev/null", src)
        self.assertLessEqual(len("ft-taskbar"), 15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
