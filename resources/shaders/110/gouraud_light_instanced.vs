#version 110

#define INTENSITY_CORRECTION 0.6

// normalized values for (-0.6/1.31, 0.6/1.31, 1./1.31)
const vec3 LIGHT_TOP_DIR = vec3(-0.4574957, 0.4574957, 0.7624929);
#define LIGHT_TOP_DIFFUSE    (0.8 * INTENSITY_CORRECTION)
#define LIGHT_TOP_SPECULAR   (0.125 * INTENSITY_CORRECTION)
#define LIGHT_TOP_SHININESS  20.0

// normalized values for (1./1.43, 0.2/1.43, 1./1.43)
const vec3 LIGHT_FRONT_DIR = vec3(0.6985074, 0.1397015, 0.6985074);
#define LIGHT_FRONT_DIFFUSE  (0.3 * INTENSITY_CORRECTION)

#define INTENSITY_AMBIENT    0.3

// vertex attributes
attribute vec3 v_position;
attribute vec3 v_normal;
// instance attributes
attribute vec3 i_offset;
attribute vec2 i_scales;

// x = diffuse, y = specular (kept for FS compatibility; lighting now computed per-pixel in FS)
varying vec2 intensity;
// Eye-space normal and position for per-pixel Phong in the fragment shader
varying vec3 eye_normal;
varying vec3 v_pos_eye;

void main()
{
    // Transform normal into eye space for per-pixel lighting in the fragment shader.
    eye_normal = normalize(gl_NormalMatrix * v_normal);

    vec4 world_position = vec4(v_position * vec3(vec2(1.5 * i_scales.x), 1.5 * i_scales.y) + i_offset - vec3(0.0, 0.0, 0.5 * i_scales.y), 1.0);
    vec3 eye_position = (gl_ModelViewMatrix * world_position).xyz;
    // Pass eye-space position to fragment shader for view-vector computation.
    v_pos_eye = eye_position;

    // Lighting is computed per-pixel in the fragment shader.
    intensity = vec2(1.0, 0.0);

    gl_Position = gl_ProjectionMatrix * vec4(eye_position, 1.0);
}
