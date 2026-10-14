// Stage 2 DesktopToolbar â€” included inside vr.cpp's anonymous namespace.
// Frametop-owned OpenVR overlays; yields when SteamVR dashboard is visible.
//
// Visual grammar from installed SteamVR dashboard CSS (not screenshots):
//   .MainControlBar 1800Ã—180 #0e141b radius 30px
//   .ControlBarGroup pad 7px, #23262E, radius 9001 / .Large 21px
//   .ControlBarButton Small 85px; .Large buttons radius 16px; Active #88ccf1
//   Section gaps: --dashboard-control-bar-control-spacing (1rem)
//
// Composition is modular / asymmetric (not a row of equal circles). Default taskbar:
//   [ Start ] [ pinned + running apps ... ] [ Displays ] [ tray: volume, Wi-Fi ]
// Older modules (home, launcher, profiles 1-6, actions, user) stay available.

#include "steamvr_assets.h"

namespace ToolbarStyle {
// SteamVR bar 1800Ã—180 (10:1). OpenVR height = width * (texH/texW) â€” keep that ratio
// so the backing's visual height is stable, and every cell is sized â‰¤ that height.
constexpr double kBarH = 0.090;
constexpr double kBarAspect = 10.0;  // width / height (1800/180)
constexpr double kPx = kBarH / 180.0;
// Cells as fractions of bar height (CSS: Small 85px, NowPlaying 150px, pad 7px).
constexpr double kApp = kBarH * (150.0 / 180.0) * 0.90;  // App tile side; always < kBarH
constexpr double kBtn = kBarH * (85.0 / 180.0);
constexpr double kSeg = kBarH * (64.0 / 180.0);
constexpr double kGroupPad = kBarH * (7.0 / 180.0);
constexpr double kInnerGap = 0.4 * 16 * kPx;
constexpr double kModuleGap = 16 * kPx;
constexpr double kBarPad = 12 * kPx;
constexpr double kScreenGap = 0.05;
constexpr double kBtnDz = 0.030;  // cells in front of the curved backing (was 0.010: occluded)
constexpr double kArchDeg = 15;       // half the angle the bar's outline bends through
constexpr double kTiltBackDeg = 20;   // past facing the eye, top away from it
// Sit cells toward the inner edge of the band (visually "down"). The geometric
// centreline reads a little high once the arch is textured and tilted back.
constexpr double kCellBandNudge = 0.08;  // fraction of band thickness, inward
constexpr uint32_t kSortBack = 1, kSortCell = 3;

// Items have no containers of their own: idle cells are the bar's colour, a targeted
// cell lights to the button grey.
constexpr uint8_t kBarR = 0x0e, kBarG = 0x14, kBarB = 0x1b;
constexpr uint8_t kBtnR = 0x3d, kBtnG = 0x44, kBtnB = 0x50;
constexpr uint8_t kAccentR = 0x88, kAccentG = 0xcc, kAccentB = 0xf1;
constexpr float kIconIdle = 0.60f;

constexpr int kTexApp = 128;
constexpr int kTexBtn = 96;
constexpr int kTexSeg = 96;
constexpr int kTexBarW = 1000, kTexBarH = 100;  // exactly 10:1 â†’ height = width/10
constexpr int kUnderlinePx = 4;
}  // namespace ToolbarStyle

enum class ToolbarModKind { Home, Launcher, Profiles, Action, User, Start, Tasks, Displays, Tray };

struct ToolbarMod {
    ToolbarModKind kind = ToolbarModKind::Action;
    std::string arg;
};

enum class CellShape { AppTile, Segment, RoundFilled };

struct ToolbarBtn {
    vr::VROverlayHandle_t o = vr::k_ulOverlayHandleInvalid;
    std::string action;
    std::string label;
    bool hover = false;
    bool lit = false;
    bool active = false;  // cyan underline / Active outline
    int slot = -1;
    CellShape shape = CellShape::RoundFilled;
    double u = 0;  // arc position along the bar (set by PlaceToolbar; popups hang from it)
};

struct ToolbarModule {
    ToolbarModKind kind = ToolbarModKind::Action;
    std::vector<ToolbarBtn> buttons;
    double width = 0;
    bool large = false;  // ControlBarGroup.Large (profiles)
    int side = 0;        // 0 left (packed to the left end), 1 center, 2 right (to the right end)
};

// The toolbar is a spatial body like a screen or an instrument (spatial.inc): its
// FollowState pose is the *dock anchor* â€” kept upright (yaw only) so docked screens stand
// level above it â€” and only the bar's own visuals pitch toward the eye.
struct DesktopToolbar : FollowState, AttentionState, MoveDrag {
    DesktopToolbar() {
        idleOpacity = 1.f;
        attentionEnabled = true;
    }
    bool enabled = false;
    bool built = false;
    bool placed = false;  // has a pose (place / recenter / layout); else recentred when first shown
    double scale = 1.0;   // multiplies every ToolbarStyle length
    double metres = 0.70;
    double curve = 0;     // arc radius: the head's horizontal distance when last settled
    vr::VROverlayHandle_t backing = vr::k_ulOverlayHandleInvalid;
    int backingTexH = 0, backingBandPx = 0;  // last uploaded arch texture (re-drawn on change)
    vr::VROverlayHandle_t grab = vr::k_ulOverlayHandleInvalid;  // move bar under the toolbar
    bool hoverGrab = false;
    bool grabLit = false;
    float controls = 0;   // move bar fade, 0 (hidden) .. 1
    long nearUntil = 0;   // a laser was near the toolbar until this tick
    long interactUntil = 0;  // keep attention after a popup closes (launch from Start)
    bool anyHover = false;
    // Config sides (CLI); built into modules[] at Ensure.
    std::vector<ToolbarMod> leftMods, centerMods, rightMods;
    std::vector<ToolbarModule> modules;
    // Stable OpenVR handles for toolbar cells. Task-list changes repaint/reposition these
    // instead of destroy+recreate under the same key in one frame (which can leave a
    // transparent-but-clickable overlay on SteamVR).
    std::map<std::string, vr::VROverlayHandle_t> cellPool;
    bool visible = false;
    bool dashHidden = false;
    float lastAlpha = -1.f;
};

DesktopToolbar g_toolbar;

double TS(double metres) { return metres * g_toolbar.scale; }

std::vector<uint8_t> RoundRectTexture(int w, int h, double radius, uint8_t r, uint8_t g, uint8_t b, uint8_t a) {
    std::vector<uint8_t> px(size_t(w) * h * 4, 0);
    const double rad = std::min(radius, std::min(w, h) / 2.0 - 1.0);
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            const double cx = std::clamp(double(x) + 0.5, rad, w - rad);
            const double cy = std::clamp(double(y) + 0.5, rad, h - rad);
            const double d = std::hypot(x + 0.5 - cx, y + 0.5 - cy);
            const double cover = std::clamp(rad - d + 0.5, 0.0, 1.0);
            if (cover <= 0) continue;
            uint8_t *p = &px[(size_t(y) * w + x) * 4];
            p[0] = r;
            p[1] = g;
            p[2] = b;
            p[3] = uint8_t(cover * a);
        }
    return px;
}

void CompositeGlyph(std::vector<uint8_t> &px, int n, const std::vector<uint8_t> &glyph, int gw, int gh, float iconA,
                    double scale) {
    if (gw <= 0 || gh <= 0 || glyph.empty()) return;
    const int dw = int(n * scale), dh = int(n * scale);
    // Match PaintIcon: a hair below centre so glyphs don't sit on the arch roof.
    const int ox = (n - dw) / 2, oy = (n - dh) / 2 + 2;
    for (int y = 0; y < dh; ++y)
        for (int x = 0; x < dw; ++x) {
            const int sx = x * gw / dw, sy = y * gh / dh;
            const uint8_t *s = &glyph[(size_t(sy) * gw + sx) * 4];
            if (s[3] < 16) continue;
            // ControlTexture packs disc bg + glyph. Keep only bright glyph pixels â€”
            // whitening the dark disc made Home look like a down-arrow blob.
            const uint8_t lum = uint8_t(0.2126f * s[0] + 0.7152f * s[1] + 0.0722f * s[2]);
            if (lum < 140) continue;
            uint8_t *p = &px[(size_t(oy + y) * n + (ox + x)) * 4];
            const float a = (s[3] / 255.f) * iconA;
            p[0] = uint8_t(245 * a + p[0] * (1 - a));
            p[1] = uint8_t(245 * a + p[1] * (1 - a));
            p[2] = uint8_t(245 * a + p[2] * (1 - a));
            p[3] = uint8_t(std::min(255.f, p[3] + 255 * a));
        }
}

void PaintUnderline(std::vector<uint8_t> &px, int w, int h, bool on) {
    if (!on) return;
    const int y0 = h - ToolbarStyle::kUnderlinePx - 6;
    const int x0 = w / 6, x1 = w - w / 6;
    for (int y = y0; y < y0 + ToolbarStyle::kUnderlinePx; ++y)
        for (int x = x0; x < x1; ++x) {
            uint8_t *p = &px[(size_t(y) * w + x) * 4];
            p[0] = ToolbarStyle::kAccentR;
            p[1] = ToolbarStyle::kAccentG;
            p[2] = ToolbarStyle::kAccentB;
            p[3] = 255;
        }
}

// Cell background: the bar's colour (invisible on it) unless targeted.
std::vector<uint8_t> CellFill(int n, double radius, bool lit) {
    return lit ? RoundRectTexture(n, n, radius, ToolbarStyle::kBtnR, ToolbarStyle::kBtnG, ToolbarStyle::kBtnB, 255)
               : RoundRectTexture(n, n, radius, ToolbarStyle::kBarR, ToolbarStyle::kBarG, ToolbarStyle::kBarB, 255);
}

std::vector<uint8_t> AppTileTexture(bool active, bool hover, const std::vector<uint8_t> &glyph, int gw, int gh) {
    const int n = ToolbarStyle::kTexApp;
    // Large / App tile: radius ~16/85 of face.
    auto px = CellFill(n, n * 0.17, hover);
    CompositeGlyph(px, n, glyph, gw, gh, active || hover ? 1.f : ToolbarStyle::kIconIdle, 0.52);
    PaintUnderline(px, n, n, active);
    if (hover && !active) {
        // 2px Active-style outline hint (#88ccf1) â€” inset ring.
        for (int y = 0; y < n; ++y)
            for (int x = 0; x < n; ++x) {
                const int m = std::min(std::min(x, y), std::min(n - 1 - x, n - 1 - y));
                if (m > 2 || m < 1) continue;
                uint8_t *p = &px[(size_t(y) * n + x) * 4];
                if (p[3] < 20) continue;
                p[0] = ToolbarStyle::kAccentR;
                p[1] = ToolbarStyle::kAccentG;
                p[2] = ToolbarStyle::kAccentB;
                p[3] = 220;
            }
    }
    return px;
}

std::vector<uint8_t> RoundFilledTexture(bool hover, const std::vector<uint8_t> &glyph, int gw, int gh) {
    const int n = ToolbarStyle::kTexBtn;
    auto px = CellFill(n, n / 2.0 - 2, hover);
    CompositeGlyph(px, n, glyph, gw, gh, hover ? 1.f : ToolbarStyle::kIconIdle, 0.50);
    return px;
}

std::vector<uint8_t> SegmentTexture(int digit, bool hover, bool active) {
    const int n = ToolbarStyle::kTexSeg;
    // Rectangular cell (Large group button radius ~16/85), not a free-floating disc.
    auto px = CellFill(n, n * 0.17, hover || active);
    auto dig = DigitTexture(n, digit, hover || active);
    CompositeGlyph(px, n, dig, n, n, 1.f, 0.78);
    PaintUnderline(px, n, n, active);
    return px;
}

// Filled glyphs only (no disc chrome). vâ†‘ in ControlTexture space.
std::vector<uint8_t> GlyphHome() {
    return ControlTexture(
        ToolbarStyle::kTexBtn, InDisc,
        [](double u, double v) {
            // Roof triangle (peak up) + body + door cutout.
            const bool roof = v > 0.05 && v < 0.55 && std::fabs(u) < 0.55 - (v - 0.05);
            const bool body = v > -0.45 && v <= 0.08 && std::fabs(u) < 0.38;
            const bool door = v > -0.45 && v < -0.05 && std::fabs(u) < 0.10;
            return (roof || body) && !door;
        },
        [](double, double) { return false; });
}

std::vector<uint8_t> GlyphPlus() {
    return ControlTexture(
        ToolbarStyle::kTexBtn, InDisc,
        [](double u, double v) {
            return (std::fabs(u) < 0.11 && std::fabs(v) < 0.40) || (std::fabs(v) < 0.11 && std::fabs(u) < 0.40);
        },
        [](double, double) { return false; });
}

std::vector<uint8_t> GlyphUser() {
    return ControlTexture(
        ToolbarStyle::kTexBtn, InDisc,
        [](double u, double v) {
            // Head + shoulders (classic avatar).
            if (std::hypot(u, v - 0.22) < 0.20) return true;
            if (v < 0.0 && v > -0.48) {
                const double half = 0.42 + v * 0.15;
                return std::fabs(u) < half && std::fabs(u) > 0.02;
            }
            return false;
        },
        [](double, double) { return false; });
}

std::vector<uint8_t> GlyphReset() {
    return ControlTexture(
        ToolbarStyle::kTexBtn, InDisc,
        [](double u, double v) {
            const double r = std::hypot(u, v);
            double ang = std::atan2(v, u) * 180 / M_PI;
            if (ang < 0) ang += 360;
            // Open ring + arrow head.
            if (std::fabs(r - 0.40) < 0.11 && !(ang > 300 || ang < 40)) return true;
            // Arrow tip near the gap (upper-right).
            return u > 0.15 && u < 0.55 && v > 0.05 && v < 0.45 && (u - 0.15) + (v - 0.05) < 0.55 &&
                   (u - 0.15) > (v - 0.05) * 0.3;
        },
        [](double, double) { return false; });
}

std::vector<uint8_t> GlyphHide() {
    return ControlTexture(
        ToolbarStyle::kTexBtn, InDisc,
        [](double u, double v) {
            // Eye outline (lens) + pupil.
            const double eye = std::hypot(u, v * 1.85);
            if (std::fabs(eye - 0.42) < 0.10 && std::fabs(u) < 0.55) return true;
            return std::hypot(u, v) < 0.14;
        },
        [](double, double) { return false; });
}

std::vector<uint8_t> GlyphGear() {
    return ControlTexture(
        ToolbarStyle::kTexBtn, InDisc,
        [](double u, double v) {
            const double r = std::hypot(u, v);
            if (r < 0.16) return true;
            if (r > 0.52 || r < 0.30) return false;
            double ang = std::atan2(v, u) * 180 / M_PI;
            if (ang < 0) ang += 360;
            const int tooth = int(ang / 45.0);
            const double local = ang - tooth * 45;
            return local < 16 || local > 40;
        },
        [](double, double) { return false; });
}

// Unscaled module width (callers scale with TS()).
bool SingleTileModule(ToolbarModKind k) {
    return k == ToolbarModKind::Home || k == ToolbarModKind::Launcher || k == ToolbarModKind::User ||
           k == ToolbarModKind::Start;
}

double ModuleWidthFor(const ToolbarModule &m) {
    if (SingleTileModule(m.kind)) return ToolbarStyle::kApp;
    if (m.kind == ToolbarModKind::Tasks) {
        const int n = std::max(1, (int)m.buttons.size());
        return ToolbarStyle::kGroupPad * 2 + n * ToolbarStyle::kApp + (n - 1) * ToolbarStyle::kInnerGap;
    }
    if (m.kind == ToolbarModKind::Profiles) {
        const int n = kSlotCount;
        return ToolbarStyle::kGroupPad * 2 + n * ToolbarStyle::kSeg + std::max(0, n - 1) * ToolbarStyle::kInnerGap;
    }
    const int n = std::max(1, (int)m.buttons.size());
    return ToolbarStyle::kGroupPad * 2 + n * ToolbarStyle::kBtn + std::max(0, n - 1) * ToolbarStyle::kInnerGap;
}

// Seen straight on, the bar is an arch: a band of constant thickness bent through
// ±kArchDeg about a centre below it, its ends cut radially. Lengths along the bar (module
// layout, ToolbarBtn::u) are arc lengths on the band's centreline; the centre of the
// centreline is the bar's local origin.
struct ToolbarArch {
    double r = 1, h = 0.09, theta = 0.26;  // centreline radius, band thickness, half-angle
    double width = 1, top = 0, bottom = 0;  // the backing overlay's extent (incl. margin)
};

ToolbarArch Arch() {
    ToolbarArch a;
    a.h = TS(ToolbarStyle::kBarH);
    a.theta = ToolbarStyle::kArchDeg * M_PI / 180;
    a.r = std::max(g_toolbar.metres / 2, a.h) / a.theta;
    const double margin = a.h * 0.04;
    a.width = 2 * (a.r + a.h / 2) * std::sin(a.theta) + 2 * margin;
    a.top = a.h / 2 + margin;
    a.bottom = (a.r - a.h / 2) * std::cos(a.theta) - a.r - margin;
    return a;
}

// Where arc length u lands in the bar's plane, and the band's slope there (radians).
void ArchPoint(const ToolbarArch &a, double u, double *x, double *y, double *phi) {
    *phi = u / a.r;
    *x = a.r * std::sin(*phi);
    *y = a.r * std::cos(*phi) - a.r;
}

std::vector<uint8_t> ArchTexture(const ToolbarArch &a, int texW, int texH) {
    std::vector<uint8_t> px(size_t(texW) * texH * 4, 0);
    const double mpp = a.width / texW;              // metres per pixel
    const double rc = a.h * (30.0 / 180.0);         // MainControlBar corner radius
    for (int py = 0; py < texH; ++py)
        for (int pxl = 0; pxl < texW; ++pxl) {
            const double X = (pxl + 0.5) * mpp - a.width / 2;
            const double Y = a.top - (py + 0.5) * (a.top - a.bottom) / texH + a.r;  // from the arch centre
            const double rho = std::hypot(X, Y);
            const double side = a.h / 2 - std::fabs(rho - a.r);                  // to the long edges
            const double end = rho * std::sin(a.theta - std::fabs(std::atan2(X, Y)));  // to the cut ends
            double dist = std::min(side, end);
            if (side < rc && end < rc) dist = rc - std::hypot(rc - side, rc - end);
            const double cover = std::clamp(dist / mpp + 0.5, 0.0, 1.0);
            if (cover <= 0) continue;
            uint8_t *p = &px[(size_t(py) * texW + pxl) * 4];
            p[0] = ToolbarStyle::kBarR;
            p[1] = ToolbarStyle::kBarG;
            p[2] = ToolbarStyle::kBarB;
            p[3] = uint8_t(cover * 255);
        }
    return px;
}

// Draws the backing for the current width when the arch's pixel shape changed.
void UploadToolbarBacking(const ToolbarArch &a) {
    if (g_toolbar.backing == vr::k_ulOverlayHandleInvalid) return;
    const int texW = ToolbarStyle::kTexBarW;
    const int texH = std::max(8, int(std::lround(texW * (a.top - a.bottom) / a.width)));
    const int band = int(std::lround(texW * a.h / a.width));
    if (texH == g_toolbar.backingTexH && band == g_toolbar.backingBandPx) return;
    g_toolbar.backingTexH = texH;
    g_toolbar.backingBandPx = band;
    const auto tex = ArchTexture(a, texW, texH);
    vr::VROverlay()->SetOverlayRaw(g_toolbar.backing, (void *)tex.data(), uint32_t(texW), uint32_t(texH), 4);
    const vr::HmdVector2_t scale = {{float(texW), float(texH)}};
    vr::VROverlay()->SetOverlayMouseScale(g_toolbar.backing, &scale);
}

// The bar's horizontal arc (seen from above): a cylinder about the head, g_toolbar.curve.
Mat ToolbarOnArc(double u, double dz) {
    const double r = g_toolbar.curve;
    if (r <= 0.25) return Translation(u, 0, dz);
    const double a = u / r, c = std::cos(a), sn = std::sin(a);
    Mat m = Identity();
    m.m[0][0] = float(c), m.m[0][2] = float(-sn);
    m.m[2][0] = float(sn), m.m[2][2] = float(c);
    m.m[0][3] = float(r * sn - dz * sn);
    m.m[1][3] = 0.f;
    m.m[2][3] = float(r - r * c + dz * c);
    return m;
}

float ToolbarCurvature(double width) {
    const double r = g_toolbar.curve;
    if (r <= 0.25 || width <= 0) return 0.f;
    return float(std::clamp(width / (2 * M_PI * r), 0.0, 1.0));
}

// A point on the arch at arc length u, dz in front of the bar, rolled with the band.
Mat ToolbarOnArch(const ToolbarArch &a, double u, double dz, bool roll = true) {
    double x, y, phi;
    ArchPoint(a, u, &x, &y, &phi);
    // Inward along the radius = toward the bottom of the bar at the middle.
    const double nudge = a.h * ToolbarStyle::kCellBandNudge;
    x -= nudge * std::sin(phi);
    y -= nudge * std::cos(phi);
    Mat m = Mul(ToolbarOnArc(x, dz), Translation(0, y, 0));
    if (!roll) return m;
    Mat rz = Identity();
    const float c = float(std::cos(phi)), sn = float(std::sin(phi));
    rz.m[0][0] = c, rz.m[0][1] = sn;
    rz.m[1][0] = -sn, rz.m[1][1] = c;
    return Mul(m, rz);
}

void KillOverlay(vr::VROverlayHandle_t &o) {
    if (o == vr::k_ulOverlayHandleInvalid) return;
    vr::VROverlay()->DestroyOverlay(o);
    o = vr::k_ulOverlayHandleInvalid;
}

vr::VROverlayHandle_t ToolbarCellOverlay(const char *key, const char *name,
                                                  const std::vector<uint8_t> &px, int w, int h) {
    auto it = g_toolbar.cellPool.find(key);
    if (it == g_toolbar.cellPool.end()) {
        const auto o = MakeChrome(key, name, px, w, h);
        if (o != vr::k_ulOverlayHandleInvalid) g_toolbar.cellPool.emplace(key, o);
        return o;
    }

    auto &o = it->second;
    if (o == vr::k_ulOverlayHandleInvalid) {
        o = MakeChrome(key, name, px, w, h);
        return o;
    }

    vr::VROverlay()->SetOverlayName(o, name);
    const auto err =
        vr::VROverlay()->SetOverlayRaw(o, const_cast<uint8_t *>(px.data()), uint32_t(w), uint32_t(h), 4);
    if (err != vr::VROverlayError_None) {
        // SetOverlayRaw can transiently return RequestFailed after repeated uploads. Keep
        // the last good texture and handle: destroying it here turns one refused refresh
        // into a visible, clickable overlay with no texture at all.
        std::fprintf(stderr, "toolbar: SetOverlayRaw refused for %s (keeping old texture): %s\n", key,
                     vr::VROverlay()->GetOverlayErrorNameFromEnum(err));
    }
    vr::VROverlay()->SetOverlayInputMethod(o, vr::VROverlayInputMethod_Mouse);
    const vr::HmdVector2_t scale = {{float(w), float(h)}};
    vr::VROverlay()->SetOverlayMouseScale(o, &scale);
    return o;
}

// Drop the module model only. Cell overlays are pooled and merely hidden so a task-list
// rebuild can repaint/reposition the same OpenVR handles without destroy/recreate races.
void DestroyToolbarCells() {
    for (auto &[key, o] : g_toolbar.cellPool)
        if (o != vr::k_ulOverlayHandleInvalid) vr::VROverlay()->HideOverlay(o);
    g_toolbar.modules.clear();
    g_toolbar.built = false;
    g_toolbar.anyHover = false;
    g_toolbar.lastAlpha = -1.f;
}

void DestroyToolbarOverlays() {
    DestroyToolbarCells();
    for (auto &[key, o] : g_toolbar.cellPool) KillOverlay(o);
    g_toolbar.cellPool.clear();
    KillOverlay(g_toolbar.backing);
    KillOverlay(g_toolbar.grab);
    g_toolbar.backingTexH = g_toolbar.backingBandPx = 0;
    g_toolbar.grabLit = false;
    g_toolbar.controls = 0;
    g_toolbar.visible = false;
}

void ToolbarDefaultMods() {
    g_toolbar.leftMods = {{ToolbarModKind::Start, ""}, {ToolbarModKind::Tasks, ""}};
    g_toolbar.centerMods.clear();
    g_toolbar.rightMods = {{ToolbarModKind::Displays, ""}, {ToolbarModKind::Tray, ""}};
}

#include "toolbar_taskbar.inc"

std::vector<uint8_t> FaceFor(const ToolbarBtn &b, bool lit) {
    if (b.shape == CellShape::Segment && b.slot >= 1) return SegmentTexture(b.slot, lit, b.active || lit);
    if (auto face = TaskbarFace(b.action, lit, b.shape == CellShape::AppTile); !face.empty()) return face;
    std::vector<uint8_t> glyph;
    if (b.action == "desktop.home")
        glyph = GlyphHome();
    else if (b.action.rfind("launcher:", 0) == 0)
        glyph = GlyphPlus();
    else if (b.action == "desktop.user")
        glyph = GlyphUser();
    else if (b.action == "screens.toggle")
        glyph = GlyphHide();
    else if (b.action.find("reset") != std::string::npos)
        glyph = GlyphReset();
    else
        glyph = GlyphGear();
    if (b.shape == CellShape::AppTile)
        return AppTileTexture(b.active || lit, lit, glyph, ToolbarStyle::kTexBtn, ToolbarStyle::kTexBtn);
    return RoundFilledTexture(lit, glyph, ToolbarStyle::kTexBtn, ToolbarStyle::kTexBtn);
}

const std::vector<uint8_t> &ToolbarGrabTexture(bool lit);

void EnsureToolbar() {
    if (!g_vr || !g_toolbar.enabled) return;
    if (g_toolbar.built) return;
    if (g_toolbar.leftMods.empty() && g_toolbar.centerMods.empty() && g_toolbar.rightMods.empty())
        ToolbarDefaultMods();

    // Paint the arch immediately — never leave a fully transparent backing that a failed
    // or skipped re-upload would stick with. PlaceToolbar may redraw when the width changes.
    if (g_toolbar.backing == vr::k_ulOverlayHandleInvalid) {
        if (g_toolbar.metres < 0.1) g_toolbar.metres = TS(ToolbarStyle::kBarH * ToolbarStyle::kBarAspect);
        const ToolbarArch arch = Arch();
        const int texW = ToolbarStyle::kTexBarW;
        const int texH = std::max(8, int(std::lround(texW * (arch.top - arch.bottom) / arch.width)));
        const auto backingPx = ArchTexture(arch, texW, texH);
        g_toolbar.backing =
            MakeChrome("frametop.toolbar.backing", "Desktop toolbar", backingPx, texW, texH);
        g_toolbar.backingTexH = texH;
        g_toolbar.backingBandPx = int(std::lround(texW * arch.h / arch.width));
    }
    // Move bar: the screens' Stage 1 grab pill (same paint, idle/hover/active rules), at the
    // size LightToolbarGrab re-uploads so its hit area never changes.
    if (g_toolbar.grab == vr::k_ulOverlayHandleInvalid) {
        g_toolbar.grab = MakeChrome("frametop.toolbar.grab", "Desktop toolbar: move", ToolbarGrabTexture(false),
                                    ChromeStyle::kBarTexW, ChromeStyle::kBarTexH * 2);
        vr::VROverlay()->SetOverlayFlag(g_toolbar.grab, vr::VROverlayFlags_SendVRDiscreteScrollEvents, true);
        g_toolbar.grabLit = false;
    }

    int side = 0;
    auto addModule = [&](ToolbarModKind kind, const std::vector<ToolbarMod> &sources) {
        ToolbarModule mod;
        mod.kind = kind;
        mod.side = side;
        mod.large = (kind == ToolbarModKind::Profiles);
        char key[80], name[80];

        auto makeCell = [&](ToolbarBtn b, int texW, int texH) {
            auto face = FaceFor(b, false);
            // Never upload an empty / short buffer (OpenVR would read garbage → blank cell).
            if (face.size() < size_t(texW) * texH * 4) {
                auto gear = GlyphGear();
                face = b.shape == CellShape::AppTile
                           ? AppTileTexture(false, false, gear, ToolbarStyle::kTexBtn, ToolbarStyle::kTexBtn)
                           : RoundFilledTexture(false, gear, ToolbarStyle::kTexBtn, ToolbarStyle::kTexBtn);
            }
            std::snprintf(key, sizeof key, "frametop.toolbar.m%zu.c%zu", g_toolbar.modules.size(), mod.buttons.size());
            std::snprintf(name, sizeof name, "Toolbar %s", b.label.c_str());
            b.o = ToolbarCellOverlay(key, name, face, texW, texH);
            mod.buttons.push_back(std::move(b));
        };

        if (kind == ToolbarModKind::Home) {
            ToolbarBtn b;
            b.action = "desktop.home";
            b.label = "home";
            b.shape = CellShape::AppTile;
            b.active = true;  // shell "home" accent like Steam selected app
            makeCell(std::move(b), ToolbarStyle::kTexApp, ToolbarStyle::kTexApp);
        } else if (kind == ToolbarModKind::Launcher) {
            ToolbarBtn b;
            std::string id = "launcher";
            for (const auto &s : sources)
                if (s.kind == ToolbarModKind::Launcher && !s.arg.empty()) id = s.arg;
            b.action = "launcher:" + id;
            b.label = "add";
            b.shape = CellShape::AppTile;
            makeCell(std::move(b), ToolbarStyle::kTexApp, ToolbarStyle::kTexApp);
        } else if (kind == ToolbarModKind::User) {
            ToolbarBtn b;
            b.action = "desktop.user";
            b.label = "user";
            b.shape = CellShape::AppTile;
            makeCell(std::move(b), ToolbarStyle::kTexApp, ToolbarStyle::kTexApp);
        } else if (kind == ToolbarModKind::Profiles) {
            for (int s = 1; s <= kSlotCount; ++s) {
                ToolbarBtn b;
                char act[32];
                std::snprintf(act, sizeof act, "profile.slot.%d", s);
                b.action = act;
                b.label = act;
                b.slot = s;
                b.shape = CellShape::Segment;
                makeCell(std::move(b), ToolbarStyle::kTexSeg, ToolbarStyle::kTexSeg);
            }
        } else if (kind == ToolbarModKind::Action) {
            // One utilities group from consecutive Action mods in sources.
            std::vector<std::string> acts;
            for (const auto &s : sources)
                if (s.kind == ToolbarModKind::Action && !s.arg.empty()) acts.push_back(s.arg);
            if (acts.empty()) return;
            for (const auto &act : acts) {
                ToolbarBtn b;
                b.action = act;
                b.label = act;
                b.shape = CellShape::RoundFilled;
                makeCell(std::move(b), ToolbarStyle::kTexBtn, ToolbarStyle::kTexBtn);
            }
        } else if (kind == ToolbarModKind::Start) {
            ToolbarBtn b;
            b.action = "popup:start";
            b.label = "start";
            b.shape = CellShape::AppTile;
            makeCell(std::move(b), ToolbarStyle::kTexApp, ToolbarStyle::kTexApp);
        } else if (kind == ToolbarModKind::Tasks) {
            if (g_taskbar.tasks.empty()) return;
            for (const auto &t : g_taskbar.tasks) {
                ToolbarBtn b;
                b.action = "task:" + t.id;
                b.label = t.name;
                b.shape = CellShape::AppTile;
                makeCell(std::move(b), ToolbarStyle::kTexApp, ToolbarStyle::kTexApp);
            }
        } else if (kind == ToolbarModKind::Displays || kind == ToolbarModKind::Tray) {
            const std::vector<std::string> acts =
                kind == ToolbarModKind::Displays ? std::vector<std::string>{"popup:profiles"}
                                                 : std::vector<std::string>{"popup:volume", "popup:wifi"};
            for (const auto &act : acts) {
                ToolbarBtn b;
                b.action = act;
                b.label = act.substr(6);
                b.shape = CellShape::RoundFilled;
                makeCell(std::move(b), ToolbarStyle::kTexBtn, ToolbarStyle::kTexBtn);
            }
        }

        mod.width = ModuleWidthFor(mod);
        if (!mod.buttons.empty()) g_toolbar.modules.push_back(std::move(mod));
    };

    // Build asymmetric module strip from side lists.
    for (const auto &m : g_toolbar.leftMods) addModule(m.kind, {m});
    side = 1;
    for (const auto &m : g_toolbar.centerMods) addModule(m.kind, {m});
    side = 2;
    // Coalesce consecutive right Actions into one utilities module.
    {
        std::vector<ToolbarMod> acts;
        auto flush = [&]() {
            if (!acts.empty()) {
                addModule(ToolbarModKind::Action, acts);
                acts.clear();
            }
        };
        for (const auto &m : g_toolbar.rightMods) {
            if (m.kind == ToolbarModKind::Action) {
                acts.push_back(m);
                continue;
            }
            flush();
            addModule(m.kind, {m});
        }
        flush();
    }

    g_toolbar.built = true;
}

// ---------------------------------------------------------------- placement

constexpr double kToolbarAhead = 0.75;  // default: this far ahead of the eyes (horizontal)
constexpr double kToolbarBelow = 0.40;  // ...and this far below them, like SteamVR's dashbar
constexpr double kGrabW = 0.24;         // move bar width at scale 1
constexpr double kGrabGap = 0.012;      // between the bar's bottom edge and the move bar

// The dock anchor: the toolbar's follow pose, levelled (yaw + position only).
bool ToolbarAnchor(Mat *out) {
    Mat p;
    if (!FollowPose(g_toolbar, &p)) return false;
    *out = YawOnlyHead(p);
    return true;
}

Mat DefaultToolbarPose() {
    Mat head;
    if (!DevicePose(vr::k_unTrackedDeviceIndex_Hmd, &head)) head = Identity();
    const double heading = std::atan2(head.m[0][2], head.m[2][2]) * 180 / M_PI;
    const double dx = -std::sin(heading * M_PI / 180), dz = -std::cos(heading * M_PI / 180);
    return PanelPose(head.m[0][3] + dx * kToolbarAhead, head.m[1][3] - kToolbarBelow,
                     head.m[2][3] + dz * kToolbarAhead, heading, 0, 0);
}

// Arc radius = the head's horizontal distance (a cylinder about you). Refreshed when the
// toolbar settles (placed, recentred, carried), not every frame: docked screens ride it.
void SettleToolbarCurve() {
    Mat a, hmd;
    if (!ToolbarAnchor(&a) || !DevicePose(vr::k_unTrackedDeviceIndex_Hmd, &hmd)) {
        if (g_toolbar.curve < 0.25) g_toolbar.curve = 1.0;
        return;
    }
    g_toolbar.curve = std::clamp(double(std::hypot(hmd.m[0][3] - a.m[0][3], hmd.m[2][3] - a.m[2][3])), 0.45, 4.0);
}

// The bar's own visuals pitch to face the eye (the "bottom of a sphere" look); the dock
// anchor itself stays level.
Mat ToolbarVisualPose(const Mat &anchor) {
    Mat hmd;
    double pitch = 0;
    if (DevicePose(vr::k_unTrackedDeviceIndex_Hmd, &hmd)) {
        const double dy = hmd.m[1][3] - anchor.m[1][3];
        const double horiz =
            std::max(0.1, double(std::hypot(hmd.m[0][3] - anchor.m[0][3], hmd.m[2][3] - anchor.m[2][3])));
        pitch = std::clamp(-std::atan2(dy, horiz) * 180 / M_PI - ToolbarStyle::kTiltBackDeg, -70.0, 45.0);
    }
    return Mul(anchor, PanelPose(0, 0, 0, 0, pitch, 0));
}

void PlaceDockedScreens(const Mat &anchor);  // toolbar_dock.inc
void TickUndockTweens();                     // toolbar_dock.inc

// Twice the screens' bar texture height with the same pill: a generous hit target.
const std::vector<uint8_t> &ToolbarGrabTexture(bool lit) {
    static const auto normal =
        PillTexture(ChromeStyle::kBarTexW, ChromeStyle::kBarTexH * 2, ChromeStyle::kIdleR, ChromeStyle::kIdleG,
                    ChromeStyle::kIdleB, ChromeStyle::kBarIdleA, ChromeStyle::kBarVisualHFrac / 2);
    static const auto glow =
        PillTexture(ChromeStyle::kBarTexW, ChromeStyle::kBarTexH * 2, ChromeStyle::kActiveR, ChromeStyle::kActiveG,
                    ChromeStyle::kActiveB, ChromeStyle::kBarLitA, ChromeStyle::kBarVisualHFrac / 2);
    return lit ? glow : normal;
}
double GrabHeight() { return TS(kGrabW) * 2.0 * ChromeStyle::kBarTexH / ChromeStyle::kBarTexW; }
double GrabY() { return -(TS(ToolbarStyle::kBarH) / 2 + TS(kGrabGap) + GrabHeight() / 2); }

void PlaceToolbar() {
    if (!g_toolbar.enabled || !g_toolbar.built) return;
    Mat anchor;
    if (!ToolbarAnchor(&anchor)) return;
    if (g_toolbar.curve < 0.25) SettleToolbarCurve();
    const Mat p = ToolbarVisualPose(anchor);

    // Each side is a run of modules: left packed to the left end, right to the right end,
    // center in the middle (between them when the bar is only as wide as its content).
    const double gap = TS(ToolbarStyle::kModuleGap), pad = TS(ToolbarStyle::kBarPad);
    double run[3] = {0, 0, 0};
    int count[3] = {0, 0, 0};
    for (auto &mod : g_toolbar.modules) {
        mod.width = TS(ModuleWidthFor(mod));
        const int sd = std::clamp(mod.side, 0, 2);
        run[sd] += (count[sd]++ ? gap : 0) + mod.width;
    }
    double content = pad * 2;
    int sides = 0;
    for (int sd = 0; sd < 3; ++sd)
        if (count[sd]) content += (sides++ ? gap : 0) + run[sd];
    // Never shorter than SteamVR's 10:1 bar.
    g_toolbar.metres = std::max(content, TS(ToolbarStyle::kBarH * ToolbarStyle::kBarAspect));
    const double half = g_toolbar.metres / 2;
    double runX[3] = {-half + pad, -run[1] / 2, half - pad - run[2]};
    if (count[1]) {
        const double lo = count[0] ? runX[0] + run[0] + gap : -half + pad;
        const double hi = (count[2] ? runX[2] - gap : half - pad) - run[1];
        runX[1] = std::clamp(runX[1], lo, std::max(lo, hi));
    }
    const ToolbarArch arch = Arch();

    if (g_toolbar.backing != vr::k_ulOverlayHandleInvalid) {
        UploadToolbarBacking(arch);
        const Mat bp = Mul(p, Translation(0, (arch.top + arch.bottom) / 2, 0));
        vr::VROverlay()->SetOverlayWidthInMeters(g_toolbar.backing, float(arch.width));
        // Curvature must match the metres-arc the cells ride (not the slightly wider
        // texture bounds), or the bent backing swallows the cells.
        vr::VROverlay()->SetOverlayCurvature(g_toolbar.backing, ToolbarCurvature(g_toolbar.metres));
        vr::VROverlay()->SetOverlayTransformAbsolute(g_toolbar.backing, vr::TrackingUniverseStanding, &bp);
        ApplyOverlaySort(g_toolbar.backing, ToolbarStyle::kSortBack, false);
    }

    const bool dash = g_toolbar.dashHidden;
    for (auto &mod : g_toolbar.modules) {
        const double w = mod.width;
        double &x = runX[std::clamp(mod.side, 0, 2)];
        const double cx = x + w / 2;
        auto put = [&](ToolbarBtn &b, double bx, double bw) {
            b.u = bx;
            if (b.o == vr::k_ulOverlayHandleInvalid) return;
            vr::VROverlay()->SetOverlayWidthInMeters(b.o, float(bw));
            // Roll with the arch so tiles follow the bar's outline (upright cells looked
            // glued-on and wrong). kBtnDz + matching curvature keep them in front of the mesh.
            Mat bp = Mul(p, ToolbarOnArch(arch, bx, TS(ToolbarStyle::kBtnDz), /*roll=*/true));
            vr::VROverlay()->SetOverlayTransformAbsolute(b.o, vr::TrackingUniverseStanding, &bp);
            ApplyOverlaySort(b.o, ToolbarStyle::kSortCell, dash);
        };
        if (SingleTileModule(mod.kind)) {
            // Square tex: width==height==kApp < kBarH.
            if (!mod.buttons.empty()) put(mod.buttons[0], cx, TS(ToolbarStyle::kApp));
        } else {
            const double cell = mod.kind == ToolbarModKind::Profiles ? ToolbarStyle::kSeg
                                : mod.kind == ToolbarModKind::Tasks  ? ToolbarStyle::kApp
                                                                     : ToolbarStyle::kBtn;
            double bx = x + TS(ToolbarStyle::kGroupPad) + TS(cell) / 2;
            for (auto &b : mod.buttons) {
                put(b, bx, TS(cell));
                bx += TS(cell) + TS(ToolbarStyle::kInnerGap);
            }
        }
        x += w + gap;
    }
    if (g_toolbar.backing != vr::k_ulOverlayHandleInvalid)
        ApplyOverlaySort(g_toolbar.backing, ToolbarStyle::kSortBack, dash);

    if (g_toolbar.grab != vr::k_ulOverlayHandleInvalid) {
        vr::VROverlay()->SetOverlayWidthInMeters(g_toolbar.grab, float(TS(kGrabW)));
        Mat gp = Mul(p, Translation(0, GrabY(), TS(ToolbarStyle::kBtnDz)));
        vr::VROverlay()->SetOverlayTransformAbsolute(g_toolbar.grab, vr::TrackingUniverseStanding, &gp);
        ApplyOverlaySort(g_toolbar.grab, ToolbarStyle::kSortCell, dash);
    }
    PlaceDockedScreens(anchor);
    TickUndockTweens();
    if (TaskbarPopupOpen()) {
        double u = std::nan("");
        for (const auto &mod : g_toolbar.modules)
            for (const auto &b : mod.buttons)
                if (b.action == g_taskbar.anchor) u = b.u;
        PlaceTaskbarPopup(p, u);
    }
}

// Alpha of every toolbar overlay: the body's attention opacity; the move bar also fades
// with laser proximity and dims unless targeted (the screens' chrome rules).
void ApplyToolbarAlpha(bool force = false) {
    const float a = g_toolbar.attentionResolved;
    const bool grabActive = g_toolbar.hoverGrab || g_toolbar.drag != Drag::None;
    const float key = a * 1000.f + g_toolbar.controls * 10.f + (grabActive ? 1.f : 0.f);
    if (!force && key == g_toolbar.lastAlpha) return;
    g_toolbar.lastAlpha = key;
    auto set = [](vr::VROverlayHandle_t o, float v) {
        if (o != vr::k_ulOverlayHandleInvalid) vr::VROverlay()->SetOverlayAlpha(o, v);
    };
    set(g_toolbar.backing, a);
    // Hover is alpha-only. Repainting textures for pointer enter/leave burns through
    // SteamVR's fragile SetOverlayRaw path and can eventually invalidate every cell.
    for (auto &m : g_toolbar.modules)
        for (auto &b : m.buttons) set(b.o, a * (b.lit ? 1.f : 0.86f));
    set(g_toolbar.grab, a * g_toolbar.controls * (grabActive ? 1.f : kChromeIdle));
}

void RefaceToolbarBtn(ToolbarBtn &b);  // below

void ShowToolbar(bool on) {
    if (!g_toolbar.built && on) EnsureToolbar();
    auto show = [&](vr::VROverlayHandle_t o) {
        if (o == vr::k_ulOverlayHandleInvalid) return;
        if (on) vr::VROverlay()->ShowOverlay(o);
        else vr::VROverlay()->HideOverlay(o);
    };
    show(g_toolbar.backing);
    show(g_toolbar.grab);
    for (auto &m : g_toolbar.modules)
        for (auto &b : m.buttons) show(b.o);
    g_toolbar.visible = on;
    if (on) {
        // Hide/show must not repaint cells. Their textures survive HideOverlay, and using
        // SetOverlayRaw as a visibility repair eventually exhausts/fails SteamVR's raw path.
        ApplyToolbarAlpha(true);
    }
}

// Shown with the desktop; yields to the SteamVR dashboard as one group with its docked
// screens (UpdateVisibility hides those when this is false).
bool ToolbarWanted() {
    if (!g_toolbar.enabled) return false;
    if (g_toolbar.drag != Drag::None) return true;
    return !vr::VROverlay()->IsDashboardVisible() && ModeVisible();
}

void UpdateToolbarVisibility() {
    if (!g_toolbar.enabled) {
        if (g_toolbar.visible) ShowToolbar(false);
        return;
    }
    EnsureToolbar();
    if (!g_toolbar.placed) {
        Mat hmd;
        if (!DevicePose(vr::k_unTrackedDeviceIndex_Hmd, &hmd)) return;
        SetWorldPose(g_toolbar, DefaultToolbarPose());
        g_toolbar.placed = true;
        SettleToolbarCurve();
    }
    g_toolbar.dashHidden = vr::VROverlay()->IsDashboardVisible();
    const bool want = ToolbarWanted();
    // Transforms stay current while hidden, so the group returns where it belongs.
    PlaceToolbar();
    if (want != g_toolbar.visible) ShowToolbar(want);
}

// ---------------------------------------------------------------- follow / drag / attention

constexpr double kToolbarFollowTau = 0.35;

void LightToolbarGrab() {
    const bool lit = g_toolbar.hoverGrab || g_toolbar.drag != Drag::None;
    if (g_toolbar.grab == vr::k_ulOverlayHandleInvalid || lit == g_toolbar.grabLit) return;
    g_toolbar.grabLit = lit;
    const auto &tex = ToolbarGrabTexture(lit);
    vr::VROverlay()->SetOverlayRaw(g_toolbar.grab, (void *)tex.data(), ChromeStyle::kBarTexW, ChromeStyle::kBarTexH * 2, 4);
}

bool StartToolbarDrag(vr::TrackedDeviceIndex_t dev) {
    if (!g_toolbar.enabled || g_toolbar.drag != Drag::None) return false;
    if (!BeginMoveDrag(g_toolbar, g_toolbar, dev)) return false;
    LightToolbarGrab();
    return true;
}

void UpdateToolbarDrag() {
    if (g_toolbar.drag != Drag::Move) return;
    Mat p;
    if (!MoveDragPose(g_toolbar, &p)) return;
    SetWorldPose(g_toolbar, YawOnlyHead(p));
    SettleToolbarCurve();
}

void EndToolbarDragsBy(vr::TrackedDeviceIndex_t dev) {
    if (g_toolbar.drag == Drag::None || g_toolbar.dragDevice != dev) return;
    EndMoveDrag(g_toolbar, g_toolbar);
    SettleToolbarCurve();
    LightToolbarGrab();
    SpawnLayoutAsync({"toolbar", "capture"});
}

void UpdateToolbarFollow(double dt) {
    if (g_toolbar.drag != Drag::None || !IsSoftFollow(g_toolbar.anchor)) return;
    Mat hmd;
    if (!DevicePose(vr::k_unTrackedDeviceIndex_Hmd, &hmd)) return;
    StepSoftFollow(g_toolbar, hmd, dt, kToolbarFollowTau, g_toolbar.attentionEnabled && g_toolbar.attentionFocused);
}

bool ToolbarInteracting() {
    return g_toolbar.anyHover || g_toolbar.hoverGrab || g_toolbar.drag != Drag::None || TaskbarPopupOpen() ||
           g_tick < g_toolbar.interactUntil;
}

void UpdateToolbarAttention(double dt) {
    const bool hit = g_gazeTarget.kind == GazeKind::Toolbar;
    StepAttention(g_toolbar, hit, dt, ToolbarInteracting());
}

// A laser near the toolbar (or on it) fades the move bar in, as on the screens.
void UpdateToolbarControls() {
    if (!g_toolbar.visible) {
        g_toolbar.controls = 0;
        return;
    }
    Mat anchor;
    if (ToolbarAnchor(&anchor)) {
        const Mat p = ToolbarVisualPose(anchor);
        for (vr::TrackedDeviceIndex_t dev = 1; dev < vr::k_unMaxTrackedDeviceCount; ++dev) {
            Mat d;
            double hx, hy;
            if (vr::VRSystem()->GetTrackedDeviceClass(dev) != vr::TrackedDeviceClass_Controller) continue;
            if (!LaserPose(dev, &d) || !RayOnPlane(p, d, &hx, &hy)) continue;
            const ToolbarArch arch = Arch();
            const double bottom = std::min(GrabY() - GrabHeight() / 2, arch.bottom) - 0.05;
            if (std::fabs(hx) <= arch.width / 2 + 0.06 && hy >= bottom && hy <= arch.top + 0.06)
                g_toolbar.nearUntil = g_tick + kControlsLinger;
        }
    }
    const bool want = ToolbarInteracting() || g_tick < g_toolbar.nearUntil;
    g_toolbar.controls = std::clamp(g_toolbar.controls + (want ? 0.2f : -0.1f), 0.f, 1.f);
}

// Gaze on the bar, its move bar, or the space between (one region, no gaze cursor).
void PickToolbarGaze(const Mat &ray, const double origin[3], GazeTarget *best) {
    if (!g_toolbar.visible) return;
    Mat anchor;
    if (!ToolbarAnchor(&anchor)) return;
    const Mat p = ToolbarVisualPose(anchor);
    double hx, hy;
    if (!RayOnPlane(p, ray, &hx, &hy)) return;
    const ToolbarArch arch = Arch();
    const double top = arch.top, bottom = std::min(GrabY() - GrabHeight() / 2, arch.bottom);
    if (std::fabs(hx) > arch.width / 2 || hy > top || hy < bottom) return;
    const double c[3] = {p.m[0][3] - origin[0], p.m[1][3] - origin[1], p.m[2][3] - origin[2]};
    const double dist = std::sqrt(Dot3(c, c));
    if (dist >= best->distance) return;
    best->kind = GazeKind::Toolbar;
    best->screen = -1;
    best->instrument = -1;
    best->slot = -1;
    best->distance = dist;
}

void LightToolbarBtn(ToolbarBtn &b, bool lit) {
    if (b.o == vr::k_ulOverlayHandleInvalid || b.lit == lit) return;
    b.lit = lit;
    // Hover is presentation state, not new content. Keep the existing texture and vary
    // alpha through ApplyToolbarAlpha instead of streaming another RGBA image to SteamVR.
    ApplyToolbarAlpha(true);
}

// Redraw only when the button's semantic content changed (popup state, tray level,
// running/focused task). Hover is deliberately excluded so raw uploads stay rare.
void RefaceToolbarBtn(ToolbarBtn &b) {
    if (b.o == vr::k_ulOverlayHandleInvalid) return;
    auto face = FaceFor(b, false);
    int tw = ToolbarStyle::kTexBtn, th = ToolbarStyle::kTexBtn;
    if (b.shape == CellShape::AppTile) tw = th = ToolbarStyle::kTexApp;
    if (b.shape == CellShape::Segment) tw = th = ToolbarStyle::kTexSeg;
    if (face.size() < size_t(tw) * th * 4) {
        auto gear = GlyphGear();
        face = b.shape == CellShape::AppTile
                   ? AppTileTexture(false, false, gear, ToolbarStyle::kTexBtn, ToolbarStyle::kTexBtn)
                   : RoundFilledTexture(false, gear, ToolbarStyle::kTexBtn, ToolbarStyle::kTexBtn);
        tw = th = b.shape == CellShape::AppTile ? ToolbarStyle::kTexApp : ToolbarStyle::kTexBtn;
    }
    const auto err = vr::VROverlay()->SetOverlayRaw(b.o, face.data(), uint32_t(tw), uint32_t(th), 4);
    if (err != vr::VROverlayError_None) {
        std::fprintf(stderr, "toolbar: content refresh refused (keeping old texture): %s\n",
                     vr::VROverlay()->GetOverlayErrorNameFromEnum(err));
        return;
    }
    const vr::HmdVector2_t scale = {{float(tw), float(th)}};
    vr::VROverlay()->SetOverlayMouseScale(b.o, &scale);
}

void RefaceTaskbarButtons(const char *prefix) {
    for (auto &m : g_toolbar.modules)
        for (auto &b : m.buttons)
            if (b.action.rfind(prefix, 0) == 0) RefaceToolbarBtn(b);
}

void RefaceAnchor(const std::string &action) {
    if (!action.empty()) RefaceTaskbarButtons(action.c_str());
}

// The task set changed: rebuild the strip model (its width changes). Not mid-drag.
// Backing, move bar and cell overlay handles stay alive. Cells are hidden, repainted and
// repositioned in place so SteamVR never sees same-key destroy/create churn during launch.
void RebuildToolbarForTasks() {
    if (!g_taskbar.rebuild || g_toolbar.drag != Drag::None || !g_toolbar.enabled) return;
    g_taskbar.rebuild = false;
    const bool want = ToolbarWanted() || g_toolbar.visible;
    DestroyToolbarCells();
    EnsureToolbar();
    PlaceToolbar();
    if (want) ShowToolbar(true);
}

void TickTaskbar() {
    if (!g_toolbar.enabled) return;
    if (!g_taskbar.tasksKnown && g_tick - g_taskbar.lastHello >= TaskbarStyle::kHelloEvery) {
        g_taskbar.lastHello = g_tick;
        TaskbarSend("hello");
    }
    RebuildToolbarForTasks();
    PollTaskbarPopup();
    if (TaskbarPopupOpen() && !g_toolbar.visible) ClosePopup(true);
    CheckPopupClickAway(g_toolbar.anyHover || g_toolbar.hoverGrab);
}

void ActivateToolbarBtn(ToolbarBtn &b) {
    if (b.action.rfind("popup:", 0) == 0) {
        OpenPopup(b.action.substr(6), "", b.action);
        return;
    }
    if (b.action.rfind("task:", 0) == 0) {
        const std::string id = b.action.substr(5);
        const TaskTile *t = FindTask(id);
        if (t && t->windows > 1) {
            OpenPopup("windows", id, b.action);  // several windows: pick one
            return;
        }
        ClosePopup(true);
        TaskbarSend("task " + id);
        return;
    }
    if (b.action == "desktop.home" || b.action == "desktop.user") {
        // Shell chrome placeholders for this pass (hierarchy first).
        return;
    }
    if (b.action.rfind("launcher:", 0) == 0) {
        const std::string id = b.action.substr(9);
        Instrument *inst = FindInstrument(id.c_str());
        if (inst && inst->type == InstrumentType::Launcher) {
            ActivateLauncher(*inst);
            return;
        }
        char reply[128] = {};
        AskFrametopLaunch(("action " + id).c_str(), reply, sizeof reply);
        return;
    }
    SpawnLayoutAsync({"action", b.action.c_str()});
}

void PollToolbar() {
    if (!g_toolbar.enabled || !g_toolbar.built) return;
    vr::VREvent_t ev{};
    bool anyHover = false;
    for (auto &m : g_toolbar.modules) {
        for (auto &b : m.buttons) {
            if (b.o == vr::k_ulOverlayHandleInvalid) continue;
            while (vr::VROverlay()->PollNextOverlayEvent(b.o, &ev, sizeof ev)) {
                const bool on = ev.eventType == vr::VREvent_MouseMove || ev.eventType == vr::VREvent_FocusEnter;
                if (on || ev.eventType == vr::VREvent_FocusLeave) {
                    if (b.hover != on) {
                        b.hover = on;
                        LightToolbarBtn(b, on);
                    }
                }
                if (ev.eventType == vr::VREvent_MouseButtonUp) EndDragsBy(ev.trackedDeviceIndex);
                if (ev.eventType == vr::VREvent_MouseButtonDown && ev.data.mouse.button == vr::VRMouseButton_Left) {
                    if (b.slot >= 1 && b.slot <= kSlotCount && !g_slotFilled[b.slot - 1]) continue;
                    ActivateToolbarBtn(b);
                }
                if (ev.eventType == vr::VREvent_MouseButtonDown && ev.data.mouse.button == vr::VRMouseButton_Right &&
                    b.action.rfind("task:", 0) == 0)
                    OpenPopup("taskmenu", b.action.substr(5), b.action);  // the task's window menu
            }
            anyHover |= b.hover;
        }
    }
    g_toolbar.anyHover = anyHover;
    if (g_toolbar.grab == vr::k_ulOverlayHandleInvalid) return;
    while (vr::VROverlay()->PollNextOverlayEvent(g_toolbar.grab, &ev, sizeof ev)) {
        switch (ev.eventType) {
            case vr::VREvent_MouseMove:
            case vr::VREvent_FocusEnter: g_toolbar.hoverGrab = true; break;
            case vr::VREvent_FocusLeave: g_toolbar.hoverGrab = false; break;
            case vr::VREvent_MouseButtonDown:
                if (ev.data.mouse.button == vr::VRMouseButton_Left) StartToolbarDrag(ev.trackedDeviceIndex);
                break;
            case vr::VREvent_MouseButtonUp: EndDragsBy(ev.trackedDeviceIndex); break;
            case vr::VREvent_ScrollDiscrete:
                if (g_toolbar.drag == Drag::Move) PushMoveDrag(g_toolbar, ev.data.scroll.ydelta);
                break;
            default: break;
        }
    }
    LightToolbarGrab();
}

void TickToolbar(double dt) {
    UpdateToolbarFollow(dt);
    UpdateToolbarDrag();
    UpdateToolbarVisibility();
    PollToolbar();
    TickTaskbar();
    if (!g_toolbar.enabled) return;
    UpdateToolbarControls();
    UpdateToolbarAttention(dt);
    if (g_toolbar.visible) ApplyToolbarAlpha();
}

void ToolbarClearMods() {
    DestroyToolbarOverlays();
    g_toolbar.leftMods.clear();
    g_toolbar.centerMods.clear();
    g_toolbar.rightMods.clear();
}

bool ToolbarAddMod(const char *side, const char *type, const char *arg) {
    std::vector<ToolbarMod> *dst = nullptr;
    if (!std::strcmp(side, "left")) dst = &g_toolbar.leftMods;
    else if (!std::strcmp(side, "center")) dst = &g_toolbar.centerMods;
    else if (!std::strcmp(side, "right")) dst = &g_toolbar.rightMods;
    else return false;
    ToolbarMod m;
    if (!std::strcmp(type, "profiles")) m.kind = ToolbarModKind::Profiles;
    else if (!std::strcmp(type, "launcher")) {
        m.kind = ToolbarModKind::Launcher;
        m.arg = arg && arg[0] ? arg : "launcher";
    } else if (!std::strcmp(type, "home")) {
        m.kind = ToolbarModKind::Home;
    } else if (!std::strcmp(type, "user")) {
        m.kind = ToolbarModKind::User;
    } else if (!std::strcmp(type, "start")) {
        m.kind = ToolbarModKind::Start;
    } else if (!std::strcmp(type, "tasks")) {
        m.kind = ToolbarModKind::Tasks;
    } else if (!std::strcmp(type, "displays")) {
        m.kind = ToolbarModKind::Displays;
    } else if (!std::strcmp(type, "tray")) {
        m.kind = ToolbarModKind::Tray;
    } else if (!std::strcmp(type, "action")) {
        m.kind = ToolbarModKind::Action;
        if (!arg || !arg[0]) return false;
        m.arg = arg;
    } else
        return false;
    dst->push_back(std::move(m));
    DestroyToolbarOverlays();
    return true;
}

size_t ToolbarButtonCount() {
    size_t n = 0;
    for (const auto &m : g_toolbar.modules) n += m.buttons.size();
    return n;
}

#include "toolbar_dock.inc"

void SetToolbarEnabled(bool on) {
    if (on == g_toolbar.enabled) return;
    if (!on) {
        ClosePopup(true);
        UndockAllScreens();
        EndMoveDrag(g_toolbar, g_toolbar);
        ShowToolbar(false);
        DestroyToolbarOverlays();
    }
    g_toolbar.enabled = on;
    if (on) {
        EnsureToolbar();
        UpdateToolbarVisibility();
    }
}

// "toolbar ..." on the control socket. `get` matches a screen's `get N` reply so ft-layout
// can reuse its parser for the toolbar body.
void ToolbarCommand(const char *rest, char *reply, int size) {
    char side[16] = {}, type[32] = {}, arg[128] = {}, mode[32] = {};
    float r[12] = {};
    double x, y, z, yaw, pitch, roll, a, b;
    int n = 0;
    auto ok = [&] { std::snprintf(reply, size, "ok"); };
    if (!std::strcmp(rest, "enable")) {
        SetToolbarEnabled(true);
        ok();
    } else if (!std::strcmp(rest, "disable")) {
        SetToolbarEnabled(false);
        ok();
    } else if (!std::strcmp(rest, "clear")) {
        ToolbarClearMods();
        ok();
    } else if (std::sscanf(rest, "module %15s %31s %127s", side, type, arg) >= 2) {
        if (!ToolbarAddMod(side, type, arg[0] ? arg : ""))
            return (void)std::snprintf(reply, size,
                                       "error toolbar module wants left|center|right "
                                       "start|tasks|displays|tray|home|launcher|profiles|action|user …");
        if (g_toolbar.enabled) {
            EnsureToolbar();
            UpdateToolbarVisibility();
        }
        ok();
    } else if (std::sscanf(rest, "place %lf %lf %lf %lf %lf %lf", &x, &y, &z, &yaw, &pitch, &roll) == 6) {
        // Upright: the dock anchor never tilts (pitch/roll accepted for symmetry, ignored).
        EndMoveDrag(g_toolbar, g_toolbar);
        const AnchorMode keep = g_toolbar.anchor;
        SetWorldPose(g_toolbar, YawOnlyHead(PanelPose(x, y, z, yaw, 0, 0)));
        g_toolbar.placed = true;
        if (keep != AnchorMode::World) RepinInPlace(g_toolbar, keep);
        SettleToolbarCurve();
        ok();
    } else if (!std::strcmp(rest, "recenter")) {
        EndMoveDrag(g_toolbar, g_toolbar);
        Mat hmd;
        if (!DevicePose(vr::k_unTrackedDeviceIndex_Hmd, &hmd))
            return (void)std::snprintf(reply, size, "error no head pose (headset off?)");
        const AnchorMode keep = g_toolbar.anchor;
        SetWorldPose(g_toolbar, DefaultToolbarPose());
        g_toolbar.placed = true;
        if (keep != AnchorMode::World) RepinInPlace(g_toolbar, keep);
        SettleToolbarCurve();
        ok();
    } else if (const int got = std::sscanf(rest, "pin %31s %f %f %f %f %f %f %f %f %f %f %f %f", mode, &r[0], &r[1],
                                           &r[2], &r[3], &r[4], &r[5], &r[6], &r[7], &r[8], &r[9], &r[10], &r[11]);
               got >= 1) {
        if (std::strcmp(mode, "world") && std::strcmp(mode, "head") && std::strcmp(mode, "head-rigid") &&
            std::strcmp(mode, "yaw-follow") && std::strcmp(mode, "position-follow"))
            return (void)std::snprintf(reply, size, "error toolbar anchors: world head head-rigid yaw-follow position-follow");
        EndMoveDrag(g_toolbar, g_toolbar);
        const AnchorMode am = ParseAnchorMode(mode);
        bool done;
        if (got == 13 && am != AnchorMode::World) {
            Mat rel = Identity();
            for (int k = 0; k < 12; ++k) rel.m[k / 4][k % 4] = r[k];
            done = ApplyFollowMode(g_toolbar, am, rel);
        } else {
            done = RepinInPlace(g_toolbar, am);
        }
        if (!done) return (void)std::snprintf(reply, size, "error no %s pose", mode);
        SettleToolbarCurve();
        std::snprintf(reply, size, "ok %s", AnchorModeName(g_toolbar.anchor));
    } else if (std::sscanf(rest, "opacity %lf %lf", &a, &b) >= 1) {
        if (std::sscanf(rest, "opacity %lf %lf", &a, &b) < 2) b = g_toolbar.idleOpacity;
        SetAttentionOpacity(g_toolbar, float(a), float(b));
        ApplyToolbarAlpha(true);
        ok();
    } else if (std::strncmp(rest, "attention ", 10) == 0) {
        if (!ParseAttentionArgs(g_toolbar, rest + 10))
            return (void)std::snprintf(reply, size, "error attention on [in out dwell hold]|off");
        ApplyToolbarAlpha(true);
        ok();
    } else if (std::strncmp(rest, "deadzone ", 9) == 0) {
        if (!ParseDeadzoneArgs(g_toolbar, rest + 9))
            return (void)std::snprintf(reply, size, "error deadzone on [degrees metres]|off");
        ok();
    } else if (std::sscanf(rest, "scale %lf", &a) == 1) {
        g_toolbar.scale = std::clamp(a, 0.5, 2.0);
        ok();
    } else if (std::sscanf(rest, "attach screen %d", &n) == 1) {
        // One-shot: put the toolbar under screen N (older layouts); it does not follow it.
        Screen *s = Find(n);
        Mat sp;
        if (!s || !ScreenPose(*s, &sp)) return (void)std::snprintf(reply, size, "error no screen %d", n);
        EndMoveDrag(g_toolbar, g_toolbar);
        const double drop = s->heightMetres() / 2 + ToolbarStyle::kScreenGap + TS(ToolbarStyle::kBarH) / 2;
        SetWorldPose(g_toolbar, YawOnlyHead(Mul(sp, Translation(0, -drop, 0.02))));
        g_toolbar.placed = true;
        SettleToolbarCurve();
        ok();
    } else if (!std::strcmp(rest, "get")) {
        Mat m;
        if (!FollowPose(g_toolbar, &m)) return (void)std::snprintf(reply, size, "error toolbar has no pose");
        int len = std::snprintf(
            reply, size,
            "ok %.4f %.4f %.4f  %.5f %.5f %.5f  %.5f %.5f %.5f  %.5f %.5f %.5f  %.4f %.4f %.3f %.3f %.3f %s",
            m.m[0][3], m.m[1][3], m.m[2][3], m.m[0][0], m.m[1][0], m.m[2][0], m.m[0][1], m.m[1][1], m.m[2][1],
            m.m[0][2], m.m[1][2], m.m[2][2], g_toolbar.metres, TS(ToolbarStyle::kBarH), g_toolbar.curve,
            g_toolbar.activeOpacity, g_toolbar.idleOpacity, AnchorModeName(g_toolbar.anchor));
        if (g_toolbar.anchor != AnchorMode::World)
            for (int k = 0; k < 12 && len < size; ++k)
                len += std::snprintf(reply + len, size - len, " %.5f", g_toolbar.pinRel.m[k / 4][k % 4]);
    } else if (!std::strcmp(rest, "state")) {
        std::snprintf(reply, size,
                      "ok enabled=%d visible=%d dash_yield=%d anchor=%s placed=%d drag=%d buttons=%zu modules=%zu "
                      "curve=%.3f metres=%.3f scale=%.2f active=%.2f idle=%.2f attention=%d focused=%d resolved=%.2f "
                      "deadzone=%d docked=%d",
                      g_toolbar.enabled ? 1 : 0, g_toolbar.visible ? 1 : 0, g_toolbar.dashHidden ? 1 : 0,
                      AnchorModeName(g_toolbar.anchor), g_toolbar.placed ? 1 : 0,
                      g_toolbar.drag != Drag::None ? 1 : 0, ToolbarButtonCount(), g_toolbar.modules.size(),
                      g_toolbar.curve, g_toolbar.metres, g_toolbar.scale, g_toolbar.activeOpacity,
                      g_toolbar.idleOpacity, g_toolbar.attentionEnabled ? 1 : 0, g_toolbar.attentionFocused ? 1 : 0,
                      g_toolbar.attentionResolved, g_toolbar.followDeadzone ? 1 : 0, DockedCount());
    } else if (TaskbarCommand(rest, reply, size)) {
    } else {
        std::snprintf(reply, size,
                      "error toolbar commands: enable|disable|clear|module|place|recenter|pin|opacity|attention|"
                      "deadzone|scale|attach screen N|get|state|taskbar|open KIND");
    }
}
