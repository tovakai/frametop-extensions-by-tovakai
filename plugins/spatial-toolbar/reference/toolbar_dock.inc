// Screen docking — included from desktop_toolbar.inc (inside vr.cpp's anonymous namespace).
//
// Frametop-owned hierarchy: toolbar body → dock anchor (its levelled pose) → docked screens.
// Nothing here touches SteamVR's dashboard objects. SteamVR docks one panel at an exclusive
// "Dashboard" dock location and remembers a transform per location; Frametop docks several
// screens side by side in stable slots (dock order) above the bar.
//
// Docking saves the screen's whole FollowState (pose, follow mode, relative pose, rigid pin,
// dead zone) in Screen::preDock; undocking puts it back. Width, curve and opacity are never
// touched — a docked screen is only moved.
//
// Dock / undock (and slot reshuffles) ease over kDockAnimSec with the same cosine ease-in-out
// as ft-layout's profile apply (DEFAULT_PROFILE_DURATION_MS = 450).

constexpr double kDockLift = 0.025;    // toolbar top edge → the lowest screen control
constexpr double kDockSpacing = 0.05;  // between docked screens (including their chrome)
constexpr double kDockSpanRad = 1.6;   // a wider group is pushed back so it subtends this
constexpr double kDockAnimSec = 0.450; // match layout/ft_layout.py DEFAULT_PROFILE_DURATION_MS

int DockedCount() {
    int n = 0;
    for (auto &[i, s] : g_screens) n += s.docked ? 1 : 0;
    return n;
}

std::vector<Screen *> DockedInOrder() {
    std::vector<std::pair<int, int>> keys;  // (slot, index): stable left → right
    for (auto &[i, s] : g_screens)
        if (s.docked) keys.push_back({s.dockSlot, i});
    std::sort(keys.begin(), keys.end());
    std::vector<Screen *> out;
    for (auto &[slot, i] : keys) out.push_back(&g_screens[i]);
    return out;
}

// How far a screen's own controls hang below its bottom edge.
double DockClearance(const Screen &s) {
    return s.chrome * (ChromeStyle::kGapFrac + ChromeStyle::kBarHalfHFrac) + s.grip / 2;
}

// Point `u` metres along a cylinder of radius R about the viewer, the toolbar's arc pushed
// back to R (R == the toolbar curve keeps it on the bar's own arc), facing the viewer.
Mat DockArc(double u, double R) {
    const double c = g_toolbar.curve > 0.25 ? g_toolbar.curve : 1.0;
    const double a = u / R, cs = std::cos(a), sn = std::sin(a);
    Mat m = Identity();
    m.m[0][0] = float(cs), m.m[0][2] = float(-sn);
    m.m[2][0] = float(sn), m.m[2][2] = float(cs);
    m.m[0][3] = float(R * sn);
    m.m[2][3] = float(c - R * cs);
    return m;
}

bool SamePose(const Mat &a, const Mat &b) {
    for (int r = 0; r < 3; ++r)
        for (int c = 0; c < 4; ++c)
            if (std::fabs(a.m[r][c] - b.m[r][c]) > 1e-5f) return false;
    return true;
}

// Same ease as layout/ft_layout.py ease_in_out (smoothstep via cosine).
double DockEase(double t) {
    t = std::clamp(t, 0.0, 1.0);
    return 0.5 * (1.0 - std::cos(M_PI * t));
}

Mat LerpPose(const Mat &a, const Mat &b, double u) {
    const Quat q = Slerp(QuatFromMat(a), QuatFromMat(b), u);
    return MatFromQuatPos(q, a.m[0][3] + (b.m[0][3] - a.m[0][3]) * u,
                          a.m[1][3] + (b.m[1][3] - a.m[1][3]) * u,
                          a.m[2][3] + (b.m[2][3] - a.m[2][3]) * u);
}

// World pose a FollowState would show right now (rigid device → live; else stored pose).
bool FollowWorldPose(const FollowState &f, Mat *out) {
    if (f.pinned != kNone || IsRigidDevice(f.anchor)) {
        const vr::TrackedDeviceIndex_t dev =
            f.pinned != kNone ? f.pinned : DeviceForMode(f.anchor);
        Mat c;
        if (dev == kNone || !DevicePose(dev, &c)) return false;
        *out = Mul(c, f.pinRel);
        return true;
    }
    *out = f.pose;
    return true;
}

// Capture current world pose and start a dock/reshuffle fly for every docked screen.
void BeginDockedTweens() {
    const auto now = Clock::now();
    for (auto &[i, s] : g_screens) {
        if (!s.docked) continue;
        Mat p;
        if (!ScreenPose(s, &p) && !FollowPose(s, &p)) continue;
        s.dockTween = true;
        s.dockTweenUndock = false;
        s.dockTweenFrom = p;
        s.dockTweenStart = now;
    }
}

// Docked screens ride the anchor every tick (the toolbar follows / is carried; they come
// along). The group is centred on the bar; each screen keeps its own size and curve.
// While dockTween is set, ease from dockTweenFrom toward the live slot target (moving end).
void PlaceDockedScreens(const Mat &anchor) {
    const auto docked = DockedInOrder();
    if (docked.empty()) return;
    double total = 0;
    for (size_t k = 0; k < docked.size(); ++k) total += docked[k]->metres + (k ? kDockSpacing : 0);
    const double c = g_toolbar.curve > 0.25 ? g_toolbar.curve : 1.0;
    const double R = std::max(c, total / kDockSpanRad);
    double u = -total / 2;
    const double top = TS(ToolbarStyle::kBarH) / 2 + kDockLift;
    const auto now = Clock::now();
    for (Screen *s : docked) {
        const double w = s->metres;
        const double lift = top + DockClearance(*s) + s->heightMetres() / 2;
        const Mat target = Mul(Mul(anchor, DockArc(u + w / 2, R)), Translation(0, lift, 0));
        u += w + kDockSpacing;
        if (s->drag != Drag::None) continue;
        Mat pose = target;
        if (s->dockTween) {
            const double elapsed = std::chrono::duration<double>(now - s->dockTweenStart).count();
            if (elapsed >= kDockAnimSec) {
                s->dockTween = false;
                s->dockTweenUndock = false;
            } else {
                pose = LerpPose(s->dockTweenFrom, target, DockEase(elapsed / kDockAnimSec));
            }
        } else if (s->anchor == AnchorMode::World && s->pinned == kNone && SamePose(s->pose, target)) {
            continue;
        }
        SetWorldPose(*s, pose);
        ApplyScreenTransform(*s);
    }
}

// Finish undock flies (world → preDock). Called with PlaceDockedScreens so both sides of
// a toggle keep the same clock.
void TickUndockTweens() {
    const auto now = Clock::now();
    for (auto &[i, s] : g_screens) {
        if (!s.dockTween || !s.dockTweenUndock || s.docked) continue;
        if (s.drag != Drag::None) continue;
        const double elapsed = std::chrono::duration<double>(now - s.dockTweenStart).count();
        if (elapsed >= kDockAnimSec) {
            s.dockTween = false;
            s.dockTweenUndock = false;
            // Same restore as the old instant undock, but land on the eased end pose.
            static_cast<FollowState &>(s) = s.dockTweenRestore;
            if (s.pinned != kNone || IsRigidDevice(s.anchor)) {
                if (!ApplyFollowMode(s, s.anchor, s.dockTweenRestore.pinRel))
                    SetWorldPose(s, s.dockTweenTo);
            } else {
                s.pose = s.dockTweenTo;
                s.pinned = kNone;
            }
            ApplyScreenTransform(s);
            continue;
        }
        SetWorldPose(s, LerpPose(s.dockTweenFrom, s.dockTweenTo, DockEase(elapsed / kDockAnimSec)));
        ApplyScreenTransform(s);
    }
}

int NextDockSlot() {
    int slot = 0;
    for (auto &[i, s] : g_screens)
        if (s.docked) slot = std::max(slot, s.dockSlot + 1);
    return slot;
}

bool DockScreen(int index, int slot = -1) {
    auto it = g_screens.find(index);
    if (it == g_screens.end() || !g_toolbar.enabled) return false;
    Screen &s = it->second;
    if (s.docked) {
        if (slot >= 0 && slot != s.dockSlot) {
            s.dockSlot = slot;
            BeginDockedTweens();
            Mat anchor;
            if (ToolbarAnchor(&anchor)) PlaceDockedScreens(anchor);
        }
        return true;
    }
    EndDrag(s);
    s.preDock = static_cast<const FollowState &>(s);
    // A rigid pin's room pose is only known through the device; keep it for a fallback.
    Mat now = s.pose;
    if (FollowPose(s, &now)) s.preDock.pose = now;
    s.docked = true;
    s.dockSlot = slot >= 0 ? slot : NextDockSlot();
    s.dockTweenUndock = false;
    SetWorldPose(s, now);  // the dock anchor owns the pose from here
    BeginDockedTweens();   // this screen + any already docked (slot reshuffle)
    RefreshSlotTextures(s);
    Mat anchor;
    if (ToolbarAnchor(&anchor)) PlaceDockedScreens(anchor);
    std::printf("screen %d: docked (slot %d)\n", index + 1, s.dockSlot);
    return true;
}

bool UndockScreen(int index) {
    auto it = g_screens.find(index);
    if (it == g_screens.end() || !it->second.docked) return false;
    Screen &s = it->second;
    EndDrag(s);
    Mat from = s.pose;
    ScreenPose(s, &from);
    Mat to = s.preDock.pose;
    if (!FollowWorldPose(s.preDock, &to)) to = s.preDock.pose;
    s.dockTweenRestore = s.preDock;
    s.docked = false;
    s.dockTween = true;
    s.dockTweenUndock = true;
    s.dockTweenFrom = from;
    s.dockTweenTo = to;
    s.dockTweenStart = Clock::now();
    SetWorldPose(s, from);  // world body for the fly; FollowState restored at the end
    BeginDockedTweens();    // remaining docked screens ease into the new layout
    RefreshSlotTextures(s);
    TickUndockTweens();
    Mat anchor;
    if (ToolbarAnchor(&anchor)) PlaceDockedScreens(anchor);
    std::printf("screen %d: undocking → %s\n", index + 1, AnchorModeName(s.dockTweenRestore.anchor));
    return true;
}

void ToggleScreenDock(int index) {
    auto it = g_screens.find(index);
    if (it == g_screens.end()) return;
    const bool done = it->second.docked ? UndockScreen(index) : DockScreen(index);
    if (done) SpawnLayoutAsync({"dock", "sync"});
}

void UndockAllScreens() {
    for (auto &[i, s] : g_screens)
        if (s.docked) UndockScreen(i);
}

// "dock N on [slot]" | "dock N off" | "dock N toggle" | "dock state"
void DockCommand(const char *rest, char *reply, int size) {
    int n = 0, slot = -1;
    char word[16] = {};
    if (!std::strcmp(rest, "state")) {
        int len = std::snprintf(reply, size, "ok %d", DockedCount());
        for (Screen *s : DockedInOrder()) {
            int index = -1;
            for (auto &[i, t] : g_screens)
                if (&t == s) index = i;
            if (len < size) len += std::snprintf(reply + len, size - len, " %d:%d", index + 1, s->dockSlot);
        }
        return;
    }
    if (std::sscanf(rest, "%d %15s %d", &n, word, &slot) < 2)
        return (void)std::snprintf(reply, size, "error dock N on [slot]|off|toggle, or dock state");
    if (!Find(n)) return (void)std::snprintf(reply, size, "error no screen %d", n);
    bool done = false;
    if (!std::strcmp(word, "on")) {
        if (!g_toolbar.enabled) return (void)std::snprintf(reply, size, "error toolbar is disabled");
        done = DockScreen(n - 1, slot);
    } else if (!std::strcmp(word, "off")) {
        done = UndockScreen(n - 1) || !Find(n)->docked;
    } else if (!std::strcmp(word, "toggle")) {
        ToggleScreenDock(n - 1);
        done = true;
    } else {
        return (void)std::snprintf(reply, size, "error dock N on [slot]|off|toggle");
    }
    // Undock starts the fly with docked=false immediately.
    std::snprintf(reply, size, done ? "ok %s" : "error dock %s failed",
                  Find(n)->docked ? "docked" : "undocked");
}
