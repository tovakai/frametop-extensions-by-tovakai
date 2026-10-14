// Shared spatial behaviour — included inside vr.cpp's anonymous namespace, after the
// AnchorMode helpers and the eye-gaze globals, before the first surface type.
//
// Every Frametop surface (screens, Spatial Instruments, the toolbar) is a body with the
// same three behaviours, so they cannot drift apart:
//   FollowState     world / rigid device pin / soft head, yaw or position follow + dead zone
//   AttentionState  idle ↔ active opacity driven by true eye gaze (dwell, hold, fades)
//   MoveDrag        carried on a controller by its move bar; follow mode restored on release
// Surfaces inherit these (Screen : FollowState, ...), so field names are shared too.

struct FollowState {
    AnchorMode anchor = AnchorMode::World;
    vr::TrackedDeviceIndex_t pinned = kNone;  // rigid tracked-device pin only
    Mat pinRel = Identity();                  // reference/device -> body
    Mat pose = Identity();                    // room pose (smoothed for soft follow)
    // Soft-follow dead zone: small head motion keeps a locked reference so you can glance
    // at a corner without the body chasing. Past the threshold the lock is pushed (excess
    // only), so intentional turns still follow.
    bool followDeadzone = false;
    double followDeadzoneDeg = 15;  // head / yaw-follow
    double followDeadzoneM = 0.15;  // position-follow (+ head translation)
    bool followLockValid = false;
    Mat followLock = Identity();    // last soft-follow reference frame
};

struct AttentionState {
    // Final alpha = attentionResolved * the surface's visibility fade.
    float activeOpacity = 1.f;
    float idleOpacity = 1.f;
    float attentionResolved = 1.f;  // smoothed idle ↔ active
    bool attentionEnabled = false;
    double attentionInMs = 150;     // fade toward active
    double attentionOutMs = 250;    // fade toward idle
    double attentionDwellMs = 80;   // gaze must stick before activating
    double attentionHoldMs = 400;   // stay active briefly after gaze leaves / sample drop
    double attentionFocusMs = 0;    // time currently focused / unfocused accumulator
    bool attentionFocused = false;
};

struct MoveDrag {
    Drag drag = Drag::None;
    vr::TrackedDeviceIndex_t dragDevice = kNone;
    Mat dragRel = Identity();                    // device -> body, while moving
    AnchorMode dragRestore = AnchorMode::World;  // soft follow reapplied after a move
};

// ---------------------------------------------------------------- follow

bool FollowPose(const FollowState &f, Mat *out) {
    if (f.pinned != kNone) {
        Mat d;
        if (!DevicePose(f.pinned, &d)) return false;
        *out = Mul(d, f.pinRel);
        return true;
    }
    // Our own copy: reading it back from SteamVR right after setting it could return the
    // old pose.
    *out = f.pose;
    return true;
}

void SetWorldPose(FollowState &f, const Mat &pose) {
    f.anchor = AnchorMode::World;
    f.pinned = kNone;
    f.pose = pose;
}

// Switch to `mode` with `rel` (reference/device -> body). The smoothed pose is seeded from
// what is shown now so a mode change never pops. False: the rigid device has no pose (the
// mode and rel are kept, as before, so a later pin can complete).
bool ApplyFollowMode(FollowState &f, AnchorMode mode, const Mat &rel) {
    Mat seed;
    const bool haveSeed = FollowPose(f, &seed);
    f.anchor = mode;
    f.pinRel = rel;
    if (IsRigidDevice(mode)) {
        const vr::TrackedDeviceIndex_t dev = DeviceForMode(mode);
        Mat c;
        if (dev == kNone || !DevicePose(dev, &c)) return false;
        f.pinned = dev;
        return true;
    }
    f.pinned = kNone;
    Mat hmd;
    const bool haveHmd = DevicePose(vr::k_unTrackedDeviceIndex_Hmd, &hmd);
    f.pose = haveSeed ? seed : Mul(ReferenceFrame(mode, haveHmd ? hmd : Identity()), rel);
    // Seed the dead-zone lock to the current reference so a fresh pin doesn't jump.
    f.followLockValid = haveHmd;
    if (haveHmd) f.followLock = ReferenceFrame(mode, hmd);
    return true;
}

// Change mode keeping the body exactly where it is now.
bool RepinInPlace(FollowState &f, AnchorMode mode) {
    Mat p;
    if (!FollowPose(f, &p)) return false;
    if (mode == AnchorMode::World) {
        SetWorldPose(f, p);
        return true;
    }
    if (IsRigidDevice(mode)) {
        const vr::TrackedDeviceIndex_t dev = DeviceForMode(mode);
        Mat c;
        if (dev == kNone || !DevicePose(dev, &c)) return false;
        return ApplyFollowMode(f, mode, Mul(Inverse(c), p));
    }
    Mat hmd;
    if (!DevicePose(vr::k_unTrackedDeviceIndex_Hmd, &hmd)) return false;
    return ApplyFollowMode(f, mode, Mul(Inverse(ReferenceFrame(mode, hmd)), p));
}

void SetFollowDeadzone(FollowState &f, bool on, double deg, double metres) {
    f.followDeadzone = on;
    if (!on) {
        f.followLockValid = false;
        return;
    }
    f.followDeadzoneDeg = std::clamp(deg, 1.0, 90.0);
    f.followDeadzoneM = std::clamp(metres, 0.02, 1.0);
    // Re-seed from the current head so enabling doesn't yank the body.
    Mat hmd;
    f.followLockValid = IsSoftFollow(f.anchor) && DevicePose(vr::k_unTrackedDeviceIndex_Hmd, &hmd);
    if (f.followLockValid) f.followLock = ReferenceFrame(f.anchor, hmd);
}

// One soft-follow step toward the head. `gazeFocused`: eye attention is on this body — a
// head-soft body then freezes so reading does not pitch/slide it under your eyes (yaw and
// position follow keep moving; freezing those felt like path stutter when eye samples
// flickered). True when `pose` moved.
bool StepSoftFollow(FollowState &f, const Mat &hmd, double dt, double tauSec, bool gazeFocused) {
    if (!IsSoftFollow(f.anchor)) return false;
    const Mat cur = ReferenceFrame(f.anchor, hmd);
    if (gazeFocused && f.anchor == AnchorMode::HeadSoft) {
        if (f.followDeadzone) {
            f.followLock = cur;
            f.followLockValid = true;
        }
        return false;
    }
    Mat ref = cur;
    // Position-follow always gets a tiny dead zone so millimetre HMD noise does not jitter a
    // still sitter. A user dead zone (if any) is at least this large.
    const double posFloorM = 0.025;
    if (f.followDeadzone || f.anchor == AnchorMode::PositionFollow) {
        if (!f.followLockValid) {
            f.followLock = cur;
            f.followLockValid = true;
        }
        const double zoneDeg = f.followDeadzone ? f.followDeadzoneDeg : 15.0;
        const double zoneM = f.followDeadzone ? std::max(f.followDeadzoneM, posFloorM) : posFloorM;
        PushFollowLock(&f.followLock, cur, f.anchor, zoneDeg, zoneM);
        ref = f.followLock;
    } else {
        f.followLockValid = false;
    }
    SmoothToward(&f.pose, Mul(ref, f.pinRel), dt, tauSec);
    return true;
}

// ---------------------------------------------------------------- attention

void SetAttentionOpacity(AttentionState &a, float active, float idle) {
    a.activeOpacity = std::clamp(active, 0.f, 1.f);
    a.idleOpacity = std::clamp(idle, 0.f, 1.f);
    // Looking must never be dimmer than looking away (swapped sliders caused "look → vanish").
    if (a.idleOpacity > a.activeOpacity) std::swap(a.idleOpacity, a.activeOpacity);
    if (!a.attentionEnabled || (!g_eyeAvailable && !g_gazeFallbackHead))
        a.attentionResolved = a.activeOpacity;
    else
        a.attentionResolved = std::clamp(a.attentionResolved, a.idleOpacity, a.activeOpacity);
}

// attention on [inMs [outMs [dwellMs [holdMs]]]]; negative = keep.
void SetAttentionTiming(AttentionState &a, bool on, double inMs, double outMs, double dwellMs, double holdMs) {
    a.attentionEnabled = on;
    if (!on) {
        a.attentionFocused = false;
        a.attentionResolved = a.activeOpacity;
        return;
    }
    if (inMs >= 0) a.attentionInMs = std::clamp(inMs, 20.0, 2000.0);
    if (outMs >= 0) a.attentionOutMs = std::clamp(outMs, 20.0, 2000.0);
    if (dwellMs >= 0) a.attentionDwellMs = std::clamp(dwellMs, 0.0, 1000.0);
    if (holdMs >= 0) a.attentionHoldMs = std::clamp(holdMs, 0.0, 1000.0);
}

// Control-socket argument forms shared by screens, instruments and the toolbar:
//   attention: "on [inMs [outMs [dwellMs [holdMs]]]]" | "off"
//   deadzone:  "on [degrees [metres]]" | "off"
bool ParseAttentionArgs(AttentionState &a, const char *args) {
    char word[16] = {};
    double v[4] = {-1, -1, -1, -1};
    const int got = std::sscanf(args, "%15s %lf %lf %lf %lf", word, &v[0], &v[1], &v[2], &v[3]);
    if (got < 1) return false;
    if (!std::strcmp(word, "off")) SetAttentionTiming(a, false, -1, -1, -1, -1);
    else if (!std::strcmp(word, "on")) SetAttentionTiming(a, true, v[0], v[1], v[2], v[3]);
    else return false;
    return true;
}

bool ParseDeadzoneArgs(FollowState &f, const char *args) {
    char word[16] = {};
    double deg = f.followDeadzoneDeg, metres = f.followDeadzoneM;
    if (std::sscanf(args, "%15s %lf %lf", word, &deg, &metres) < 1) return false;
    if (!std::strcmp(word, "off")) SetFollowDeadzone(f, false, deg, metres);
    else if (!std::strcmp(word, "on")) SetFollowDeadzone(f, true, deg, metres);
    else return false;
    return true;
}

// One attention step. `hit`: true eye gaze is on the body (or its chrome / popups). An
// interaction (`awake`, e.g. a laser on it) also counts as attention. True when the
// resolved opacity changed enough to re-upload alpha.
bool StepAttention(AttentionState &a, bool hit, double dt, bool awake = false) {
    const float before = a.attentionResolved;
    if (!a.attentionEnabled) {
        a.attentionFocused = false;
        a.attentionFocusMs = 0;
        a.attentionResolved = a.activeOpacity;  // no attention: active opacity (legacy)
    } else if (!g_eyeAvailable && !g_gazeFallbackHead && !awake) {
        // Eye tracking has never delivered a sample: do not park the body at idle (that
        // soft-locks settings UIs when idle is 0). Hold active until gaze works.
        a.attentionFocused = false;
        a.attentionFocusMs = 0;
        a.attentionResolved = a.activeOpacity;
    } else {
        // Fresh sample, sticky held ray, or explicit head fallback all count as valid.
        const bool valid = g_eyeValid || g_eyeHeld || (g_gazeFallbackHead && g_gazeTarget) || awake;
        const bool on = hit || awake;
        if (!valid) {
            // Truly lost tracking: keep focused through the hold, then ease idle. Do not
            // slam toward idle on every brief OpenVR dropout.
            if (a.attentionFocused) {
                a.attentionFocusMs += dt * 1000.0;
                if (a.attentionFocusMs >= a.attentionHoldMs) {
                    a.attentionFocused = false;
                    a.attentionFocusMs = 0;
                }
            }
        } else if (on) {
            a.attentionFocusMs += dt * 1000.0;
            if (awake || (!a.attentionFocused && a.attentionFocusMs >= a.attentionDwellMs)) a.attentionFocused = true;
            if (a.attentionFocused) a.attentionFocusMs = 0;  // reset hold while still gazing
        } else if (a.attentionFocused) {
            a.attentionFocusMs += dt * 1000.0;
            if (a.attentionFocusMs >= a.attentionHoldMs) {
                a.attentionFocused = false;
                a.attentionFocusMs = 0;
            }
        } else {
            a.attentionFocusMs = 0;
        }
        const float target = a.attentionFocused ? a.activeOpacity : a.idleOpacity;
        const double tau = (a.attentionFocused ? a.attentionInMs : a.attentionOutMs) / 1000.0;
        const double k = tau <= 1e-4 ? 1.0 : 1.0 - std::exp(-dt / tau);
        a.attentionResolved = float(a.attentionResolved + (target - a.attentionResolved) * k);
    }
    return std::fabs(a.attentionResolved - before) > 0.001f;
}

// ---------------------------------------------------------------- move drag

// Grab: the body rides the device from here. A rigid pin is let go (the body is carried
// freely) and the follow mode is remembered so release can reapply it.
bool BeginMoveDrag(FollowState &f, MoveDrag &d, vr::TrackedDeviceIndex_t dev) {
    Mat c, p;
    if (dev == kNone || !DevicePose(dev, &c) || !FollowPose(f, &p)) return false;
    d.dragRestore = f.anchor;
    if (f.pinned != kNone) {
        f.pinned = kNone;
        f.pose = p;
    }
    d.drag = Drag::Move;
    d.dragDevice = dev;
    d.dragRel = Mul(Inverse(c), p);
    return true;
}

bool MoveDragPose(const MoveDrag &d, Mat *out) {
    Mat c;
    if (d.drag != Drag::Move || !DevicePose(d.dragDevice, &c)) return false;
    *out = Mul(c, d.dragRel);
    return true;
}

// Scroll while moving: push away (up) or pull closer along the line from the head.
void PushMoveDrag(MoveDrag &d, double notches) {
    Mat c, head;
    if (!DevicePose(d.dragDevice, &c) || !DevicePose(vr::k_unTrackedDeviceIndex_Hmd, &head)) return;
    Mat p = Mul(c, d.dragRel);
    const double to[3] = {p.m[0][3] - head.m[0][3], p.m[1][3] - head.m[1][3], p.m[2][3] - head.m[2][3]};
    const double len = std::sqrt(Dot3(to, to));
    const double next = std::clamp(len * (1 + 0.08 * notches), 0.3, 10.0);
    for (int k = 0; k < 3; ++k) p.m[k][3] = float(head.m[k][3] + to[k] / (len + 1e-9) * next);
    d.dragRel = Mul(Inverse(c), p);
}

// Let go: soft follow modes re-attach relative to where the body was dropped (so a
// follow-mode body keeps following after a move). Returns whether it had been moving.
bool EndMoveDrag(FollowState &f, MoveDrag &d) {
    const bool moved = d.drag == Drag::Move;
    const AnchorMode restore = d.dragRestore;
    d.drag = Drag::None;
    d.dragDevice = kNone;
    d.dragRestore = AnchorMode::World;
    if (moved && IsSoftFollow(restore)) RepinInPlace(f, restore);
    return moved;
}
