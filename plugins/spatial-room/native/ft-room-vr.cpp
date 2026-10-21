// ft-room-vr: standalone OpenVR overlay frontend for Spatial Room.
// No compositor hooks, root privileges, Steam config writes or auto-install.
// stdin: "clear", "segment ax ay az bx by bz color", "commit", "hud TEXT", "quit".
// stdout: "ready <universe>", "aim <ox oy oz dx dy dz>", "place ...",
//         "mode", "confirm", "undo", "label", "height", "rotate", "save".
// Wireframes are world-space overlay ribbons, not actual 3D meshes.
#include <openvr.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <map>
#include <string>
#include <thread>
#include <unistd.h>
#include <vector>

namespace {
using Vec = std::array<double, 3>;
using Matrix = vr::HmdMatrix34_t;
using Clock = std::chrono::steady_clock;
constexpr int kMaxSegments = 240;
std::atomic<bool> stop{false};
void Signal(int) { stop = true; }

Vec add(Vec a, Vec b) { return {a[0]+b[0], a[1]+b[1], a[2]+b[2]}; }
Vec sub(Vec a, Vec b) { return {a[0]-b[0], a[1]-b[1], a[2]-b[2]}; }
Vec mul(Vec a, double v) { return {a[0]*v,a[1]*v,a[2]*v}; }
double dot(Vec a, Vec b) { return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]; }
Vec cross(Vec a, Vec b) { return {a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]}; }
double norm(Vec a) { return std::sqrt(dot(a,a)); }
Vec unit(Vec a) { const double n=norm(a); return n > 1e-9 ? mul(a,1/n) : Vec{0,1,0}; }
Vec origin(const Matrix& m) { return {m.m[0][3],m.m[1][3],m.m[2][3]}; }
Matrix multiply(const Matrix& a, const Matrix& b) {
    Matrix r{};
    for(int i=0;i<3;++i) for(int j=0;j<4;++j) {
        double v=j==3?a.m[i][3]:0;
        for(int k=0;k<3;++k) v+=a.m[i][k]*b.m[k][j];
        r.m[i][j]=float(v);
    }
    return r;
}
Matrix identity() { Matrix m{}; for(int i=0;i<3;++i)m.m[i][i]=1; return m; }

// The Frame controller's tip angles roughly 40 degrees below its tracked pose -Z.
// Fetch SteamVR's render-model component offset instead of guessing the laser ray.
Matrix tip_offset(vr::TrackedDeviceIndex_t device) {
    Matrix t=identity();
    char model[256]={};
    auto* sys=vr::VRSystem();
    sys->GetStringTrackedDeviceProperty(device,vr::Prop_RenderModelName_String,model,sizeof model);
    vr::RenderModel_ControllerMode_State_t mode{};
    vr::RenderModel_ComponentState_t part{};
    vr::VRControllerState_t buttons{};
    if(model[0] && vr::VRRenderModels()->GetComponentState(
        model,vr::k_pch_Controller_Component_Tip,&buttons,&mode,&part))
        t=part.mTrackingToComponentLocal;
    return t;
}
struct Ray { Vec o{}, dir{}; bool valid=false; };
Ray controller_ray() {
    auto* sys=vr::VRSystem();
    const auto device=sys->GetTrackedDeviceIndexForControllerRole(vr::TrackedControllerRole_RightHand);
    if(device==vr::k_unTrackedDeviceIndexInvalid) return {};
    vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
    sys->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,poses,vr::k_unMaxTrackedDeviceCount);
    if(!poses[device].bPoseIsValid || !poses[device].bDeviceIsConnected) return {};
    Matrix m=multiply(poses[device].mDeviceToAbsoluteTracking,tip_offset(device));
    return {origin(m),unit({-m.m[0][2],-m.m[1][2],-m.m[2][2]}),true};
}
Vec head_position() {
    vr::TrackedDevicePose_t poses[vr::k_unMaxTrackedDeviceCount]{};
    vr::VRSystem()->GetDeviceToAbsoluteTrackingPose(vr::TrackingUniverseStanding,0,poses,vr::k_unMaxTrackedDeviceCount);
    return poses[vr::k_unTrackedDeviceIndex_Hmd].bPoseIsValid ?
        origin(poses[vr::k_unTrackedDeviceIndex_Hmd].mDeviceToAbsoluteTracking) : Vec{0,1.6,0};
}

struct Segment {Vec a,b;int color=0;};
std::vector<Segment> pending, segments;
const std::array<std::array<float,3>,4> colors{{
    {{0.22f,0.85f,1.f}},{{1.f,0.65f,0.25f}},{{0.45f,1.f,0.48f}},{{1.f,0.35f,0.5f}}
}};
std::vector<vr::VROverlayHandle_t> ribbons;
vr::VROverlayHandle_t hud=vr::k_ulOverlayHandleInvalid;
vr::IVROverlay* overlay=nullptr;
const std::vector<unsigned char> ribbonPixels(size_t(256*2*4),255);

Matrix ribbon_pose(Vec a, Vec b, Vec camera) {
    const Vec mid=mul(add(a,b),0.5);
    const Vec x=unit(sub(b,a));
    Vec z=sub(sub(camera,mid),mul(x,dot(sub(camera,mid),x)));
    if(norm(z)<1e-5) z=cross(x,Vec{0,1,0});
    if(norm(z)<1e-5) z=cross(x,Vec{1,0,0});
    z=unit(z);
    const Vec y=unit(cross(z,x));
    Matrix m{};
    for(int i=0;i<3;++i) {
        m.m[i][0]=float(x[i]);m.m[i][1]=float(y[i]);m.m[i][2]=float(z[i]);m.m[i][3]=float(mid[i]);
    }
    return m;
}
bool make_ribbon(size_t i) {
    if(i>=kMaxSegments) return false;
    while(ribbons.size()<=i) {
        vr::VROverlayHandle_t h=vr::k_ulOverlayHandleInvalid;
        const std::string key="tovakai.spatial-room.edge."+std::to_string(ribbons.size());
        if(overlay->CreateOverlay(key.c_str(),"Spatial Room wire", &h)!=vr::VROverlayError_None) return false;
        overlay->SetOverlayRaw(h,const_cast<unsigned char*>(ribbonPixels.data()),256,2,4);
        overlay->SetOverlayAlpha(h,0.85f);
        ribbons.push_back(h);
    }
    return true;
}
bool visible=false;
void show_geometry(bool enabled) {
    if(!enabled) {
        if(visible) for(auto h:ribbons) overlay->HideOverlay(h);
        visible=false;
        return;
    }
    visible=true;
    const Vec camera=head_position();
    for(size_t i=0;i<ribbons.size();++i) {
        const auto h=ribbons[i];
        if(i>=segments.size() || i>=kMaxSegments) {overlay->HideOverlay(h);continue;}
        const auto& s=segments[i];
        const double len=norm(sub(s.b,s.a));
        if(len<0.001 || len>100) {overlay->HideOverlay(h);continue;}
        const Matrix pose=ribbon_pose(s.a,s.b,camera);
        overlay->SetOverlayTransformAbsolute(h,vr::TrackingUniverseStanding,&pose);
        overlay->SetOverlayWidthInMeters(h,float(len));
        const auto& c=colors[size_t(std::clamp(s.color,0,3))];
        overlay->SetOverlayColor(h,c[0],c[1],c[2]);
        overlay->ShowOverlay(h);
    }
}

// Minimal 5x7 uppercase font: no external font files or changes to system.
using Glyph = std::array<const char*,7>;
const std::map<char,Glyph> font={
{'A',{" ### ","#   #","#   #","#####","#   #","#   #","#   #"}},
{'B',{"#### ","#   #","#   #","#### ","#   #","#   #","#### "}},
{'C',{" ####","#    ","#    ","#    ","#    ","#    "," ####"}},
{'D',{"#### ","#   #","#   #","#   #","#   #","#   #","#### "}},
{'E',{"#####","#    ","#    ","#### ","#    ","#    ","#####"}},
{'F',{"#####","#    ","#    ","#### ","#    ","#    ","#    "}},
{'G',{" ####","#    ","#    ","# ###","#   #","#   #"," ####"}},
{'H',{"#   #","#   #","#   #","#####","#   #","#   #","#   #"}},
{'I',{"#####","  #  ","  #  ","  #  ","  #  ","  #  ","#####"}},
{'J',{"#####","    #","    #","    #","#   #","#   #"," ### "}},
{'K',{"#   #","#  # ","# #  ","##   ","# #  ","#  # ","#   #"}},
{'L',{"#    ","#    ","#    ","#    ","#    ","#    ","#####"}},
{'M',{"#   #","## ##","# # #","#   #","#   #","#   #","#   #"}},
{'N',{"#   #","##  #","# # #","#  ##","#   #","#   #","#   #"}},
{'O',{" ### ","#   #","#   #","#   #","#   #","#   #"," ### "}},
{'P',{"#### ","#   #","#   #","#### ","#    ","#    ","#    "}},
{'Q',{" ### ","#   #","#   #","#   #","# # #","#  # "," ## #"}},
{'R',{"#### ","#   #","#   #","#### ","# #  ","#  # ","#   #"}},
{'S',{" ####","#    ","#    "," ### ","    #","    #","#### "}},
{'T',{"#####","  #  ","  #  ","  #  ","  #  ","  #  ","  #  "}},
{'U',{"#   #","#   #","#   #","#   #","#   #","#   #"," ### "}},
{'V',{"#   #","#   #","#   #","#   #","#   #"," # # ","  #  "}},
{'W',{"#   #","#   #","#   #","# # #","# # #","## ##","#   #"}},
{'X',{"#   #","#   #"," # # ","  #  "," # # ","#   #","#   #"}},
{'Y',{"#   #","#   #"," # # ","  #  ","  #  ","  #  ","  #  "}},
{'Z',{"#####","    #","   # ","  #  "," #   ","#    ","#####"}},
{'0',{" ### ","#   #","#  ##","# # #","##  #","#   #"," ### "}},
{'1',{"  #  "," ##  ","  #  ","  #  ","  #  ","  #  ","#####"}},
{'2',{" ### ","#   #","    #","  ## "," #   ","#    ","#####"}},
{'3',{"#### ","    #","    #"," ### ","    #","    #","#### "}},
{'4',{"   # ","  ## "," # # ","#  # ","#####","   # ","   # "}},
{'5',{"#####","#    ","#    ","#### ","    #","    #","#### "}},
{'6',{" ### ","#    ","#    ","#### ","#   #","#   #"," ### "}},
{'7',{"#####","    #","   # ","  #  "," #   "," #   "," #   "}},
{'8',{" ### ","#   #","#   #"," ### ","#   #","#   #"," ### "}},
{'9',{" ### ","#   #","#   #"," ####","    #","    #"," ### "}},
{':',{"     ","  #  ","     ","     ","  #  ","     ","     "}},
{'-',{"     ","     ","     ","#####","     ","     ","     "}},
{'.',{"     ","     ","     ","     ","     "," ##  "," ##  "}},
{'/',{"    #","    #","   # ","  #  "," #   ","#    ","#    "}},
{'?',{" ### ","#   #","    #","  ## ","  #  ","     ","  #  "}}
};
constexpr int hudW=640,hudH=144;
std::string hudText="STARTING";
bool hudDirty=true;
void draw_hud() {
    if(hud==vr::k_ulOverlayHandleInvalid || !hudDirty) return;
    hudDirty=false;
    std::vector<unsigned char> px(size_t(hudW*hudH*4),0);
    for(int y=0;y<hudH;++y) for(int x=0;x<hudW;++x) {
        const size_t off=size_t(y*hudW+x)*4;
        px[off]=12;px[off+1]=22;px[off+2]=30;px[off+3]=180;
    }
    const std::array<std::string,4> lines={
        "SPATIAL ROOM",hudText.substr(0,56),
        "TRIGGER PLACE  GRIP MODE  A CONFIRM  B UNDO",
        "BUMPER LABEL  Y HEIGHT  STICK ROTATE  X SAVE"
    };
    for(size_t ln=0;ln<lines.size();++ln) {
        int x=15,y=9+int(ln)*34;
        for(char cc:lines[ln]) {
            const char c=(cc>='a'&&cc<='z')?char(cc-'a'+'A'):cc;
            const auto it=font.find(c);
            if(it!=font.end()) for(int gy=0;gy<7;++gy) for(int gx=0;gx<5;++gx)
                if(it->second[gy][gx]=='#') for(int yy=0;yy<2;++yy) for(int xx=0;xx<2;++xx) {
                    int pxX=x+gx*2+xx,pxY=y+gy*2+yy;
                    if(pxX<0||pxX>=hudW||pxY<0||pxY>=hudH)continue;
                    size_t off=size_t(pxY*hudW+pxX)*4;
                    px[off]=210;px[off+1]=236;px[off+2]=250;px[off+3]=255;
                }
            x+=12;
            if(x>hudW-15)break;
        }
    }
    // A small HUD; raw upload happens only when its text changes.
    overlay->SetOverlayRaw(hud,px.data(),hudW,hudH,4);
}
bool initialize_hud() {
    if(overlay->CreateOverlay("tovakai.spatial-room.hud","Spatial Room controls",&hud)!=vr::VROverlayError_None)
        return false;
    Matrix pose=identity();pose.m[1][3]=-0.27f;pose.m[2][3]=-1.15f;
    overlay->SetOverlayTransformTrackedDeviceRelative(hud,vr::k_unTrackedDeviceIndex_Hmd,&pose);
    overlay->SetOverlayWidthInMeters(hud,0.95f);
    overlay->SetOverlayAlpha(hud,0.92f);
    draw_hud();
    overlay->ShowOverlay(hud);
    return true;
}

const std::array<const char*,8> actions={"place","mode","confirm","undo","label","height","rotate","save"};
struct Buttons {
    vr::IVRInput* input=nullptr;
    vr::VRActionSetHandle_t set=0;
    std::array<vr::VRActionHandle_t,8> handle{};
    std::array<bool,8> down{};
    bool ok=false, warned=false;
    bool init(const char* manifest) {
        input=vr::VRInput();
        if(input->SetActionManifestPath(manifest)!=vr::VRInputError_None)return false;
        if(input->GetActionSetHandle("/actions/room",&set)!=vr::VRInputError_None)return false;
        for(size_t i=0;i<actions.size();++i) {
            const std::string name=std::string("/actions/room/in/")+actions[i];
            if(input->GetActionHandle(name.c_str(),&handle[i])!=vr::VRInputError_None)return false;
        }
        return ok=true;
    }
    void poll(bool sceneRunning) {
        if(!ok) return;
        vr::VRActiveActionSet_t active{};
        active.ulActionSet=set;
        active.nPriority=vr::k_nActionSetOverlayGlobalPriorityMin+0x120;
        bool updated=!sceneRunning && input->UpdateActionState(&active,sizeof active,1)==vr::VRInputError_None;
        bool any=false;
        for(size_t i=0;i<actions.size();++i) {
            bool pressed=false;
            if(updated) {
                vr::InputDigitalActionData_t d{};
                if(input->GetDigitalActionData(handle[i],&d,sizeof d,vr::k_ulInvalidInputValueHandle)==vr::VRInputError_None) {
                    pressed=d.bActive&&d.bState;
                    any|=d.bActive;
                }
            }
            if(pressed&&!down[i]) {
                if(i==0) {
                    Ray r=controller_ray();
                    if(r.valid) std::printf("place %.6f %.6f %.6f %.6f %.6f %.6f\n",
                            r.o[0],r.o[1],r.o[2],r.dir[0],r.dir[1],r.dir[2]);
                } else std::printf("%s\n",actions[i]);
                std::fflush(stdout);
            }
            down[i]=pressed;
        }
        if(!any && !sceneRunning && !warned) {
            warned=true;
            std::fprintf(stderr,"ft-room-vr: no active SteamVR input action. Enable global input from overlays if needed.\n");
        }
    }
};

bool parse_segment(const char* str,Segment &seg) {
    double a[6]={};int color=0;char extra=0;
    // Ensure exact grammar and finite, bounded coordinates; do not pass arbitrary data to OpenVR.
    if(std::sscanf(str,"segment %lf %lf %lf %lf %lf %lf %d %c",
         &a[0],&a[1],&a[2],&a[3],&a[4],&a[5],&color,&extra)!=7)return false;
    for(double v:a) if(!std::isfinite(v)||std::abs(v)>100)return false;
    if(color<0||color>3)return false;
    seg.a={a[0],a[1],a[2]};seg.b={a[3],a[4],a[5]};seg.color=color;
    return true;
}
bool reading=true,layoutDirty=false;
std::string incoming;
void command(std::string line) {
    if(line=="clear") pending.clear();
    else if(line=="commit") {
        segments=pending;
        layoutDirty=true;
    } else if(line.rfind("segment ",0)==0) {
        Segment seg;
        if(pending.size()<kMaxSegments && parse_segment(line.c_str(),seg))pending.push_back(seg);
    } else if(line.rfind("hud ",0)==0) {
        const std::string value=line.substr(4,56);
        if(value!=hudText){hudText=value;hudDirty=true;}
    } else if(line=="quit")stop=true;
}
void read_commands() {
    char buffer[8192];
    ssize_t n;
    while((n=read(STDIN_FILENO,buffer,sizeof buffer))>0) {
        incoming.append(buffer,size_t(n));
        if(incoming.size()>65536) { std::fprintf(stderr,"ft-room-vr: input too large\n");stop=true;return; }
        size_t pos=0;
        while((pos=incoming.find('\n'))!=std::string::npos) {
            command(incoming.substr(0,pos));
            incoming.erase(0,pos+1);
        }
    }
    if(n==0){reading=false;stop=true;}
}

} // namespace

int main(int argc,char**argv) {
    if(argc!=2) {std::fprintf(stderr,"usage: ft-room-vr /absolute/path/to/room_actions.json\n");return 2;}
    std::signal(SIGINT,Signal);std::signal(SIGTERM,Signal);
    vr::EVRInitError error=vr::VRInitError_None;
    vr::VR_Init(&error,vr::VRApplication_Overlay);
    if(error!=vr::VRInitError_None){std::fprintf(stderr,"ft-room-vr: SteamVR init: %s\n",vr::VR_GetVRInitErrorAsEnglishDescription(error));return 1;}
    overlay=vr::VROverlay();
    if(!overlay||!initialize_hud()){std::fprintf(stderr,"ft-room-vr: failed creating overlay\n");vr::VR_Shutdown();return 1;}
    Buttons buttons;
    if(!buttons.init(argv[1])) {
        std::fprintf(stderr,"ft-room-vr: action manifest unavailable; no controller input\n");
        hudText="INPUT UNAVAILABLE";hudDirty=true;draw_hud();
    }
    if(!vr::VRSettings()->GetBool("steamvr","globalActionSetPriority",nullptr))
        std::fprintf(stderr,"ft-room-vr: SteamVR overlay-global input not enabled; buttons may not work\n");
    const auto universe=vr::VRSystem()->GetUint64TrackedDeviceProperty(
        vr::k_unTrackedDeviceIndex_Hmd,vr::Prop_CurrentUniverseId_Uint64,nullptr);
    std::printf("ready %llu\n",static_cast<unsigned long long>(universe));std::fflush(stdout);
    const int flags=fcntl(STDIN_FILENO,F_GETFL,0);
    if(flags>=0)fcntl(STDIN_FILENO,F_SETFL,flags|O_NONBLOCK);
    bool scene=false,shown=false;
    auto lastAim=Clock::now()-std::chrono::seconds(1);
    auto lastUniverse=Clock::now();
    uint64_t activeUniverse=universe;
    while(!stop) {
        read_commands();
        if(Clock::now()-lastUniverse>std::chrono::seconds(1)) {
            lastUniverse=Clock::now();
            uint64_t now=vr::VRSystem()->GetUint64TrackedDeviceProperty(
                vr::k_unTrackedDeviceIndex_Hmd,vr::Prop_CurrentUniverseId_Uint64,nullptr);
            if(now!=activeUniverse) {
                activeUniverse=now;
                std::printf("universe %llu\n",static_cast<unsigned long long>(now));
                std::fflush(stdout);
                // Stop projecting stale geometry even before the Python session exits.
                show_geometry(false);
                overlay->HideOverlay(hud);
                break;
            }
        }
        const bool isScene=vr::VRApplications()->GetCurrentSceneProcessId()!=0;
        if(isScene!=scene) {scene=isScene;layoutDirty=true;}
        if(scene) {
            if(shown){show_geometry(false);overlay->HideOverlay(hud);shown=false;}
        } else {
            if(!shown){overlay->ShowOverlay(hud);layoutDirty=true;shown=true;}
            if(layoutDirty){show_geometry(true);layoutDirty=false;}
            draw_hud();
            buttons.poll(false);
            if(Clock::now()-lastAim>std::chrono::milliseconds(120)) {
                lastAim=Clock::now();
                const Ray r=controller_ray();
                if(r.valid) {
                    std::printf("aim %.6f %.6f %.6f %.6f %.6f %.6f\n",
                        r.o[0],r.o[1],r.o[2],r.dir[0],r.dir[1],r.dir[2]);
                    std::fflush(stdout);
                }
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }
    if(hud!=vr::k_ulOverlayHandleInvalid)overlay->DestroyOverlay(hud);
    for(auto h:ribbons)overlay->DestroyOverlay(h);
    vr::VR_Shutdown();
    return 0;
}
