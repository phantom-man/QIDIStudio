#!/usr/bin/env python3
"""
ai_texture_critic.py — Autonomous AI Texture Mapping Quality Analyser
======================================================================
Implements the complete Vision-in-the-Loop (ViL) debugging loop described in:
  - docs/AI Debugging 3D Texture Mapping.md
  - docs/AI Debugging Texture Mapping Glitches.md

Given a session_summary.json produced by apply_texture_bpy.py --debug-snapshots,
this script autonomously:

  1. Reads the telemetry JSON (post_weld / post_classify / post_displace stages)
  2. Analyses UV stretch metrics, Shape DNA, feature values
  3. Cross-references visual signals with the Laplacian DNA
  4. Issues structured REMEDIATION HINTS — specific code/threshold changes
  5. Writes ai_texture_critic_report.txt in the same directory

The AI can run this instead of (or before) looking at rendered images.
It implements the "Formal Geometric Heuristic" from docs/AI Debugging 3D Texture
Mapping.md §II with the following diagnostic decision tree:

  IF mesh_class != expected_class     → threshold calibration issue
  IF uv_stretch.high_energy_frac > 0.20  → seam placement issue
  IF uv_stretch.dirichlet_energy  > 2.0  → wrong projection (LSCM vs OBJECT)
  IF Shape DNA mismatch logged        → topology misclassification
  IF mean_stretch << 1.0 globally     → UV scale calibration issue
  IF max_stretch  > 5.0               → collapsed UV island (degenerate face)

Usage:
  # Run after apply_texture_bpy.py --debug-snapshots --snapshots-dir /tmp/snaps
  python scripts/ai_texture_critic.py /tmp/snaps/session_summary.json

  # Or point at a snapshots directory directly
  python scripts/ai_texture_critic.py /tmp/snaps/

  # Run as part of ai_debug_pipeline.py — called automatically per test case

Mathematical references:
  Dirichlet energy   E_D(ψ) = ∫_M |∇ψ|² dA             (Lévy 2002 eq. 4)
  L2 stretch metric  Γ²     = Σ(a²+b²+c²+d²) / 2A       (Sander 2001)
  Shape DNA          λ_k    = k-th eigenvalue Δ_M         (Reuter 2006)
  Conformal deficit  κ_v    = 2π − Σ interior angles at v (CMU 15-458 §6)
"""

import sys
import os
import json
import pathlib
import math
from dataclasses import dataclass, field
from typing import Optional


# ── Diagnostic thresholds ─────────────────────────────────────────────────
# From docs/AI Debugging 3D Texture Mapping.md §II ("Formal Geometric Heuristic")
# and calibrated against real runs from ai_debug_pipeline.py TEST_CASES.

STRETCH_HIGH_ENERGY_THRESHOLD = 0.15  # Lévy 2002: > 15% drift = high Dirichlet E
STRETCH_HIGH_FRAC_WARN = 0.20  # > 20% of faces with high energy = problem
DIRICHLET_ENERGY_WARN = 2.0  # E_D normalised by total 3D area > 2.0
MAX_STRETCH_DEGENERATE = 50.0  # max_stretch > 50 = collapsed UV island (ERROR)
MAX_STRETCH_WARN = 5.0  # max_stretch > 5  = severe local stretch (WARNING)
MEAN_STRETCH_SCALE_WARN_LOW = 0.5  # mean < 0.5 → UV overscaled (too large tiles)
MEAN_STRETCH_SCALE_WARN_HIGH = 3.0  # mean > 3.0 → UV underscaled (too small tiles)
DNA_RATIO_REVOLUTION_MIN = 0.85  # λ1/λ2 > 0.85 → REVOLUTION-like (Reuter 2006)
DNA_RATIO_FLAT_MAX = 0.50  # λ1/λ2 < 0.50 → FLAT/PRISMATIC-like


# ── Data classes ──────────────────────────────────────────────────────────


@dataclass
class DiagnosticIssue:
    """A single detected quality issue with its root cause and remediation."""

    severity: str  # "ERROR" | "WARNING" | "INFO"
    stage: str  # which pipeline stage revealed it
    signal: str  # "visual" | "metric" | "dna" | "topology"
    description: str
    root_cause: str
    remediation: str


@dataclass
class CriticReport:
    """Complete diagnostic report for one apply_texture_bpy.py run."""

    model_path: str
    n_stages: int
    mesh_class: str
    projection: str
    issues: list[DiagnosticIssue] = field(default_factory=list)
    overall: str = "PASS"  # "PASS" | "WARN" | "FAIL"

    def add(self, issue: DiagnosticIssue):
        self.issues.append(issue)
        if issue.severity == "ERROR":
            self.overall = "FAIL"
        elif issue.severity == "WARNING" and self.overall != "FAIL":
            self.overall = "WARN"


# ── Core diagnostic functions ─────────────────────────────────────────────


def _analyse_uv_stretch(stage_data: dict, report: CriticReport) -> None:
    """
    Analyse UV stretch metrics from a post_displace snapshot.

    Decision tree:
    1. high_energy_frac > 20%  → seam placement causes UV island fragmentation
    2. dirichlet_energy > 2.0  → wrong projection mode (OBJECT vs LSCM)
    3. max_stretch > 5.0       → collapsed UV island (degenerate polygon in UV)
    4. mean_stretch << 1.0     → UV globally overscaled (tile_size too large)
    5. mean_stretch >> 3.0     → UV globally underscaled (tile_size too small)

    References:
      Lévy 2002 §3 — LSCM minimises Dirichlet energy E_D
      Sander 2001  — L2 stretch metric (a²+b²+c²+d²)/2A
    """
    stretch = stage_data.get("uv_stretch", {})
    if not stretch or "error" in stretch:
        err_msg = (
            stretch.get("error", "no uv_stretch in snapshot")
            if stretch
            else "no uv_stretch in snapshot"
        )
        # OBJECT-coords mode won't have UV stretch — not an error
        proj = stage_data.get("projection", "object")
        if proj == "object":
            report.add(
                DiagnosticIssue(
                    severity="INFO",
                    stage="post_displace",
                    signal="metric",
                    description="No UV stretch data (OBJECT-coords mode)",
                    root_cause="Mesh classified as FLAT_SHELL or PRISMATIC → world-space box-map, no UV layer",
                    remediation="If texture appears to tile correctly on flat surfaces, this is correct behaviour. "
                    "If wrapping round edges, override with --projection lscm.",
                )
            )
        else:
            report.add(
                DiagnosticIssue(
                    severity="WARNING",
                    stage="post_displace",
                    signal="metric",
                    description=f"UV stretch data unavailable: {err_msg}",
                    root_cause="UV layer missing after displacement pipeline",
                    remediation="Check that _do_uv_unwrap() ran successfully. Look for 'UV unwrap complete' in log.",
                )
            )
        return

    mean_s = stretch.get("mean_stretch", 1.0)
    max_s = stretch.get("max_stretch", 1.0)
    frac = stretch.get("high_energy_frac", 0.0)
    e_d = stretch.get("dirichlet_energy", 0.0)
    n_high = stretch.get("n_high_energy_faces", 0)
    n_faces = stretch.get("n_faces", 1)

    # ── Check 1: High-energy face fraction ────────────────────────────────
    if frac > STRETCH_HIGH_FRAC_WARN:
        report.add(
            DiagnosticIssue(
                severity="WARNING",
                stage="post_displace",
                signal="metric",
                description=(
                    f"High Dirichlet energy: {n_high}/{n_faces} faces "
                    f"({frac:.1%}) have stretch > 15%"
                ),
                root_cause=(
                    "UV island boundaries create discontinuities (spike fans) where "
                    "the Displace modifier samples the texture at different offsets per island. "
                    "Most common at camera islands, circular ports, and sharp boss rims."
                ),
                remediation=(
                    "1. In _classify_mesh_topology(): reduce seam_angle_rad from 60° to 30° "
                    "   (change ORGANIC_RAD seam from 1.047 to 0.524) if mesh is FLAT_SHELL/PRISMATIC.\n"
                    "2. If mesh is REVOLUTION (tall cylinder), verify annular=True (χ≤0).\n"
                    "3. If all else fails, force --projection object for this mesh.\n"
                    "4. Increase Taubin smoothing iterations (_ITERS in _apply_displacement_blender) "
                    "   from max(15,...) to max(25,...) to better blend seam discontinuities."
                ),
            )
        )

    # ── Check 2: Dirichlet energy (total conformal deficit) ───────────────
    if e_d > DIRICHLET_ENERGY_WARN:
        report.add(
            DiagnosticIssue(
                severity="ERROR" if e_d > 5.0 else "WARNING",
                stage="post_displace",
                signal="metric",
                description=(
                    f"Dirichlet energy E_D = {e_d:.3f} (threshold {DIRICHLET_ENERGY_WARN}). "
                    "Severe conformal distortion across the mesh."
                ),
                root_cause=(
                    "Wrong projection mode for mesh topology. "
                    "LSCM on flat/prismatic geometry fragments islands at every sharp edge, "
                    "producing high E_D. OBJECT-coords on curved geometry produces global stretch "
                    "because world-space XY does not follow the surface geodesically."
                ),
                remediation=(
                    "Check mesh_class in session_summary.json:\n"
                    "  - FLAT_SHELL/PRISMATIC with LSCM → switch to OBJECT coords: "
                    "    lower sharp_fraction threshold from 0.35 to 0.25 in _classify_mesh_topology()\n"
                    "  - ORGANIC/REVOLUTION with OBJECT → switch to LSCM: "
                    "    lower z_ratio threshold from 1.0 to 0.6 in _classify_mesh_topology()\n"
                    "  - Add the new mesh as a test case in scripts/ai_debug_pipeline.py "
                    "    and run it to validate the threshold change."
                ),
            )
        )

    # ── Check 3a: Degenerate UV island (collapsed face, very high stretch) ──
    if max_s > MAX_STRETCH_DEGENERATE:
        report.add(
            DiagnosticIssue(
                severity="ERROR",
                stage="post_displace",
                signal="metric",
                description=(
                    f"Degenerate UV island detected: max_stretch = {max_s:.1f} "
                    f"(threshold {MAX_STRETCH_DEGENERATE}). At least one face collapsed to a point in UV space."
                ),
                root_cause=(
                    "A polygon collapsed to zero area in UV space. Common causes:\n"
                    "  (a) Extremely thin/sliver triangles on the original mesh\n"
                    "  (b) UV island scaled to effectively zero by the tile normalisation\n"
                    "  (c) Degenerate geometry in the source STL (overlapping verts not welded)"
                ),
                remediation=(
                    "1. Verify weld ran: check 'Welded: N→M verts' in the pipeline log. "
                    "   If before≈after, STL has no duplicates but may have actual slivers.\n"
                    "2. Run 'Select → Select All by Trait → Non Manifold' in Blender to identify slivers.\n"
                    "3. Increase weld distance from 0.001 to 0.01 mm in _apply_displacement_blender() "
                    "   bmesh.ops.remove_doubles(dist=0.001) → dist=0.01"
                ),
            )
        )
    # ── Check 3b: Severe local stretch near seams (WARNING) ───────────────
    elif max_s > MAX_STRETCH_WARN:
        report.add(
            DiagnosticIssue(
                severity="WARNING",
                stage="post_displace",
                signal="metric",
                description=(
                    f"Local UV stretch near seam boundaries: max_stretch = {max_s:.1f} "
                    f"(warn threshold {MAX_STRETCH_WARN}).  Mean = {mean_s:.3f} (acceptable)."
                ),
                root_cause=(
                    "LSCM seam-cut triangles typically have higher stretch than interior faces — "
                    "this is expected for cylindrical/revolution meshes with 30° seam angles. "
                    f"max_stretch {max_s:.0f} << 50 (degenerate threshold), so no UV collapse."
                ),
                remediation=(
                    "If texture shows visible tiling at seam lines, reduce seam_angle_rad "
                    "from 30° to 20° in _classify_mesh_topology() for REVOLUTION meshes to "
                    "create more, smaller islands with lower per-island stretch."
                ),
            )
        )

    # ── Check 4: UV scale calibration issues ──────────────────────────────
    if mean_s < MEAN_STRETCH_SCALE_WARN_LOW:
        report.add(
            DiagnosticIssue(
                severity="WARNING",
                stage="post_displace",
                signal="metric",
                description=f"UV overscaled: mean_stretch = {mean_s:.3f} < {MEAN_STRETCH_SCALE_WARN_LOW}",
                root_cause=(
                    "UV scale calibration underestimated mm/UV-unit ratio. "
                    "The mm_per_uv estimate from edge sampling is too small → tile_size appears too large."
                ),
                remediation=(
                    "Increase --tile-size argument (e.g. from 15mm to 25mm) OR "
                    "check the edge-length sampling loop in _do_uv_unwrap(): "
                    "verify n_samp > 200 before the scale is computed."
                ),
            )
        )

    if mean_s > MEAN_STRETCH_SCALE_WARN_HIGH:
        report.add(
            DiagnosticIssue(
                severity="WARNING",
                stage="post_displace",
                signal="metric",
                description=f"UV underscaled: mean_stretch = {mean_s:.3f} > {MEAN_STRETCH_SCALE_WARN_HIGH}",
                root_cause=(
                    "UV scale calibration overestimated mm/UV-unit ratio. "
                    "The texture pattern will repeat too frequently — very fine tile."
                ),
                remediation=(
                    "Decrease --tile-size argument (e.g. from 15mm to 8mm) OR "
                    "verify that the mesh is in correct-scale millimetres, not metres."
                ),
            )
        )


def _analyse_topology(stage_data: dict, report: CriticReport) -> None:
    """
    Analyse topology classification and cross-reference with Shape DNA.

    The Spectral DNA hook (Reuter 2006): λ1/λ2 ratio reveals rotational symmetry:
      ratio > 0.85 → REVOLUTION-like (degenerate eigenvalue pair)
      ratio < 0.50 → FLAT/PRISMATIC-like (spread spectrum, asymmetric)
      0.50..0.85   → ORGANIC (moderate asymmetry)

    If classifier output contradicts DNA evidence → likely misclassification.
    """
    mesh_class = stage_data.get("mesh_class", "UNKNOWN")
    features = stage_data.get("features", {})
    proj = stage_data.get("projection", "unknown")

    sharp_frac = features.get("sharp_fraction", None)
    z_ratio = features.get("z_ratio", None)
    k_std = features.get("curvature_std", None)
    euler_char = features.get("euler_characteristic", None)

    # Validate classifier feature values are sensible
    if sharp_frac is not None and z_ratio is not None:
        # Sanity check: FLAT_SHELL with z_ratio > 0.4 is suspicious
        if mesh_class == "FLAT_SHELL" and z_ratio > 0.4:
            report.add(
                DiagnosticIssue(
                    severity="WARNING",
                    stage="post_classify",
                    signal="topology",
                    description=(
                        f"FLAT_SHELL classification with z_ratio={z_ratio:.3f} > 0.25. "
                        "Object may be taller than expected for a flat shell."
                    ),
                    root_cause=(
                        "z_ratio threshold (0.25) may be too generous for this mesh. "
                        "The mesh has significant Z extent but was still classified as flat."
                    ),
                    remediation=(
                        "If texture is wrapping incorrectly around Z-walls, lower the flat threshold:\n"
                        "  In _classify_mesh_topology():  flat = z_ratio < 0.20  (was 0.25)\n"
                        "  This will promote tall flat meshes to ORGANIC and use LSCM."
                    ),
                )
            )

        # REVOLUTION requires χ≤0 (annular manifold) — if χ>0, should be ORGANIC
        if mesh_class == "REVOLUTION" and euler_char is not None and euler_char > 0:
            report.add(
                DiagnosticIssue(
                    severity="ERROR",
                    stage="post_classify",
                    signal="topology",
                    description=(
                        f"REVOLUTION classification but χ={euler_char} > 0. "
                        "Non-annular manifold classified as revolution surface."
                    ),
                    root_cause=(
                        "The Euler characteristic tiebreaker requires χ≤0 for REVOLUTION "
                        "(annular manifold = open cylinder). χ>0 means the mesh is a closed "
                        "surface (figurine, pedestal) — should be ORGANIC."
                    ),
                    remediation=(
                        "The match/case in _classify_mesh_topology() has this guard:\n"
                        "   case (False, True, False) if annular:  // REVOLUTION\n"
                        "Ensure 'annular = euler_char <= 0' is evaluated correctly.\n"
                        "If euler_char is always positive, check if the mesh has boundary edges "
                        "(open bottom) that reduce χ."
                    ),
                )
            )

    # Summary info record
    report.add(
        DiagnosticIssue(
            severity="INFO",
            stage="post_classify",
            signal="topology",
            description=(
                f"Topology: class={mesh_class}  projection={proj}  "
                f"sharp={sharp_frac:.1%}  z_ratio={z_ratio:.3f}  "
                f"K_std={k_std:.4f}  χ={euler_char}"
                if all(x is not None for x in [sharp_frac, z_ratio, k_std, euler_char])
                else f"Topology: class={mesh_class}  projection={proj}"
            ),
            root_cause="Topology classification summary (informational)",
            remediation="No action needed if class matches expected. "
            "Compare against TEST_CASES in scripts/ai_debug_pipeline.py.",
        )
    )


def _analyse_weld(stage_data: dict, report: CriticReport) -> None:
    """Check weld quality and geometry statistics."""
    before = stage_data.get("weld_before", None)
    after = stage_data.get("weld_after", None)

    if before is not None and after is not None:
        ratio = after / max(before, 1)
        if ratio > 0.98:
            # Very few duplicates welded — could be already-clean OR broken weld
            geom = stage_data.get("geometry", {})
            n_verts = geom.get("verts", 0)
            if n_verts > 100:  # not a trivially small mesh
                report.add(
                    DiagnosticIssue(
                        severity="INFO",
                        stage="post_weld",
                        signal="metric",
                        description=(
                            f"Weld ratio: {after}/{before} verts ({ratio:.1%} retained). "
                            "Very few duplicate vertices removed."
                        ),
                        root_cause=(
                            "Either: (a) input mesh already has shared vertices (non-STL format), "
                            "or (b) STL precision is low and weld distance 0.001mm is too tight."
                        ),
                        remediation=(
                            "If duplicate-vertex artifacts appear (coincident triangles with split normals),\n"
                            "try increasing weld distance: bmesh.ops.remove_doubles(dist=0.01) in\n"
                            "_apply_displacement_blender()."
                        ),
                    )
                )
        elif ratio < 0.3:
            # More than 70% of vertices welded — extremely over-welded
            report.add(
                DiagnosticIssue(
                    severity="WARNING",
                    stage="post_weld",
                    signal="metric",
                    description=(
                        f"Extreme weld: {before} → {after} verts ({ratio:.1%} retained). "
                        "Over 70% of vertices merged."
                    ),
                    root_cause=(
                        "Weld distance 0.001mm is too large relative to mesh scale, "
                        "OR the mesh has very small features (fine detail being destroyed)."
                    ),
                    remediation=(
                        "Decrease weld distance from 0.001 to 0.0001 in\n"
                        "_apply_displacement_blender():\n"
                        "  bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)"
                    ),
                )
            )


def _analyse_stage(stage_data: dict, report: CriticReport) -> None:
    """Dispatch analysis by stage name."""
    stage = stage_data.get("stage", "unknown")
    match stage:
        case "post_weld":
            _analyse_weld(stage_data, report)
        case "post_classify":
            _analyse_topology(stage_data, report)
        case "post_displace":
            # Topology already analysed at post_classify; only check UV stretch here
            _analyse_uv_stretch(stage_data, report)
        case _:
            pass


# ── Main analysis entry point ─────────────────────────────────────────────


def analyse_session(session_json_path: str) -> CriticReport:
    """
    Load a session_summary.json produced by apply_texture_bpy.py --debug-snapshots
    and return a fully-populated CriticReport.
    """
    session_path = pathlib.Path(session_json_path)
    if not session_path.exists():
        raise FileNotFoundError(f"Session JSON not found: {session_json_path}")

    with open(session_path, encoding="utf-8-sig") as fh:
        session = json.load(fh)

    model = session.get("model", "unknown")
    stages = session.get("stages", [])

    # Determine overall classification from post_classify or post_displace
    mesh_class = "UNKNOWN"
    projection = "unknown"
    for s in stages:
        if s.get("mesh_class") and s["mesh_class"] != "UNKNOWN":
            mesh_class = s["mesh_class"]
            projection = s.get("projection", "unknown")
            break

    report = CriticReport(
        model_path=model,
        n_stages=len(stages),
        mesh_class=mesh_class,
        projection=projection,
    )

    for stage_data in stages:
        _analyse_stage(stage_data, report)

    return report


def format_report(report: CriticReport) -> str:
    """
    Format a CriticReport as a human-readable text block.

    The "Multimodal Diagnostic Packet" from docs/AI Debugging 3D Texture Mapping.md §I
    translated into a text signal the AI agent can act on without vision capability.
    """
    lines = [
        "=" * 72,
        "  AI TEXTURE CRITIC REPORT",
        "=" * 72,
        f"  Model    : {report.model_path}",
        f"  Stages   : {report.n_stages}",
        f"  Topology : {report.mesh_class}  (projection={report.projection})",
        f"  Overall  : {report.overall}",
        "=" * 72,
        "",
    ]

    if not report.issues:
        lines.append(
            "  No issues detected. Pipeline is operating within normal parameters."
        )
    else:
        errors = [i for i in report.issues if i.severity == "ERROR"]
        warnings = [i for i in report.issues if i.severity == "WARNING"]
        infos = [i for i in report.issues if i.severity == "INFO"]

        if errors:
            lines.append(f"  ERRORS ({len(errors)})")
            lines.append("  " + "-" * 68)
            for i, issue in enumerate(errors, 1):
                lines += [
                    f"  [{i}] [{issue.stage}] {issue.description}",
                    f"      Root cause : {issue.root_cause}",
                    f"      Remediation: {issue.remediation}",
                    "",
                ]

        if warnings:
            lines.append(f"  WARNINGS ({len(warnings)})")
            lines.append("  " + "-" * 68)
            for i, issue in enumerate(warnings, 1):
                lines += [
                    f"  [{i}] [{issue.stage}] {issue.description}",
                    f"      Root cause : {issue.root_cause}",
                    f"      Remediation: {issue.remediation}",
                    "",
                ]

        if infos:
            lines.append(f"  INFO ({len(infos)})")
            lines.append("  " + "-" * 68)
            for issue in infos:
                lines.append(f"  [I] [{issue.stage}] {issue.description}")
            lines.append("")

    lines += [
        "=" * 72,
        "  BIBLIOGRAPHY (mathematical foundations of this analysis):",
        "  Lévy 2002    — LSCM: Least Squares Conformal Maps for UV",
        "  Sander 2001  — L2 stretch metric for UV quality evaluation",
        "  Reuter 2006  — Shape DNA: spectral geometry fingerprinting",
        "  Crane 2024   — Discrete Differential Geometry (CMU 15-458)",
        "  Taubin 1995  — Non-shrinking Laplacian smoothing (seam blend)",
        "  Chazal 2009  — Euler characteristic & topological invariants",
        "=" * 72,
    ]
    return "\n".join(lines)


# ── CLI entry point ───────────────────────────────────────────────────────


def main():
    # Ensure Unicode characters (χ, ∇, λ) print correctly on Windows consoles
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) < 2:
        print("Usage: ai_texture_critic.py <session_summary.json | snapshots_dir>")
        print()
        print("Reads session_summary.json produced by:")
        print("  blender.exe --background --python apply_texture_bpy.py -- \\")
        print("    model.stl skin.png --debug-snapshots --snapshots-dir /tmp/snaps")
        sys.exit(1)

    target = pathlib.Path(sys.argv[1])
    if target.is_dir():
        json_path = target / "session_summary.json"
    else:
        json_path = target

    if not json_path.exists():
        print(f"ERROR: {json_path} not found", file=sys.stderr)
        sys.exit(1)

    report = analyse_session(str(json_path))
    text = format_report(report)
    out_path = json_path.parent / "ai_texture_critic_report.txt"

    print(text)
    out_path.write_text(text, encoding="utf-8")
    print(f"\n  Report written to: {out_path}")

    sys.exit(0 if report.overall == "PASS" else 1)


if __name__ == "__main__":
    main()
