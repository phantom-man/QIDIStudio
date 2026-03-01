#version 110

#define INTENSITY_CORRECTION 0.6
#define LIGHT_TOP_DIFFUSE    (0.8   * INTENSITY_CORRECTION)
#define LIGHT_TOP_SPECULAR   (0.125 * INTENSITY_CORRECTION)
#define LIGHT_TOP_SHININESS  80.0
#define LIGHT_FRONT_DIFFUSE  (0.3 * INTENSITY_CORRECTION)
#define INTENSITY_AMBIENT    0.3

uniform vec4 uniform_color;
uniform float emission_factor;

// x = diffuse, y = specular (unused; lighting computed below)
varying vec2 intensity;
varying vec3 eye_normal;
varying vec3 v_pos_eye;
// Eye-space light directions (computed in VS)
varying vec3 v_light_top;
varying vec3 v_light_front;

void main()
{
    // Per-pixel Blinn-Phong lighting (light dirs from VS varyings)
    vec3 N = normalize(eye_normal);
    vec3 V = normalize(-v_pos_eye);
    float NdotL_top   = max(dot(N, v_light_top),   0.0);
    float NdotL_front = max(dot(N, v_light_front), 0.0);
    float diff = INTENSITY_AMBIENT + emission_factor
               + NdotL_top   * LIGHT_TOP_DIFFUSE
               + NdotL_front * LIGHT_FRONT_DIFFUSE;
    vec3 H = normalize(v_light_top + V);
    float spec = LIGHT_TOP_SPECULAR * pow(max(dot(N, H), 0.0), LIGHT_TOP_SHININESS);
    vec3 lit_color = vec3(spec) + uniform_color.rgb * diff;
    // Gamma correction: linear -> sRGB
    gl_FragColor = vec4(pow(clamp(lit_color, 0.0, 1.0), vec3(1.0 / 2.2)), uniform_color.a);
}
