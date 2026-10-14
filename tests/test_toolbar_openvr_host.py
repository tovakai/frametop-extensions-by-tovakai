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
        self.assertIn('SetOverlayMouseScale(popup.handle,&ms)',code)
        self.assertIn('SetOverlayAlpha(display.handle',code)
        # Hover is an alpha-only change, never a texture re-upload.
        loop=code.split('void loop(){')[1].split('};\n} // namespace')[0]
        self.assertNotIn('SetOverlayRaw',loop)
        self.assertIn('IsDashboardVisible()',loop)
        self.assertIn('GetCurrentSceneProcessId()',loop)

    def test_orig_models_and_painter_are_used(self):
        provider=(DIR/"menu.py").read_text()
        self.assertIn('import ft_toolbar',provider)
        self.assertIn('ft_toolbar.button_local_x(',provider)
        self.assertIn('model.items_text(',provider)
        self.assertIn('toolbar_profiles.displays_popup()',provider)
        self.assertIn('toolbar_profiles.activate(item)',provider)
        self.assertIn('PangoCairo.show_layout(',provider)
        self.assertIn('surf = cairo.ImageSurface(cairo.FORMAT_ARGB32',provider)
        self.assertIn('os.replace(',provider)
        # Background layout is calculated by the old Python model.
        names=[name for _,name,_ in ft_toolbar.button_local_x(
            ft_toolbar.DEFAULT_GROUPS)]
        self.assertIn('popup:profiles',names)

    def test_startup_waits_for_valid_headset_tracking(self):
        code=(DIR/"toolbar.cpp").read_text()
        self.assertIn("std::chrono::seconds(15)",code)
        self.assertIn("hmd_pose(head,&tracking)",code)
        self.assertIn("IsTrackedDeviceConnected(vr::k_unTrackedDeviceIndex_Hmd)",code)
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
