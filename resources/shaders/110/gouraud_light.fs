#version 110

// Per-pixel Phong lighting constants
#define INTENSITY_CORRECTION 0.6
const vec3 LIGHT_TOP_DIR   = vec3(-0.4574957,  0.4574957, 0.7624929);
#define LIGHT_TOP_DIFFUSE   (0.8   * INTENSITY_CORRECTION)
#define LIGHT_TOP_SPECULAR  (0.125 * INTENSITY_CORRECTION)
#define LIGHT_TOP_SHININESS 20.0
const vec3 LIGHT_FRONT_DIR = vec3( 0.6985074,  0.1397015, 0.6985074);
#define LIGHT_FRONT_DIFFUSE (0.3 * INTENSITY_CORRECTION)
#define INTENSITY_AMBIENT   0.3

uniform vec4 uniform_color;
uniform float emission_factor;

// x = diffuse, y = specular (unused; lighting computed below)
varying vec2 intensity;
varying vec3 eye_normal;
varying vec3 v_pos_eye;

void main()
{
    // Per-pixel Phong lighting
    vec3 N = normalize(eye_normal);
    vec3 V = normalize(-v_pos_eye);
    float NdotL_top   = max(dot(N, LIGHT_TOP_DIR),   0.0);
    float NdotL_front = max(dot(N, LIGHT_FRONT_DIR), 0.0);
    float diff = INTENSITY_AMBIENT + emission_factor
               + NdotL_top   * LIGHT_TOP_DIFFUSE
               + NdotL_front * LIGHT_FRONT_DIFFUSE;
    float spec = LIGHT_TOP_SPECULAR * pow(max(dot(V, reflect(-LIGHT_TOP_DIR, N)), 0.0), LIGHT_TOP_SHININESS);
    vec3 lit_color = vec3(spec) + uniform_color.rgb * diff;
    // Gamma correction: linear -> sRGB
    gl_FragColor = vec4(pow(clamp(lit_color, 0.0, 1.0), vec3(1.0 / 2.2)), uniform_color.a);
}
