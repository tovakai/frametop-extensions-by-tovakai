// Taskbar side of the DesktopToolbar — included by desktop_toolbar.inc (inside vr.cpp's
// anonymous namespace). ft-screens draws the Start / Tasks / Displays / Tray modules and
// the popup overlays, and does every hit test; session/ft-taskbar.py on the host supplies
// the tasks (from the nested KWin), the tray state and the rendered popups.
//
//   ft-screens -> @frametop_taskbar   hello | open KIND [ARG] | click KIND ID U V |
//                                     scroll KIND DY | closed KIND | task ID
//   ft-taskbar -> @ft_screens         toolbar popup KIND SERIAL | toolbar popup-close KIND |
//                                     toolbar tasks SERIAL | toolbar tray volume LEVEL PCT |
//                                     toolbar tray wifi ENABLED BARS CONNECTED
// Popup image + hit rects and the task list are files in /run/user/UID/frametop-taskbar/.

namespace TaskbarStyle {
constexpr uint32_t kSortPopup = 4, kSortHilite = 5;
constexpr double kPopupGap = 0.018;  // bar top edge -> popup bottom edge
constexpr double kPopupDz = 0.03;    // popups float a little in front of the bar
constexpr double kHiliteDz = 0.002;
constexpr long kHelloEvery = 450;    // ticks between hellos until ft-taskbar answers
constexpr int kIconN = 80;           // app icon texels inside a task tile
constexpr long kSliderEvery = 4;     // ticks between slider updates while dragging
}  // namespace TaskbarStyle

struct TaskTile {
    std::string id, icon, name;  // id stays percent-encoded: it is only echoed back
    bool pinned = false, focused = false;
    int windows = 0;
};

struct PopupItem {
    std::string id;
    int x = 0, y = 0, w = 0, h = 0;  // texels, top-left origin
};

struct TaskbarState {
    std::vector<TaskTile> tasks;
    bool tasksKnown = false;  // ft-taskbar has answered at least once
    bool rebuild = false;     // the task set changed: rebuild the strip when not dragging
    int volLevel = 2, volPct = 0;
    bool wifiEnabled = false, wifiConnected = false;
    int wifiBars = 0;
    long lastHello = -100000;
    int sock = -1;
    // The popup: one at a time, hanging from the toolbar button whose action is `anchor`.
    vr::VROverlayHandle_t popup = vr::k_ulOverlayHandleInvalid;
    vr::VROverlayHandle_t hilite = vr::k_ulOverlayHandleInvalid;
    std::string kind, arg, anchor;
    bool shown = false;
    int texW = 0, texH = 0;
    double metres = 0;  // at toolbar scale 1
    std::vector<PopupItem> items;
    int hover = -1, pressed = -1;
    bool hoverPopup = false;
    long lastSlider = 0;
    uint64_t triggerDown = 0;  // one bit per tracked device
};

TaskbarState g_taskbar;

std::string TaskbarDir() { return "/run/user/" + std::to_string(getuid()) + "/frametop-taskbar"; }

void TaskbarSend(const std::string &msg) {
    if (g_taskbar.sock < 0) g_taskbar.sock = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (g_taskbar.sock < 0) return;
    sockaddr_un dest{};
    dest.sun_family = AF_UNIX;
    const char kName[] = "frametop_taskbar";
    std::memcpy(dest.sun_path + 1, kName, sizeof kName - 1);
    const socklen_t len = socklen_t(offsetof(sockaddr_un, sun_path) + 1 + sizeof kName - 1);
    sendto(g_taskbar.sock, msg.data(), msg.size(), MSG_DONTWAIT, reinterpret_cast<sockaddr *>(&dest), len);
}

bool TaskbarPopupOpen() { return !g_taskbar.kind.empty(); }

// ---------------------------------------------------------------- glyphs

std::vector<uint8_t> GlyphStart() {
    return ControlTexture(
        ToolbarStyle::kTexBtn, InDisc,
        [](double u, double v) {
            const double au = std::fabs(u), av = std::fabs(v);
            return au > 0.06 && au < 0.38 && av > 0.06 && av < 0.38;
        },
        [](double, double) { return false; });
}

std::vector<uint8_t> GlyphMonitor() {
    return ControlTexture(
        ToolbarStyle::kTexBtn, InDisc,
        [](double u, double v) {
            const double au = std::fabs(u);
            const bool frame = au < 0.50 && v > -0.14 && v < 0.40 && !(au < 0.39 && v > -0.04 && v < 0.30);
            const bool stand = au < 0.06 && v <= -0.14 && v > -0.30;
            const bool base = au < 0.24 && v <= -0.30 && v > -0.39;
            return frame || stand || base;
        },
        [](double, double) { return false; });
}

std::vector<uint8_t> GlyphVolume(int level) {
    return ControlTexture(
        ToolbarStyle::kTexBtn, InDisc,
        [level](double u, double v) {
            const double av = std::fabs(v);
            if (u > -0.52 && u < -0.30 && av < 0.15) return true;                    // box
            if (u >= -0.30 && u < -0.04 && av < 0.15 + (u + 0.30) * 1.1) return true;  // cone
            if (level <= 0) {
                const double cu = u - 0.28;
                return std::fabs(cu) < 0.17 && av < 0.17 && (std::fabs(cu - v) < 0.06 || std::fabs(cu + v) < 0.06);
            }
            const double r = std::hypot(u + 0.02, v);
            if (std::fabs(std::atan2(v, u + 0.02)) > 0.8) return false;
            for (int i = 0; i < std::min(level, 3); ++i)
                if (std::fabs(r - (0.20 + 0.15 * i)) < 0.045) return true;
            return false;
        },
        [](double, double) { return false; });
}

std::vector<uint8_t> GlyphWifi(bool enabled, int bars, bool connected) {
    return ControlTexture(
        ToolbarStyle::kTexBtn, InDisc,
        [=](double u, double v) {
            const double oy = v + 0.36, r = std::hypot(u, oy);
            const bool slash = !connected && std::fabs(u + v * 0.9) < 0.055 && std::fabs(u) < 0.42;
            if (slash) return true;
            if (r < 0.09) return true;
            if (oy <= 0 || std::fabs(std::atan2(u, oy)) > 0.78) return false;
            const int arcs = !enabled ? 0 : connected ? std::clamp(bars - 1, 0, 3) : 3;
            for (int i = 0; i < arcs; ++i)
                if (std::fabs(r - (0.25 + 0.19 * i)) < 0.05) return true;
            return false;
        },
        [](double, double) { return false; });
}

// ---------------------------------------------------------------- task tiles

// App icon (PNG written by ft-taskbar), resampled once to kIconN² RGBA.
const std::vector<uint8_t> *TaskIcon(const std::string &path) {
    static std::map<std::string, std::vector<uint8_t>> cache;
    if (path.empty()) return nullptr;
    auto it = cache.find(path);
    if (it != cache.end()) return it->second.empty() ? nullptr : &it->second;
    std::vector<uint8_t> out;
    int w = 0, h = 0, n = 0;
    if (stbi_uc *img = stbi_load(path.c_str(), &w, &h, &n, 4)) {
        const int N = TaskbarStyle::kIconN;
        out.assign(size_t(N) * N * 4, 0);
        const double s = double(std::max(w, h)) / N;
        const int ox = int((N - w / s) / 2), oy = int((N - h / s) / 2);
        for (int y = 0; y < N; ++y)
            for (int x = 0; x < N; ++x) {
                // Box filter over the source texels this output texel covers.
                const int sx0 = int((x - ox) * s), sy0 = int((y - oy) * s);
                const int sx1 = std::max(sx0 + 1, int((x - ox + 1) * s)), sy1 = std::max(sy0 + 1, int((y - oy + 1) * s));
                double acc[4] = {0, 0, 0, 0}, cnt = 0;
                for (int sy = std::max(0, sy0); sy < std::min(h, sy1); ++sy)
                    for (int sx = std::max(0, sx0); sx < std::min(w, sx1); ++sx) {
                        const stbi_uc *p = img + (size_t(sy) * w + sx) * 4;
                        const double a = p[3] / 255.0;
                        acc[0] += p[0] * a, acc[1] += p[1] * a, acc[2] += p[2] * a, acc[3] += p[3];
                        cnt += 1;
                    }
                if (cnt <= 0 || acc[3] <= 0) continue;
                uint8_t *q = &out[(size_t(y) * N + x) * 4];
                const double alpha = acc[3] / cnt;
                for (int k = 0; k < 3; ++k) q[k] = uint8_t(std::clamp(acc[k] / cnt / (alpha / 255.0), 0.0, 255.0));
                q[3] = uint8_t(alpha);
            }
        stbi_image_free(img);
    }
    auto &slot = cache[path];
    slot = std::move(out);
    return slot.empty() ? nullptr : &slot;
}

void PaintRing(std::vector<uint8_t> &px, int n) {
    for (int y = 0; y < n; ++y)
        for (int x = 0; x < n; ++x) {
            const int m = std::min(std::min(x, y), std::min(n - 1 - x, n - 1 - y));
            if (m > 2 || m < 1) continue;
            uint8_t *p = &px[(size_t(y) * n + x) * 4];
            if (p[3] < 20) continue;
            p[0] = ToolbarStyle::kAccentR, p[1] = ToolbarStyle::kAccentG, p[2] = ToolbarStyle::kAccentB, p[3] = 220;
        }
}

// Running: a short accent underline; focused: the full-width one (SteamVR's selected app).
void PaintTaskUnderline(std::vector<uint8_t> &px, int n, bool focused) {
    const int y0 = n - ToolbarStyle::kUnderlinePx - 6;
    const int x0 = focused ? n / 6 : n * 3 / 8, x1 = n - x0;
    for (int y = y0; y < y0 + ToolbarStyle::kUnderlinePx; ++y)
        for (int x = x0; x < x1; ++x) {
            uint8_t *p = &px[(size_t(y) * n + x) * 4];
            p[0] = ToolbarStyle::kAccentR, p[1] = ToolbarStyle::kAccentG, p[2] = ToolbarStyle::kAccentB, p[3] = 255;
        }
}

// Composite a kIconN² icon into an n² tile. A hair below centre: underlines sit
// underneath, and a true centre still reads slightly high on the arched bar.
void PaintIcon(std::vector<uint8_t> &px, int n, const std::vector<uint8_t> &icon, float dim) {
    const int N = TaskbarStyle::kIconN, ox = (n - N) / 2, oy = (n - N) / 2 + 2;
    for (int y = 0; y < N; ++y)
        for (int x = 0; x < N; ++x) {
            const uint8_t *s = &icon[(size_t(y) * N + x) * 4];
            if (!s[3]) continue;
            const int dy = oy + y, dx = ox + x;
            if (dy < 0 || dy >= n || dx < 0 || dx >= n) continue;
            uint8_t *p = &px[(size_t(dy) * n + dx) * 4];
            const float a = s[3] / 255.f;
            for (int k = 0; k < 3; ++k) p[k] = uint8_t(s[k] * dim * a + p[k] * (1 - a));
            p[3] = uint8_t(std::min(255.f, p[3] + 255 * a));
        }
}

// screens/assets/start-icon.png next to this checkout's build (white art on transparent).
const std::vector<uint8_t> *StartIcon() {
    static std::string path = [] {
        char exe[PATH_MAX] = {};
        const ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
        if (n <= 0) return std::string();
        const std::string s(exe, size_t(n));
        const auto cut = s.rfind("/screens/");
        return cut == std::string::npos ? std::string() : s.substr(0, cut) + "/screens/assets/start-icon.png";
    }();
    return TaskIcon(path);
}

std::vector<uint8_t> StartTileTexture(bool lit) {
    const int n = ToolbarStyle::kTexApp;
    auto px = CellFill(n, n * 0.17, lit);
    if (const auto *icon = StartIcon()) PaintIcon(px, n, *icon, lit ? 1.f : 0.9f);
    if (lit) PaintRing(px, n);
    return px;
}

std::vector<uint8_t> TaskTileTexture(const TaskTile &t, bool lit) {
    const int n = ToolbarStyle::kTexApp;
    auto px = CellFill(n, n * 0.17, lit);
    if (const auto *icon = TaskIcon(t.icon)) {
        PaintIcon(px, n, *icon, lit || t.windows > 0 ? 1.f : 0.85f);
    } else {
        CompositeGlyph(px, n, GlyphMonitor(), ToolbarStyle::kTexBtn, ToolbarStyle::kTexBtn,
                       lit ? 1.f : ToolbarStyle::kIconIdle, 0.52);
    }
    if (t.windows > 0) PaintTaskUnderline(px, n, t.focused);
    if (lit) PaintRing(px, n);
    return px;
}

const TaskTile *FindTask(const std::string &id) {
    for (const auto &t : g_taskbar.tasks)
        if (t.id == id) return &t;
    return nullptr;
}

// Faces for taskbar buttons (empty: not a taskbar button). A button whose popup is open
// shows lit, like SteamVR's active control.
std::vector<uint8_t> TaskbarFace(const std::string &action, bool lit, bool appTile) {
    const bool open = TaskbarPopupOpen() && g_taskbar.anchor == action;
    lit = lit || open;
    std::vector<uint8_t> glyph;
    if (action.rfind("task:", 0) == 0) {
        const TaskTile *t = FindTask(action.substr(5));
        return t ? TaskTileTexture(*t, lit) : std::vector<uint8_t>{};
    }
    if (action == "popup:start" && appTile && StartIcon()) return StartTileTexture(lit);
    if (action == "popup:start") glyph = GlyphStart();
    else if (action == "popup:profiles") glyph = GlyphMonitor();
    else if (action == "popup:volume") glyph = GlyphVolume(g_taskbar.volLevel);
    else if (action == "popup:wifi") glyph = GlyphWifi(g_taskbar.wifiEnabled, g_taskbar.wifiBars, g_taskbar.wifiConnected);
    else return {};
    if (appTile) {
        auto px = AppTileTexture(lit, lit, glyph, ToolbarStyle::kTexBtn, ToolbarStyle::kTexBtn);
        return px;
    }
    return RoundFilledTexture(lit, glyph, ToolbarStyle::kTexBtn, ToolbarStyle::kTexBtn);
}

// ---------------------------------------------------------------- popup

void HidePopupOverlays() {
    if (g_taskbar.popup != vr::k_ulOverlayHandleInvalid) vr::VROverlay()->HideOverlay(g_taskbar.popup);
    if (g_taskbar.hilite != vr::k_ulOverlayHandleInvalid) vr::VROverlay()->HideOverlay(g_taskbar.hilite);
    g_taskbar.shown = false;
}

void RefaceAnchor(const std::string &action);  // below the module code (desktop_toolbar.inc)

// notify: tell ft-taskbar (false when it asked for the close itself).
void ClosePopup(bool notify) {
    if (!TaskbarPopupOpen()) return;
    const std::string kind = g_taskbar.kind, anchor = g_taskbar.anchor;
    g_taskbar.kind.clear();
    g_taskbar.arg.clear();
    g_taskbar.anchor.clear();
    g_taskbar.items.clear();
    g_taskbar.hover = g_taskbar.pressed = -1;
    g_taskbar.hoverPopup = false;
    HidePopupOverlays();
    // Launching from Start closes the popup and looks at the new window: keep the bar
    // awake briefly so attention does not slam it to idle mid-rebuild.
    g_toolbar.interactUntil = g_tick + 45;  // ~0.75 s at 60 Hz
    if (notify) TaskbarSend("closed " + kind);
    RefaceAnchor(anchor);
}

// Toggle: the same button closes its popup; another button swaps it (one at a time).
void OpenPopup(const std::string &kind, const std::string &arg, const std::string &anchor) {
    if (g_taskbar.kind == kind && g_taskbar.arg == arg) {
        ClosePopup(true);
        return;
    }
    ClosePopup(true);
    g_taskbar.kind = kind;
    g_taskbar.arg = arg;
    g_taskbar.anchor = anchor;
    TaskbarSend(arg.empty() ? "open " + kind : "open " + kind + " " + arg);
    RefaceAnchor(anchor);
}

bool LoadPopupFiles(const std::string &kind) {
    const std::string dir = TaskbarDir();
    std::FILE *f = std::fopen((dir + "/popup.txt").c_str(), "r");
    if (!f) return false;
    char line[512], k[32] = {}, id[256] = {};
    int serial = 0, w = 0, h = 0;
    double metres = 0;
    std::vector<PopupItem> items;
    bool headerOk = false;
    while (std::fgets(line, sizeof line, f)) {
        PopupItem it;
        if (std::sscanf(line, "popup %31s %d %d %d %lf", k, &serial, &w, &h, &metres) == 5) headerOk = kind == k;
        else if (std::sscanf(line, "item %255s %d %d %d %d", id, &it.x, &it.y, &it.w, &it.h) == 5) {
            it.id = id;
            items.push_back(std::move(it));
        }
    }
    std::fclose(f);
    if (!headerOk || w <= 0 || h <= 0 || metres <= 0) return false;
    int iw = 0, ih = 0, n = 0;
    stbi_uc *img = stbi_load((dir + "/popup.png").c_str(), &iw, &ih, &n, 4);
    if (!img) return false;
    if (g_taskbar.popup == vr::k_ulOverlayHandleInvalid) {
        const std::vector<uint8_t> blank(4 * 4 * 4, 0);
        g_taskbar.popup = MakeChrome("frametop.toolbar.popup", "Toolbar popup", blank, 4, 4);
        vr::VROverlay()->SetOverlayFlag(g_taskbar.popup, vr::VROverlayFlags_SendVRDiscreteScrollEvents, true);
        g_taskbar.hilite = MakeChrome("frametop.toolbar.popup.hl", "Toolbar popup highlight", blank, 4, 4);
        vr::VROverlay()->SetOverlayInputMethod(g_taskbar.hilite, vr::VROverlayInputMethod_None);
    }
    vr::VROverlay()->SetOverlayRaw(g_taskbar.popup, img, uint32_t(iw), uint32_t(ih), 4);
    stbi_image_free(img);
    const vr::HmdVector2_t scale = {float(iw), float(ih)};
    vr::VROverlay()->SetOverlayMouseScale(g_taskbar.popup, &scale);
    g_taskbar.texW = iw, g_taskbar.texH = ih;
    g_taskbar.metres = metres * double(iw) / w;
    g_taskbar.items = std::move(items);
    g_taskbar.hover = -1;
    return true;
}

double PopupMetres() { return TS(g_taskbar.metres); }

void PlaceHilite(const Mat &pp) {
    if (g_taskbar.hilite == vr::k_ulOverlayHandleInvalid) return;
    if (!g_taskbar.shown || g_taskbar.hover < 0 || g_taskbar.hover >= int(g_taskbar.items.size())) {
        vr::VROverlay()->HideOverlay(g_taskbar.hilite);
        return;
    }
    const PopupItem &it = g_taskbar.items[size_t(g_taskbar.hover)];
    const double s = PopupMetres() / g_taskbar.texW;
    vr::VROverlay()->SetOverlayWidthInMeters(g_taskbar.hilite, float(it.w * s));
    const Mat hp = Mul(pp, Translation((it.x + it.w / 2.0 - g_taskbar.texW / 2.0) * s,
                                       (g_taskbar.texH / 2.0 - (it.y + it.h / 2.0)) * s, TaskbarStyle::kHiliteDz));
    vr::VROverlay()->SetOverlayTransformAbsolute(g_taskbar.hilite, vr::TrackingUniverseStanding, &hp);
    ApplyOverlaySort(g_taskbar.hilite, TaskbarStyle::kSortHilite, false);
    vr::VROverlay()->ShowOverlay(g_taskbar.hilite);
}

void SetHover(int item) {
    if (item == g_taskbar.hover) return;
    g_taskbar.hover = item;
    if (item >= 0 && item < int(g_taskbar.items.size())) {
        const PopupItem &it = g_taskbar.items[size_t(item)];
        const int w = std::max(8, it.w / 2), h = std::max(8, it.h / 2);
        const auto px = RoundRectTexture(w, h, 6, 255, 255, 255, 30);
        vr::VROverlay()->SetOverlayRaw(g_taskbar.hilite, const_cast<uint8_t *>(px.data()), uint32_t(w), uint32_t(h), 4);
    }
}

// Upright at `at`'s position, square to the line from it to the head on both axes.
Mat FacingHead(const Mat &at) {
    Mat hmd;
    if (!DevicePose(vr::k_unTrackedDeviceIndex_Hmd, &hmd)) return at;
    const double x = at.m[0][3], y = at.m[1][3], z = at.m[2][3];
    const double dx = hmd.m[0][3] - x, dy = hmd.m[1][3] - y, dz = hmd.m[2][3] - z;
    const double yaw = std::atan2(dx, dz) * 180 / M_PI;
    const double pitch = -std::atan2(dy, std::max(0.05, std::hypot(dx, dz))) * 180 / M_PI;
    return PanelPose(x, y, z, yaw, pitch, 0);
}

// Hang the popup above its button, facing the head (not the bar's tilt or arc).
// anchorU: the button's arc position (NaN: the button is gone, so the popup closes).
void PlaceTaskbarPopup(const Mat &visual, double anchorU) {
    if (!TaskbarPopupOpen() || !g_taskbar.shown) return;
    if (std::isnan(anchorU)) {
        ClosePopup(true);
        return;
    }
    const double m = PopupMetres(), h = m * g_taskbar.texH / g_taskbar.texW;
    const Mat at = Mul(visual, ToolbarOnArch(Arch(), anchorU, TS(TaskbarStyle::kPopupDz), false));
    const Mat pp = Mul(FacingHead(at),
                       Translation(0, TS(ToolbarStyle::kBarH) / 2 + TS(TaskbarStyle::kPopupGap) + h / 2, 0));
    vr::VROverlay()->SetOverlayWidthInMeters(g_taskbar.popup, float(m));
    vr::VROverlay()->SetOverlayTransformAbsolute(g_taskbar.popup, vr::TrackingUniverseStanding, &pp);
    ApplyOverlaySort(g_taskbar.popup, TaskbarStyle::kSortPopup, false);
    PlaceHilite(pp);
}

int HitPopupItem(double x, double y) {
    // Last match wins: small controls (pin toggles) sit on top of the tiles they decorate.
    for (int i = int(g_taskbar.items.size()) - 1; i >= 0; --i) {
        const PopupItem &it = g_taskbar.items[size_t(i)];
        if (x >= it.x && x < it.x + it.w && y >= it.y && y < it.y + it.h) return i;
    }
    return -1;
}

void SendPopupClick(int item, double x, double y) {
    const PopupItem &it = g_taskbar.items[size_t(item)];
    char buf[400];
    std::snprintf(buf, sizeof buf, "click %s %s %.3f %.3f", g_taskbar.kind.c_str(), it.id.c_str(),
                  std::clamp((x - it.x) / std::max(1, it.w), 0.0, 1.0), std::clamp((y - it.y) / std::max(1, it.h), 0.0, 1.0));
    TaskbarSend(buf);
}

void PollTaskbarPopup() {
    if (g_taskbar.popup == vr::k_ulOverlayHandleInvalid) return;
    vr::VREvent_t ev{};
    while (vr::VROverlay()->PollNextOverlayEvent(g_taskbar.popup, &ev, sizeof ev)) {
        if (!g_taskbar.shown) continue;
        const double x = ev.data.mouse.x, y = g_taskbar.texH - ev.data.mouse.y;  // OpenVR: bottom-left origin
        switch (ev.eventType) {
            case vr::VREvent_MouseMove:
                g_taskbar.hoverPopup = true;
                SetHover(HitPopupItem(x, y));
                if (g_taskbar.pressed >= 0 && g_taskbar.items[size_t(g_taskbar.pressed)].id == "slider" &&
                    g_tick - g_taskbar.lastSlider >= TaskbarStyle::kSliderEvery) {
                    g_taskbar.lastSlider = g_tick;
                    SendPopupClick(g_taskbar.pressed, x, y);
                }
                break;
            case vr::VREvent_FocusEnter: g_taskbar.hoverPopup = true; break;
            case vr::VREvent_FocusLeave:
                g_taskbar.hoverPopup = false;
                g_taskbar.pressed = -1;
                SetHover(-1);
                break;
            case vr::VREvent_MouseButtonDown:
                if (ev.data.mouse.button != vr::VRMouseButton_Left) break;
                g_taskbar.pressed = HitPopupItem(x, y);
                if (g_taskbar.pressed >= 0) SendPopupClick(g_taskbar.pressed, x, y);
                break;
            case vr::VREvent_MouseButtonUp:
                g_taskbar.pressed = -1;
                EndDragsBy(ev.trackedDeviceIndex);
                break;
            case vr::VREvent_ScrollDiscrete:
                if (ev.data.scroll.ydelta != 0) {
                    char buf[64];
                    std::snprintf(buf, sizeof buf, "scroll %s %.2f", g_taskbar.kind.c_str(), ev.data.scroll.ydelta);
                    TaskbarSend(buf);
                }
                break;
            default: break;
        }
    }
}

// Click-away: a trigger press that lands on neither the popup nor the toolbar closes it.
void CheckPopupClickAway(bool onToolbar) {
    uint64_t down = 0;
    for (vr::TrackedDeviceIndex_t dev = 1; dev < vr::k_unMaxTrackedDeviceCount && dev < 64; ++dev) {
        if (vr::VRSystem()->GetTrackedDeviceClass(dev) != vr::TrackedDeviceClass_Controller) continue;
        vr::VRControllerState_t st{};
        if (!vr::VRSystem()->GetControllerState(dev, &st, sizeof st)) continue;
        if (st.ulButtonPressed & vr::ButtonMaskFromId(vr::k_EButton_SteamVR_Trigger)) down |= uint64_t(1) << dev;
    }
    const uint64_t pressed = down & ~g_taskbar.triggerDown;
    g_taskbar.triggerDown = down;
    if (pressed && TaskbarPopupOpen() && !g_taskbar.hoverPopup && !onToolbar) ClosePopup(true);
}

// ---------------------------------------------------------------- state from ft-taskbar

bool LoadTasks() {
    std::FILE *f = std::fopen((TaskbarDir() + "/tasks.txt").c_str(), "r");
    if (!f) return false;
    std::vector<TaskTile> tasks;
    char line[1024];
    while (std::fgets(line, sizeof line, f)) {
        std::string s(line);
        while (!s.empty() && (s.back() == '\n' || s.back() == '\r')) s.pop_back();
        std::vector<std::string> fld;
        size_t a = 0;
        for (size_t b; (b = s.find('\t', a)) != std::string::npos; a = b + 1) fld.push_back(s.substr(a, b - a));
        fld.push_back(s.substr(a));
        if (fld.size() < 7 || fld[0] != "task") continue;
        TaskTile t;
        t.id = fld[1];
        t.pinned = fld[2] == "1";
        t.windows = std::atoi(fld[3].c_str());
        t.focused = fld[4] == "1";
        t.icon = fld[5];
        t.name = fld[6];
        tasks.push_back(std::move(t));
    }
    std::fclose(f);
    bool sameSet = tasks.size() == g_taskbar.tasks.size();
    for (size_t i = 0; sameSet && i < tasks.size(); ++i) sameSet = tasks[i].id == g_taskbar.tasks[i].id;
    g_taskbar.tasks = std::move(tasks);
    g_taskbar.tasksKnown = true;
    if (!sameSet) g_taskbar.rebuild = true;
    return sameSet;
}

void RefaceTaskbarButtons(const char *prefix);  // desktop_toolbar.inc

// "toolbar popup|popup-close|tasks|tray ..." from ft-taskbar. False: not a taskbar command.
bool TaskbarCommand(const char *rest, char *reply, int size) {
    char kind[32] = {};
    int serial = 0, a = 0, b = 0, c = 0;
    if (std::sscanf(rest, "popup %31s %d", kind, &serial) == 2) {
        if (g_taskbar.kind != kind) {
            TaskbarSend(std::string("closed ") + kind);  // closed here meanwhile
        } else if (!LoadPopupFiles(kind)) {
            std::snprintf(reply, size, "error popup files");
            return true;
        } else if (!g_taskbar.shown && g_toolbar.visible) {
            g_taskbar.shown = true;
            vr::VROverlay()->SetOverlayAlpha(g_taskbar.popup, 1.f);
            vr::VROverlay()->ShowOverlay(g_taskbar.popup);
        }
        std::snprintf(reply, size, "ok");
    } else if (std::sscanf(rest, "popup-close %31s", kind) == 1) {
        if (g_taskbar.kind == kind) ClosePopup(false);
        std::snprintf(reply, size, "ok");
    } else if (std::sscanf(rest, "tasks %d", &serial) == 1) {
        if (LoadTasks()) RefaceTaskbarButtons("task:");
        std::snprintf(reply, size, "ok %zu", g_taskbar.tasks.size());
    } else if (std::sscanf(rest, "tray volume %d %d", &a, &b) == 2) {
        g_taskbar.tasksKnown = true;
        g_taskbar.volLevel = std::clamp(a, 0, 3), g_taskbar.volPct = b;
        RefaceTaskbarButtons("popup:volume");
        std::snprintf(reply, size, "ok");
    } else if (std::sscanf(rest, "tray wifi %d %d %d", &a, &b, &c) == 3) {
        g_taskbar.wifiEnabled = a != 0, g_taskbar.wifiBars = std::clamp(b, 0, 4), g_taskbar.wifiConnected = c != 0;
        RefaceTaskbarButtons("popup:wifi");
        std::snprintf(reply, size, "ok");
    } else if (!std::strcmp(rest, "taskbar")) {
        std::snprintf(reply, size, "ok tasks=%zu known=%d popup=%s shown=%d items=%zu volume=%d/%d wifi=%d/%d/%d",
                      g_taskbar.tasks.size(), g_taskbar.tasksKnown ? 1 : 0,
                      g_taskbar.kind.empty() ? "-" : g_taskbar.kind.c_str(), g_taskbar.shown ? 1 : 0,
                      g_taskbar.items.size(), g_taskbar.volLevel, g_taskbar.volPct, g_taskbar.wifiEnabled ? 1 : 0,
                      g_taskbar.wifiBars, g_taskbar.wifiConnected ? 1 : 0);
    } else if (!std::strcmp(rest, "overlays")) {
        // Every visible Frametop overlay that takes laser input: where invisible hit area
        // comes from. key alpha width x hit height (metres, from the mouse-scale aspect
        // SteamVR intersects with) y (world).
        std::vector<vr::VROverlayHandle_t> all = {g_toolbar.backing, g_toolbar.grab, g_taskbar.popup, g_taskbar.hilite};
        for (const auto &m : g_toolbar.modules)
            for (const auto &btn : m.buttons) all.push_back(btn.o);
        for (const auto &[i, s] : g_screens)
            for (auto o : s.All()) all.push_back(o);
        int len = std::snprintf(reply, size, "ok");
        for (auto o : all) {
            if (o == vr::k_ulOverlayHandleInvalid || !vr::VROverlay()->IsOverlayVisible(o)) continue;
            vr::VROverlayInputMethod im{};
            vr::VROverlay()->GetOverlayInputMethod(o, &im);
            if (im != vr::VROverlayInputMethod_Mouse) continue;
            char key[96] = {};
            vr::EVROverlayError e{};
            vr::VROverlay()->GetOverlayKey(o, key, sizeof key, &e);
            float alpha = 0, w = 0, aspect = 0;
            vr::VROverlay()->GetOverlayAlpha(o, &alpha);
            vr::VROverlay()->GetOverlayWidthInMeters(o, &w);
            vr::HmdVector2_t ms{};
            vr::VROverlay()->GetOverlayMouseScale(o, &ms);
            if (ms.v[0] > 0) aspect = ms.v[1] / ms.v[0];
            vr::TrackingUniverseOrigin uo{};
            vr::HmdMatrix34_t m{};
            vr::VROverlay()->GetOverlayTransformAbsolute(o, &uo, &m);
            const char *k = std::strncmp(key, "frametop.", 9) ? key : key + 9;
            if (len < size)
                len += std::snprintf(reply + len, size - len, "\n%s a=%.2f %.3fx%.3f y=%.2f", k, alpha, w, w * aspect,
                                     m.m[1][3]);
        }
    } else if (std::sscanf(rest, "open %31s", kind) == 1) {
        // Same as pressing the module button (testing / scripting).
        const std::string k = kind;
        OpenPopup(k, "", k == "start" ? "popup:start" : "popup:" + k);
        std::snprintf(reply, size, "ok");
    } else {
        return false;
    }
    return true;
}
