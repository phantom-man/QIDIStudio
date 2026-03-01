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

attribute vec3 v_position;
attribute vec3 v_normal;

uniform mat4 view_model_matrix;
uniform mat4 projection_matrix;
uniform mat3 normal_matrix;

// x = diffuse, y = specular (kept for FS compatibility; lighting now computed per-pixel in FS)
varying vec2 intensity;
// Eye-space normal and position for per-pixel Phong in the fragment shader
varying vec3 eye_normal;
varying vec3 v_pos_eye;

void main()
{
    // Transform normal into eye space for per-pixel lighting in the fragment shader.
    eye_normal = normalize(normal_matrix * v_normal);

    vec4 position = view_model_matrix * vec4(v_position, 1.0);
    // Pass eye-space position to fragment shader for view-vector computation.
    v_pos_eye = position.xyz;

    // Lighting is computed per-pixel in the fragment shader.
    intensity = vec2(1.0, 0.0);

    gl_Position = projection_matrix * position;
}
