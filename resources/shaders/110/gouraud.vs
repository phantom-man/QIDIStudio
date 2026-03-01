#version 110
#define INTENSITY_CORRECTION 0.6

// World-space light directions — transformed to eye-space on GPU
const vec3 LIGHT_TOP_DIR_WS   = vec3(-0.4574957, 0.4574957, 0.7624929);
#define LIGHT_TOP_DIFFUSE    (0.8 * INTENSITY_CORRECTION)
#define LIGHT_TOP_SPECULAR   (0.125 * INTENSITY_CORRECTION)
#define LIGHT_TOP_SHININESS  80.0

const vec3 LIGHT_FRONT_DIR_WS = vec3(0.6985074, 0.1397015, 0.6985074);
#define LIGHT_FRONT_DIFFUSE  (0.3 * INTENSITY_CORRECTION)

const vec3 LIGHT_BACK_DIR_WS  = vec3(0.1397015, 0.6985074, 0.6985074);
#define LIGHT_BACK_DIFFUSE  (0.3 * INTENSITY_CORRECTION)

#define INTENSITY_AMBIENT    0.3

const vec3 ZERO = vec3(0.0, 0.0, 0.0);

struct SlopeDetection
{
    bool actived;
	float normal_z;
    mat3 volume_world_normal_matrix;
};

attribute vec3 v_position;
attribute vec3 v_normal;

uniform mat4 view_model_matrix;
uniform mat4 projection_matrix;
// view_matrix for world-space light transform; normal_matrix computed on GPU.
uniform mat4 view_matrix;

uniform mat4 volume_world_matrix;
uniform SlopeDetection slope;

// Clipping plane, x = min z, y = max z. Used by the FFF and SLA previews to clip with a top / bottom plane.
uniform vec2 z_range;
// Clipping plane - general orientation. Used by the SLA gizmo.
uniform vec4 clipping_plane;
uniform bool is_text_shape;
varying vec2 intensity;

varying vec3 clipping_planes_dots;

varying vec4 model_pos;
varying vec4 world_pos;
varying float world_normal_z;
varying vec3 eye_normal;
varying vec3 v_pos_eye;
// Eye-space light directions
varying vec3 v_light_top;
varying vec3 v_light_front;
varying vec3 v_light_back;

// GLSL 1.10 lacks built-in inverse/transpose — manual implementations
mat3 mat3_inverse(mat3 m) {
    float a = m[0][0], b = m[0][1], c = m[0][2];
    float d = m[1][0], e = m[1][1], f = m[1][2];
    float g = m[2][0], h = m[2][1], k = m[2][2];
    float det = a*(e*k-f*h) - b*(d*k-f*g) + c*(d*h-e*g);
    float inv = 1.0 / det;
    return mat3((e*k-f*h)*inv, (c*h-b*k)*inv, (b*f-c*e)*inv,
                (f*g-d*k)*inv, (a*k-c*g)*inv, (c*d-a*f)*inv,
                (d*h-e*g)*inv, (b*g-a*h)*inv, (a*e-b*d)*inv);
}
mat3 mat3_transpose(mat3 m) {
    return mat3(m[0][0], m[1][0], m[2][0],
                m[0][1], m[1][1], m[2][1],
                m[0][2], m[1][2], m[2][2]);
}

void main()
{
	// GPU-computed normal matrix (GLSL 1.10 manual implementation).
	mat3 gpu_nm = mat3_transpose(mat3_inverse(mat3(view_model_matrix)));
	eye_normal = normalize(gpu_nm * v_normal);

	vec4 position = (view_model_matrix * vec4(v_position, 1.0));
	v_pos_eye = position.xyz;

	// Transform world-space light dirs to eye-space on GPU.
	mat3 view_rot = mat3(view_matrix);
	v_light_top   = normalize(view_rot * LIGHT_TOP_DIR_WS);
	v_light_front = normalize(view_rot * LIGHT_FRONT_DIR_WS);
	v_light_back  = normalize(view_rot * LIGHT_BACK_DIR_WS);

	intensity = vec2(1.0, 0.0);

    world_pos = volume_world_matrix * vec4(v_position, 1.0);
    world_normal_z = slope.actived ? (normalize(slope.volume_world_normal_matrix * v_normal)).z : 0.0;
    gl_Position = projection_matrix * position;
    clipping_planes_dots = vec3(dot(world_pos, clipping_plane), world_pos.z - z_range.x, z_range.y - world_pos.z);
}
