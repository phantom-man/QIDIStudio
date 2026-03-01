#version 140
#define INTENSITY_CORRECTION 0.6

// World-space light directions — transformed to eye-space on GPU each draw
const vec3 LIGHT_TOP_DIR_WS   = vec3(-0.4574957, 0.4574957, 0.7624929);
const vec3 LIGHT_FRONT_DIR_WS = vec3( 0.6985074, 0.1397015, 0.6985074);
const vec3 LIGHT_BACK_DIR_WS  = vec3( 0.1397015, 0.6985074, 0.6985074);

#define INTENSITY_AMBIENT    0.3

const vec3 ZERO = vec3(0.0, 0.0, 0.0);

struct SlopeDetection
{
    bool actived;
	float normal_z;
    mat3 volume_world_normal_matrix;
};

in vec3 v_position;
in vec3 v_normal;

uniform mat4 view_model_matrix;
uniform mat4 projection_matrix;
// view_matrix is separate so we can transform world-space lights to eye-space on GPU.
// normal_matrix is computed entirely on GPU (transpose(inverse(...))) — no CPU upload needed.
uniform mat4 view_matrix;

uniform mat4 volume_world_matrix;
uniform SlopeDetection slope;

// Clipping plane, x = min z, y = max z. Used by the FFF and SLA previews to clip with a top / bottom plane.
uniform vec2 z_range;
// Clipping plane - general orientation. Used by the SLA gizmo.
uniform vec4 clipping_plane;
uniform bool is_text_shape;
// x = diffuse, y = specular (kept for FS compatibility; lighting now computed per-pixel in FS)
out vec2 intensity;

out vec3 clipping_planes_dots;

out vec4 model_pos;
out vec4 world_pos;
out float world_normal_z;
out vec3 eye_normal;
// Eye-space position for view-vector computation in the fragment shader
out vec3 v_pos_eye;
// Eye-space light directions (world-space dirs rotated by view matrix, constant per draw call)
out vec3 v_light_top;
out vec3 v_light_front;
out vec3 v_light_back;

void main()
{
	// GPU-computed normal matrix — eliminates CPU inverse+transpose per draw call.
	mat3 gpu_nm = transpose(inverse(mat3(view_model_matrix)));
	eye_normal = normalize(gpu_nm * v_normal);

	vec4 position = (view_model_matrix * vec4(v_position, 1.0));
	// Pass eye-space position to fragment shader for view-vector computation.
	v_pos_eye = position.xyz;

	// Transform world-space light dirs to eye-space once per vertex (constant across draw).
	mat3 view_rot = mat3(view_matrix);
	v_light_top   = normalize(view_rot * LIGHT_TOP_DIR_WS);
	v_light_front = normalize(view_rot * LIGHT_FRONT_DIR_WS);
	v_light_back  = normalize(view_rot * LIGHT_BACK_DIR_WS);

	// Lighting is computed per-pixel in the fragment shader.
	intensity = vec2(1.0, 0.0);

    // Point in homogenous coordinates.
    world_pos = volume_world_matrix * vec4(v_position, 1.0);

    // z component of normal vector in world coordinate used for slope shading
    world_normal_z = slope.actived ? (normalize(slope.volume_world_normal_matrix * v_normal)).z : 0.0;

    gl_Position = projection_matrix * position;
    // Fill in the scalars for fragment shader clipping. Fragments with any of these components lower than zero are discarded.
    clipping_planes_dots = vec3(dot(world_pos, clipping_plane), world_pos.z - z_range.x, z_range.y - world_pos.z);
}
