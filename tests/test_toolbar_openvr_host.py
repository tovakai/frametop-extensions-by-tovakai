"""Source and packaging regression guards for independently hosted VR toolbar."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/"plugins"/"spatial-toolbar"
sys.path.insert(0,str(ROOT/"sdk"))
sys.path.insert(0,str(DIR))
from frametop_ext.manifest import load_manifest  # noqa: E402
import ft_toolbar  # noqa: E402


class HostContracts(unittest.TestCase):
    def test_external_manifest_and_dependency(self):
        obj=json.loads((DIR/"extension.json").read_text())
        self.assertEqual(obj["dependencies"],["tovakai.spatial-profiles"])
        self.assertEqual(load_manifest(DIR/"extension.json").entrypoint,"run.sh")
        self.assertEqual(obj["status"],"experimental")
        self.assertTrue((DIR/"run.sh").exists())
        self.assertTrue((DIR/"build.sh").exists())

    def test_legacy_arch_geometry_and_overlay_ownership(self):
        code=(DIR/"toolbar.cpp").read_text()
        self.assertIn('ARCH_DEG = 15',code)
        self.assertIn('TILT_BACK = 20',code)
        self.assertIn('constexpr int BW = 1000',code)
        self.assertIn('on_arch(const Arch&',code)
        self.assertIn('arch_texture(const Arch&',code)
        self.assertIn('GetDeviceToAbsoluteTrackingPose(',code)
        self.assertIn('tovakai.spatial-toolbar.backing',code)
        self.assertIn('tovakai.spatial-toolbar.displays',code)
        self.assertIn('tovakai.spatial-toolbar.popup',code)
        self.assertNotIn('frametop.toolbar.backing',code)
        self.assertNotIn('gamepadui.main',code)
        self.assertNotIn('DestroyOverlay(vr::',code)

    def test_known_invisible_hitbox_regression(self):
        code=(DIR/"toolbar.cpp").read_text()
        self.assertIn('VROverlayInputMethod_None',code)
        self.assertIn('SetOverlayMouseScale(s.handle,&scale)',code)
        self.assertIn('SetOverlayMouseScale(incoming.handle,&mouseScale)',code)
        self.assertIn('SetOverlayAlpha(display.handle',code)
        # Hover is an alpha-only change, never a texture re-upload.
        loop=code.split('void loop(){')[1].split('};\n} // namespace')[0]
        self.assertNotIn('SetOverlayRaw',loop)
        self.assertIn('IsDashboardVisible()',loop)
        self.assertIn('GetCurrentSceneProcessId()',loop)

    def test_category_navigation_keeps_old_popup_visible_during_swap(self):
        code=(DIR/"toolbar.cpp").read_text()
        self.assertIn("std::array<Surface,2> popups",code)
        self.assertIn('tovakai.spatial-toolbar.popup.swap',code)
        self.assertIn("const int stage=(activePopup<0)?0:1-activePopup;",code)
        self.assertIn("SetOverlayRaw(incoming.handle,pixels.data()",code)
        self.assertIn("SetOverlaySortOrder(incoming.handle,5)",code)
        self.assertIn("SetOverlaySortOrder(outgoing.handle,4)",code)
        self.assertIn("SetOverlayInputMethod(outgoing.handle,vr::VROverlayInputMethod_None)",code)
        self.assertIn("retirePopupAfter=std::chrono::steady_clock::now()+",code)
        self.assertIn("std::chrono::milliseconds(55)",code)
        self.assertIn("retire_popup_if_ready();",code)
        self.assertIn("for(auto &p:popups)show(p,false);",code)
        self.assertIn("if(!visible||!shown||index!=activePopup)continue;",code)
        # Uploads happen to the staging handle, never the visible active one.
        open_method=code.split('    void open(const std::string& kind,')[1].split('    void click(',1)[0]
        self.assertNotIn("SetOverlayRaw(popups[size_t(activePopup)]",open_method)
        self.assertIn("if(err!=vr::VROverlayError_None)",open_method)
        self.assertIn("current menu stays visible",open_method)
        self.assertIn("if(showErr!=vr::VROverlayError_None)",open_method)
        # Existing toolbar backplate remains passive and the retiring image
        # stops receiving mouse input before it is hidden.
        self.assertIn("mouse?vr::VROverlayInputMethod_Mouse:vr::VROverlayInputMethod_None",code)

    def test_orig_models_and_painter_are_used(self):
        provider=(DIR/"menu.py").read_text()
        self.assertIn('import ft_toolbar',provider)
        runtime=(DIR/"ui_runtime.py").read_text()
        self.assertIn('ft_toolbar.button_local_x(',runtime)
        self.assertIn('model.items_text(',provider)
        self.assertIn('toolbar_profiles.displays_popup()',provider)
        self.assertIn('toolbar_profiles.activate(item)',runtime)
        self.assertIn('model.start_layout(',runtime)
        self.assertIn('model.merge_tasks(',runtime)
        self.assertIn('PangoCairo.show_layout(',provider)
        self.assertIn('surf = cairo.ImageSurface(cairo.FORMAT_ARGB32',provider)
        self.assertIn('os.replace(',provider)
        # Background layout is calculated by the old Python model.
        names=[name for _,name,_ in ft_toolbar.button_local_x(
            ft_toolbar.DEFAULT_GROUPS)]
        self.assertIn('popup:profiles',names)

    def test_start_task_and_drag_are_real_overlay_controls(self):
        code=(DIR/"toolbar.cpp").read_text()
        for key in ("tovakai.spatial-toolbar.start",
                    "tovakai.spatial-toolbar.task.",
                    "tovakai.spatial-toolbar.grab"):
            self.assertIn(key,code)
        self.assertIn('open("start",startX)',code)
        self.assertIn('open("profiles",buttonX)',code)
        self.assertIn('drag_start(ev.trackedDeviceIndex)',code)
        self.assertIn('drag_end(ev.trackedDeviceIndex)',code)
        self.assertIn('drag_tick();',code)
        self.assertIn('std::filesystem::last_write_time(dir+"/tasks.json"',code)
        self.assertIn('SetOverlayInputMethod(s.handle,',code)
        self.assertIn('mouse?vr::VROverlayInputMethod_Mouse:vr::VROverlayInputMethod_None',code)
        self.assertIn("show(backdrop,visible);",code)
        self.assertIn('show(start,visible);show(display,visible);show(grab,visible);',code)
        provider=(DIR/"tasks.py").read_text()
        self.assertIn("workspace.windowList()",provider)
        self.assertIn("org.tovakai.SpatialToolbar",provider)
        self.assertIn('sock.bind(b"\\0tovakai_toolbar_tasks")',provider)

    def test_grab_matches_upstream_pill_and_thumbstick_depth_control(self):
        code=(DIR/"toolbar.cpp").read_text()
        # Frametop/frametop screens/vr.cpp BarTexture defaults and proportions:
        # 256x24, normal grey 235/210, active blue 90/170/255/240.
        self.assertIn("pill_texture(256,24,235,235,235,210)",code)
        self.assertIn("pill_texture(256,24,90,170,255,240)",code)
        self.assertIn("grab_texture(false),256,24,.30f,true,3",code)
        self.assertIn("const double gripHeight=gripWidth*(24.0/256.0)",code)
        self.assertIn("light_grab(hoverGrab||dragging)",code)
        self.assertIn("light_grab(true)",code)
        self.assertIn("light_grab(false)",code)
        # This flag is essential for SteamVR to deliver controller thumbstick
        # scrolling while the user is holding the toolbar grab trigger.
        self.assertIn("grab.handle,vr::VROverlayFlags_SendVRDiscreteScrollEvents,true",code)
        self.assertIn("ev.eventType==vr::VREvent_ScrollDiscrete&&dragging",code)
        self.assertIn("push_drag(ev.data.scroll.ydelta)",code)
        # Push along headset -> toolbar (not along controller local Z), and
        # update controller-relative drag transform so moving your hand after
        # scrolling remains seamless. These values match upstream Push().
        drag=code.split("    void push_drag(double notches){")[1].split(
            "    void drag_start(",1)[0]
        self.assertIn("const double length=std::sqrt(dx*dx+dy*dy+dz*dz)",drag)
        self.assertIn("length*(1.+.08*notches)",drag)
        self.assertIn("std::clamp(length*(1.+.08*notches),.3,10.)",drag)
        self.assertIn("dragRel=mul(inverse(controller),pose)",drag)
        self.assertIn("drag_tick();",drag)
        self.assertNotIn("dragRel.m[2][3]",drag)
        # Don't upload a fresh grab texture on every frame; that caused
        # disappearing-but-clickable icons in the original monolithic toolbar.
        light=code.split("    void light_grab(bool lit){")[1].split(
            "    void push_drag(",1)[0]
        self.assertIn("if(grabLit==lit)return;",light)

    def test_original_cairo_renderer_has_explicit_container_setup(self):
        dependencies=(DIR/"install-renderer-deps.sh").read_text()
        launcher=(DIR/"run.sh").read_text()
        self.assertIn("python3-gobject python3-cairo pango",dependencies)
        self.assertIn('"$core/scripts/in-box"',dependencies)
        self.assertIn("menu.py",launcher)
        self.assertIn(" render --kind profiles --dir ",launcher)
        self.assertIn(" render --kind start --dir ",launcher)
        self.assertIn(" render --kind toolbar --dir ",launcher)
        self.assertIn("install-renderer-deps.sh",launcher)
        # No implicit package installation, root access or compositor restart
        # is permitted during the normal renderer startup.
        self.assertNotIn("dnf install",launcher)
        self.assertNotIn("sudo",launcher)
        self.assertNotIn("systemctl",launcher)

    def test_startup_waits_for_valid_headset_tracking(self):
        code=(DIR/"toolbar.cpp").read_text()
        self.assertIn("std::chrono::seconds(15)",code)
        self.assertIn("hmd_pose(head,&tracking)",code)
        self.assertIn("IsTrackedDeviceConnected(",code)
        self.assertIn("vr::k_unTrackedDeviceIndex_Hmd)",code)
        self.assertIn("tracking_name(tracking.tracking)",code)
        self.assertIn("std::chrono::milliseconds(50)",code)
        self.assertIn('std::memcmp(message,"stop",4)==0',code)

    def test_cli_and_build_do_not_modify_core(self):
        build=(DIR/"build.sh").read_text()
        runner=(DIR/"run.sh").read_text()
        self.assertIn('screens/build/include/openvr.h',build)
        self.assertIn('v2.15.6',build)
        self.assertIn('toolbar.cpp',build)
        self.assertNotIn('ft-screens',build.split('g++ ')[-1])
        self.assertIn('flock -n',runner)
        self.assertIn('bash plugins/spatial-toolbar/build.sh',runner)
        self.assertNotIn('systemctl',runner)
        self.assertNotIn('sudo',runner)


if __name__=="__main__":
    unittest.main()
