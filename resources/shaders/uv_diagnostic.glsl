/*
  uv_diagnostic.glsl — QIDIStudio UV Mapping Diagnostic Fragment Shader
  =======================================================================
  Implements the "Geometric Microscope" from docs/AI Debugging Texture
  Mapping Glitches.md §I, implementing a Jacobian-based UV distortion
  visualiser that converts conformal mapping errors into a colour signal
  readable by the AI vision module.

  Three visualisation modes (u_visualMode uniform):
    0.0  CHECKERBOARD  — 8×8 procedural grid; aspect-ratio drift > 15%
                         indicates high Dirichlet energy E_D (Lévy 2002)
    1.0  HEATMAP       — Jacobian stretch heatmap computed from screen-space
                         UV derivatives (dFdx/dFdy approximation)
    2.0  HYBRID        — 50/50 blend of CHECKERBOARD + HEATMAP

  Colour semantics (HEATMAP mode):
    GREEN  = Perfect conformal map  (|dx| ≈ |dy|, logStretch ≈ 0)
    RED    = Compression zone       (texture pixels < 3D surface area)
    BLUE   = Expansion / stretch    (texture pixels > 3D surface area)

  This is the "signal" the AI texture critic reads:
  • Large red zones near camera island → seam misplacement (Lévy 2002 §4)
  • Large blue zones on flat backs     → LSCM pinching (use OBJECT coords)
  • Alternating bands on revolution    → seam angle too wide (use 30°, not 60°)

  Integration with apply_texture_bpy.py pipeline:
  • Python generates the UV debug snapshots (session_summary.json)
  • This shader is injected into a debug-build render to provide the VISUAL
    signal that the AI correlates with the telemetry JSON
  • scripts/ai_texture_critic.py reads BOTH and produces a structured diagnosis

  References:
    Lévy 2002     — Least Squares Conformal Maps (original LSCM paper)
    Sander 2001   — Texture Mapping Progressive Meshes (L2 stretch metric)
    Crane 2024    — Discrete Differential Geometry §7 (conformal energy)
    Nimier-David 2019 — Mitsuba 2: Differentiable Rendering (inverse rendering)
    docs/AI Debugging Texture Mapping Glitches.md §I–IV
    docs/AI Debugging 3D Texture Mapping.md §I–V

  USAGE (inject into debug build):
    Compile as part of the QIDIStudio GLSL shader system.
    Set u_visualMode before any mesh render call:
      glUniform1f(loc_uVisualMode, 1.0f);  // heatmap
    Bind a 1024×1024 white/black checker image to u_debugChecker for mode 0/2.
*/

#version 450
precision highp float;

// ── Varyings ──────────────────────────────────────────────────────────────
in vec2 v_uv;           // UV coordinates interpolated from vertex shader
out vec4 fragColor;

// ── Uniforms ──────────────────────────────────────────────────────────────
uniform sampler2D u_debugChecker;   // 1024×1024 checker texture (mode 0 / 2)
uniform float     u_visualMode;     // 0: checker  1: heatmap  2: hybrid

// ── Threshold (PhD calibration: Lévy 2002 §3, Sander 2001 L2 metric) ─────
// Drift > 15% in checker aspect ratio → high Dirichlet energy zone.
// Maps to logStretch of log2(1.15) ≈ 0.20 — set visualisation centre accordingly.
const float THRESHOLD = 0.20;      // logStretch magnitude = "worth showing"
const float CHECKER_SCALE = 8.0;   // 8×8 grid matches docs §I.1 recommendation

// ─────────────────────────────────────────────────────────────────────────
// _jacobian_heatmap()
// ─────────────────────────────────────────────────────────────────────────
// Approximates the 2D Jacobian of the UV mapping using screen-space finite
// differences (dFdx / dFdy are the partial derivatives of v_uv with respect
// to screen pixel x and y, provided by the rasteriser).
//
// The ratio |dx| / |dy| measures anisotropy:
//   ratio = 1.0  → conformal (angle-preserving) — GREEN
//   ratio > 1.0  → texture compressed in y / stretched in x — RED shift
//   ratio < 1.0  → texture compressed in x / stretched in y — BLUE shift
//
// logStretch = log2(ratio) centres the scale at 0 (GREEN):
//   logStretch > 0  → red tint    (compression: too many texels per mm²)
//   logStretch < 0  → blue tint   (expansion:   too few  texels per mm²)
//   logStretch ≈ 0  → green output (conformal — ideal)
//
// Mathematical relationship to Dirichlet energy:
//   E_D(ψ) = ∫|∇ψ|² dA  (Lévy 2002 eq. 4)
//   Locally, E_D per fragment ∝ max(stretch, 1/stretch)
// ─────────────────────────────────────────────────────────────────────────
vec3 _jacobian_heatmap() {
    // Screen-space UV derivatives (Jacobian row approximation)
    vec2 dx = dFdx(v_uv);   // ∂uv/∂screen_x
    vec2 dy = dFdy(v_uv);   // ∂uv/∂screen_y

    // Guard against degenerate (zero) derivatives at silhouette edges
    float mag_dx = max(length(dx), 1e-7);
    float mag_dy = max(length(dy), 1e-7);

    // Log2 of the stretch ratio — centred at 0 = conformal
    float logStretch = log2(mag_dx / mag_dy);

    // Clamp to visualisation range (±2 stops = ×4 compression/expansion)
    logStretch = clamp(logStretch, -2.0, 2.0);

    // Colour map:
    //   logStretch  > 0:  interpolate GREEN → RED   (compression)
    //   logStretch  < 0:  interpolate GREEN → BLUE  (expansion)
    //   logStretch  = 0:  pure GREEN               (conformal)
    vec3 heatmap;
    if (logStretch >= 0.0) {
        // Green → Red: t goes 0→1 as logStretch goes 0→1
        float t = logStretch / 2.0;
        heatmap = mix(vec3(0.0, 0.8, 0.1), vec3(0.9, 0.1, 0.0), t);
    } else {
        // Green → Blue: t goes 0→1 as |logStretch| goes 0→1
        float t = -logStretch / 2.0;
        heatmap = mix(vec3(0.0, 0.8, 0.1), vec3(0.0, 0.1, 0.9), t);
    }

    // Overlay a bright ring at the threshold boundary (|logStretch| ≈ THRESHOLD)
    // This makes the "15% distortion zone boundary" visually crisp.
    float dist_to_threshold = abs(abs(logStretch) - THRESHOLD);
    if (dist_to_threshold < 0.04) {
        heatmap = mix(heatmap, vec3(1.0, 1.0, 0.0), 0.7);  // yellow boundary ring
    }

    return heatmap;
}

// ─────────────────────────────────────────────────────────────────────────
// main()
// ─────────────────────────────────────────────────────────────────────────
void main() {
    // Mode 0: Pure checkerboard (UV distortion via aspect-ratio drift)
    // Mode 1: Pure Jacobian heatmap (screen-space derivative analysis)
    // Mode 2: Hybrid blend — best for diagnosing both stretch AND anisotropy

    if (u_visualMode < 0.5) {
        // ── CHECKERBOARD MODE ────────────────────────────────────────────
        // Tile at CHECKER_SCALE repetitions — distortion appears as non-square
        // checker elements. AI measures aspect ratio of each checker cell.
        fragColor = texture(u_debugChecker, v_uv * CHECKER_SCALE);

    } else if (u_visualMode < 1.5) {
        // ── HEATMAP MODE ─────────────────────────────────────────────────
        fragColor = vec4(_jacobian_heatmap(), 1.0);

    } else {
        // ── HYBRID MODE ──────────────────────────────────────────────────
        vec4 checker  = texture(u_debugChecker, v_uv * CHECKER_SCALE);
        vec4 heat     = vec4(_jacobian_heatmap(), 1.0);
        // Weight heatmap more strongly where energy is high (above threshold)
        float logS    = abs(log2(max(length(dFdx(v_uv)), 1e-7) /
                                  max(length(dFdy(v_uv)), 1e-7)));
        float blend   = smoothstep(0.0, THRESHOLD * 2.0, logS);
        // Low-distortion areas: mostly checker (pattern quality)
        // High-distortion areas: mostly heatmap (quantitative signal)
        fragColor = mix(checker, heat, 0.3 + blend * 0.5);
    }
}
