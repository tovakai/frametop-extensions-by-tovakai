// Reference fragment shader for a FUTURE Frametop compositor stereo stage.
// Not loaded by the current extension manager. Original independent formulation.
#extension GL_OES_EGL_image_external : require
precision highp float;
uniform samplerExternalOES color_tex; // source DMA-BUF via EGLImage
uniform sampler2D depth_tex;         // normalized R8 depth: near=1, far=0
uniform float strength;              // 0..0.10 of image width per eye
uniform float convergence;           // depth at the screen plane
uniform float eye;                   // -1 left, +1 right
uniform int iterations;              // <=8
varying vec2 uv;
void main() {
    vec2 source = uv;
    for (int i = 0; i < 8; ++i) {
        if (i >= iterations) break;
        float d = texture2D(depth_tex, clamp(source, vec2(0.0), vec2(1.0))).r;
        source.x = uv.x + eye * strength * (d - convergence);
    }
    gl_FragColor = vec4(texture2D(color_tex, clamp(source, vec2(0.0), vec2(1.0))).rgb, 1.0);
}
