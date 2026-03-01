#version 140

#define INTENSITY_CORRECTION 0.6

// World-space light directions — transformed to eye-space on GPU each draw
const vec3 LIGHT_TOP_DIR_WS   = vec3(-0.4574957, 0.4574957, 0.7624929);
#define LIGHT_TOP_DIFFUSE    (0.8 * INTENSITY_CORRECTION)
#define LIGHT_TOP_SPECULAR   (0.125 * INTENSITY_CORRECTION)
#define LIGHT_TOP_SHININESS  80.0

// normalized values for (1./1.43, 0.2/1.43, 1./1.43)
const vec3 LIGHT_FRONT_DIR_WS = vec3(0.6985074, 0.1397015, 0.6985074);
#define LIGHT_FRONT_DIFFUSE  (0.3 * INTENSITY_CORRECTION)

#define INTENSITY_AMBIENT    0.3

in vec3 v_position;
in vec3 v_normal;

uniform mat4 view_model_matrix;
uniform mat4 projection_matrix;
// view_matrix for world-space → eye-space light transform; normal_matrix computed on GPU.
uniform mat4 view_matrix;

// x = diffuse, y = specular (kept for FS compatibility; lighting now computed per-pixel in FS)
out vec2 intensity;
// Eye-space normal and position for per-pixel Phong in the fragment shader
out vec3 eye_normal;
out vec3 v_pos_eye;
// Eye-space light directions (world-space dirs rotated by view matrix)
out vec3 v_light_top;
out vec3 v_light_front;

void main()
{
    // GPU-computed normal matrix — eliminates CPU inverse+transpose per draw call.
    mat3 gpu_nm = transpose(inverse(mat3(view_model_matrix)));
    eye_normal = normalize(gpu_nm * v_normal);

    vec4 position = view_model_matrix * vec4(v_position, 1.0);
    v_pos_eye = position.xyz;

    // Transform world-space light dirs to eye-space on GPU.
    mat3 view_rot = mat3(view_matrix);
    v_light_top   = normalize(view_rot * LIGHT_TOP_DIR_WS);
    v_light_front = normalize(view_rot * LIGHT_FRONT_DIR_WS);

    intensity = vec2(1.0, 0.0);

    gl_Position = projection_matrix * position;
}
