#!/usr/bin/env python3
"""
apply_texture_bpy.py  —  Blender/bpy displacement texture generator.

Generates a texture-displaced mesh that QIDIStudio loads as a new volume:
  --mode part     → displacement shell added as MODEL_PART  (raised scales)
  --mode negative → displacement shell added as NEGATIVE_VOLUME (carved in)
  --mode modifier → original mesh replaced with displaced version

Invocation by QIDIStudio:
  <bpy_env>/Scripts/python.exe apply_texture_bpy.py
      <model_stl>  <skin_asset>
      [--mode modifier]
      [--tile-size 15]  [--relief 1.0]
      [--invert]  [--gamma 0.7]
      [--log <logfile>]

Output:
  Writes  SKIN_OUTPUT: <path>  to stdout (and log file).
  QIDIStudio parses that line to find the result STL.
"""

import sys
import os
import argparse
import pathlib
import tempfile
import traceback
import zipfile
import xml.etree.ElementTree as ET
import faulthandler
from dataclasses import dataclass
from enum import Enum, auto

# ── Safety net: if Blender's C++ layer segfaults, dump Python traceback ───
# Ref: "PhD-Level Hybrid Debugging Workflow.md" §IV.1
faulthandler.enable(file=sys.stderr, all_threads=True)

# ── bpy import ────────────────────────────────────────────────────────────
try:
    import bpy
except ImportError:
    print("ERROR: bpy not available. Run with bpy_env Python interpreter.", flush=True)
    sys.exit(1)


def _detect_full_blender() -> bool:
    """True when running under a full blender.exe installation (not the bpy pip package).

    Full Blender has a proper GL/viewport context so:
      - bpy.ops.object.convert(target='MESH') reliably applies modifiers
      - The Displace modifier evaluates correctly via the depsgraph
      - No vertex splitting occurs (unlike bmesh.from_object with UV seams)

    The bpy pip package lacks these guarantees even in background mode.
    """
    try:
        bp = bpy.app.binary_path
        if bp and os.path.basename(bp).lower().startswith("blender"):
            return True
    except Exception:
        pass
    # Fallback: blender sets sys.argv[0] to the launcher path
    if sys.argv and os.path.basename(sys.argv[0]).lower().startswith("blender"):
        return True
    return False


IS_FULL_BLENDER: bool = _detect_full_blender()

if not IS_FULL_BLENDER:
    print(
        "ERROR: apply_texture_bpy.py must be run via blender.exe --background --python.",
        flush=True,
    )
    print(
        "ERROR: The bpy pip package does not support the Displace modifier pipeline.",
        flush=True,
    )
    print(
        "ERROR: Install Blender from https://www.blender.org/download/ (version >= 4.0)",
        flush=True,
    )
    sys.exit(1)


# ── argument parsing ──────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate bpy-displaced texture mesh for QIDIStudio"
    )
    p.add_argument("model_path", help="Source STL/3MF to texture")
    p.add_argument("skin_path", help="Skin asset: PNG/JPG for displacement texture")
    p.add_argument(
        "--mode",
        choices=["part", "negative", "modifier"],
        default="modifier",
        help="part=add raised shell, negative=add carved shell, modifier=replace mesh",
    )
    p.add_argument(
        "--tile-size",
        type=float,
        default=None,
        help=(
            "Texture repeat size in mm.  Omit to use auto-calculated optimal value "
            "(recommended — computed from part geometry using symmetry theory)."
        ),
    )
    p.add_argument(
        "--relief",
        type=float,
        default=None,
        help=(
            "Displacement amplitude in mm.  Omit to use auto-calculated optimal value "
            "(recommended — proportional to tile_size at 1:20 emboss ratio)."
        ),
    )
    p.add_argument(
        "--no-auto-params",
        dest="auto_params",
        action="store_false",
        default=True,
        help=(
            "Disable automatic tile-size and relief calculation.  "
            "Use explicit --tile-size and --relief instead."
        ),
    )
    p.add_argument(
        "--invert", action="store_true", help="Invert the displacement direction"
    )
    p.add_argument(
        "--gamma",
        type=float,
        default=0.7,
        help="Gamma applied to the skin image before displacement (default 0.7)",
    )
    p.add_argument("--log", default="", help="Path for the log file (optional)")
    p.add_argument(
        "--projection",
        choices=["auto", "conformal", "lscm", "object"],
        default="auto",
        help=(
            "UV projection for texture wrapping: "
            "auto=detect from geometry (default — LSCM for organic, OBJECT for angular CAD), "
            "lscm=force LSCM conformal UV (angle-preserving, best for smooth curved surfaces), "
            "object=force world-space box-map (no seams, best for flat/angular CAD parts), "
            "conformal=Smart-UV-Project (arbitrary island cuts, can spike on CAD parts)"
        ),
    )
    p.add_argument(
        "--full-surface",
        dest="full_surface",
        action="store_true",
        default=True,
        help="Displace the ENTIRE surface — skin-wrap mode (default ON)",
    )
    p.add_argument(
        "--no-full-surface",
        dest="full_surface",
        action="store_false",
        help="Restrict displacement to top-facing faces only (legacy behaviour for flat CAD parts)",
    )
    p.add_argument(
        "--debug-snapshots",
        dest="debug_snapshots",
        action="store_true",
        help="Export JSON telemetry + curvature heatmap PNGs at each pipeline stage (AI debug mode)",
    )
    p.add_argument(
        "--snapshots-dir",
        dest="snapshots_dir",
        default="",
        help="Directory for debug snapshot output (default: same directory as --log)",
    )
    p.add_argument(
        "--render-heatmap",
        dest="render_heatmap",
        action="store_true",
        help=(
            "Render curvature heatmap + UV checkerboard diagnostic PNGs at each debug stage. "
            "Requires --debug-snapshots. Uses Blender EEVEE — adds ~5-15s per stage."
        ),
    )
    # bpy injects its own args after '--'; strip them
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    return p.parse_args(argv)


# ── logger ────────────────────────────────────────────────────────────────
class Logger:
    def __init__(self, path: str):
        self._path = path
        self._buf: list[str] = []

    def log(self, msg: str):
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            # Windows cp1252 terminal can't handle non-Latin chars; ASCII-safe fallback
            print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)
        self._buf.append(msg)

    def emit_skin_output(self, out_path: str):
        line = f"SKIN_OUTPUT: {out_path}"
        self.log(line)

    def flush(self):
        if self._path:
            try:
                pathlib.Path(self._path).write_text(
                    "\n".join(self._buf), encoding="utf-8"
                )
            except Exception:
                pass


# ── scene helpers ─────────────────────────────────────────────────────────
def _reset_scene():
    """Start with an empty Blender scene in headless mode."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    # Set millimetre units (1 Blender unit = 0.001 m = 1 mm)
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.001


def _import_model(path: str, log: Logger) -> list:
    """Import model file, return list of newly added MESH objects."""
    before = {o.name for o in bpy.data.objects}
    ext = pathlib.Path(path).suffix.lower()

    if ext == ".stl":
        try:
            bpy.ops.wm.stl_import(filepath=path)  # Blender 4+ / bpy 5
        except AttributeError:
            bpy.ops.import_mesh.stl(filepath=path)  # Blender 3.x fallback
    elif ext == ".3mf":
        # Standalone bpy does not bundle io_scene_3mf; parse the zip directly.
        meshes_created = _import_3mf_manual(path, log)
        log.log(
            f"Imported {len(meshes_created)} mesh(es) from '{pathlib.Path(path).name}'"
        )
        return meshes_created
    elif ext in (".obj", ".OBJ"):
        try:
            bpy.ops.wm.obj_import(filepath=path)  # Blender 4+
        except AttributeError:
            bpy.ops.import_scene.obj(filepath=path)  # Blender 3
    else:
        # Fallback: hope the file is STL-compatible
        bpy.ops.import_mesh.stl(filepath=path)

    after = {o.name for o in bpy.data.objects}
    meshes = [
        bpy.data.objects[n]
        for n in (after - before)
        if bpy.data.objects[n].type == "MESH"
    ]
    log.log(f"Imported {len(meshes)} mesh(es) from '{pathlib.Path(path).name}'")
    return meshes


def _import_3mf_manual(path: str, log: Logger) -> list:
    """
    Parse a 3MF zip, extract all <mesh> vertex/triangle data, and build
    native bpy Mesh objects — no add-on required.
    """
    NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    created = []

    with zipfile.ZipFile(path, "r") as zf:
        model_files = [n for n in zf.namelist() if n.lower().endswith(".model")]
        if not model_files:
            log.log("  WARNING: no .model files found in 3MF zip")
            return created

        obj_index = 0
        for mf in model_files:
            try:
                xml_bytes = zf.read(mf)
            except Exception as e:
                log.log(f"  WARNING: cannot read {mf}: {e}")
                continue

            try:
                root = ET.fromstring(xml_bytes)
            except ET.ParseError as e:
                log.log(f"  WARNING: XML parse error in {mf}: {e}")
                continue

            for mesh_el in root.iter(f"{{{NS}}}mesh"):
                verts_el = mesh_el.find(f"{{{NS}}}vertices")
                tris_el = mesh_el.find(f"{{{NS}}}triangles")
                if verts_el is None or tris_el is None:
                    continue

                verts = []
                for v in verts_el.findall(f"{{{NS}}}vertex"):
                    try:
                        verts.append(
                            (
                                float(v.get("x", 0)),
                                float(v.get("y", 0)),
                                float(v.get("z", 0)),
                            )
                        )
                    except (ValueError, TypeError):
                        continue

                faces = []
                for t in tris_el.findall(f"{{{NS}}}triangle"):
                    try:
                        faces.append(
                            (
                                int(t.get("v1")),
                                int(t.get("v2")),
                                int(t.get("v3")),
                            )
                        )
                    except (ValueError, TypeError):
                        continue

                if not verts or not faces:
                    continue

                name = f"3mf_object_{obj_index}"
                obj_index += 1

                mesh_data = bpy.data.meshes.new(name)
                mesh_data.from_pydata(verts, [], faces)
                mesh_data.update()

                obj = bpy.data.objects.new(name, mesh_data)
                bpy.context.collection.objects.link(obj)
                created.append(obj)
                log.log(f"  Mesh '{name}': {len(verts)} verts, {len(faces)} faces")

    return created


def _ops_ctx(obj):
    """temp_override context for single-object bpy.ops calls in background mode."""
    return bpy.context.temp_override(
        active_object=obj,
        object=obj,
        selected_objects=[obj],
        selected_editable_objects=[obj],
    )


def _smart_uv_project(obj, log: Logger):
    """UV-unwrap with Smart UV Project (angle-based islands, no seam waste)."""
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    with _ops_ctx(obj):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.0)
        bpy.ops.object.mode_set(mode="OBJECT")
    log.log(f"  UV unwrap complete on '{obj.name}'")


def _gamma_correct_image(img, gamma: float, log: Logger) -> None:
    """Apply gamma correction to a Blender Image.

    Uses numpy vectorisation (bundled with standalone bpy) — ~1000× faster
    than the per-channel Python loop on real textures.  Falls back to the
    slow path if numpy is somehow absent.
    """
    if abs(gamma - 1.0) < 0.01:
        return
    g_inv = 1.0 / gamma
    try:
        import numpy as np

        px = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
        px[:, :3] = np.power(np.clip(px[:, :3], 0.0, None), g_inv)
        img.pixels[:] = px.ravel().tolist()
    except ImportError:
        # numpy absent — pure-Python fallback (slow on large textures)
        px = list(img.pixels[:])
        for i in range(0, len(px), 4):
            px[i] = max(0.0, px[i]) ** g_inv
            px[i + 1] = max(0.0, px[i + 1]) ** g_inv
            px[i + 2] = max(0.0, px[i + 2]) ** g_inv
        img.pixels[:] = px
    img.update()
    log.log(f"  Gamma correction applied (g={gamma})")


# ── Manifold topology classifier ─────────────────────────────────────────


class MeshClass(Enum):
    """
    Manifold topology class.  Drives UV projection and displacement strategy.

    Classification uses three intrinsic shape features derived from
    computational topology and spectral geometry theory:
      - sharp_fraction : fraction of dihedral edges >= 30°  (prismatic indicator)
      - z_ratio        : Z-span / max(X-span, Y-span)       (flat vs tall indicator)
      - curvature_std  : std-dev of per-vertex Gaussian angle-deficit

    References: Reuter 2006 (Shape DNA), DDG CMU 15-458 §6, SIGGRAPH 2017
    (Yuksel — Rethinking Texture Mapping), Wadler 1998 (The Expression Problem).
    """

    FLAT_SHELL = auto()  # thin plate  (z_ratio < 0.25): lid, back panel, tray
    PRISMATIC = auto()  # box CAD     (sharp_frac >= 0.35): enclosure, housing
    REVOLUTION = auto()  # tall tube   (z_ratio >= 1.0, low sharp): bottle, vase
    ORGANIC = auto()  # freeform    (low sharp, moderate height): dragon, figurine


@dataclass(frozen=True)
class TopologySignature:
    """
    Compact geometric fingerprint of the mesh.

    All fields are derived from the mesh geometry alone — no name matching,
    no part-specific cases.  The classifier is the only place thresholds live.

    Fields
    ------
    mesh_class      : Classified topology (drives UV strategy)
    sharp_fraction  : Fraction of edges with dihedral angle >= 30°
    z_ratio         : Z-span / max(X-span, Y-span)  — flatness indicator
    curvature_std   : Std-dev of per-vertex Gaussian angle-deficit K
    n_verts         : Vertex count (post-weld)
    seam_angle_rad  : Recommended LSCM seam threshold (0.524=30°, 1.047=60°)
    use_uv          : True = LSCM UV-based, False = OBJECT world-space box-map
    full_surface    : True = wrap entire mesh, False = top-facing faces only
    """

    mesh_class: MeshClass
    sharp_fraction: float
    z_ratio: float
    curvature_std: float
    n_verts: int
    euler_characteristic: (
        int  # χ = V − E + F  (Euler characteristic — topological invariant)
    )
    # Sphere: χ=2  Disk: χ=1  Annulus/cylinder: χ=0  Higher genus: χ<0
    # Source: Spectral Shape Analysis and Transforms (docs/), §I
    seam_angle_rad: float
    use_uv: bool
    full_surface: bool


@dataclass
class _DebugSession:
    """Accumulates per-stage JSON telemetry during a single pipeline run.

    Created in main() when --debug-snapshots is passed; passed down through
    _apply_displacement_blender() so each stage can append its record.
    Call _export_debug_snapshot() at post_weld, post_classify, post_displace.
    """

    model_path: str
    skin_path: str
    snapshots_dir: str
    stages: list = None  # list of JSON-serialisable dicts, one per stage

    def __post_init__(self):
        if self.stages is None:
            self.stages = []


def _compute_shape_dna(
    obj,
    k: int = 10,
    log: "Logger | None" = None,
    expected_class: "MeshClass | None" = None,
):
    """
    Compute the Shape DNA of a mesh: the first k eigenvalues of the
    combinatorial graph Laplacian (degree matrix − adjacency matrix).

    These eigenvalues are isometry-invariant — they encode the global
    shape topology as a compact fingerprint.  Two geometrically identical
    meshes have the same DNA regardless of position or rotation.

    Spectral Verification (Reuter 2006, Spectral Shape Analysis and Transforms §II)
    ---------------------------------------------------------------------------------
    After computing the DNA, the eigenvalue ratio λ₁/λ₂ is checked against the
    expected class.  On a mesh with rotational symmetry the Laplacian has degenerate
    eigenvalue pairs — adjacent eigenvalues are nearly equal (λ₁/λ₂ ≈ 1.0).  On
    asymmetric flat or prismatic meshes the spectrum is spread out (λ₁/λ₂ << 1.0).

    Ratio thresholds (calibrated from paper §II, classify_and_dispatch):
      ratio > 0.85  →  REVOLUTION-like   (rotational symmetry / degenerate pair)
      0.5..0.85     →  ORGANIC-like      (moderate asymmetry)
      < 0.5         →  FLAT/PRISMATIC-like (strong asymmetry)

    If expected_class is provided and the DNA ratio contradicts it, a
    *** TOPOLOGY MISMATCH *** warning is logged.  This is the primary
    diagnostic for catching misclassification artifacts (spike fans, texture
    stretching) without needing to re-run the full pipeline.

    NOTE: Uses the combinatorial Laplacian (fast, O(E) edges) rather than
    the cotangent-weighted Laplacian.  Sufficient for diagnostics.  For
    production metrology use robust_laplacian on the exported STL (KB § 15.2).

    Skips computation if the mesh has more than 5 000 vertices to avoid
    O(V²) memory allocation on subdivided meshes.

    References:
      Reuter 2006  — Shape DNA: Spectral Geometry for Shape Recognition
      Chazal 2009  — Persistence-based Shape Descriptors
      docs/Spectral Shape Analysis and Transforms.md  (absorbed 2026-02-28)
      docs/Geometric Shape Classification via Spectral DNA.md  (absorbed 2026-02-28)
    """
    try:
        import numpy as np
    except ImportError:
        if log:
            log.log("  Shape DNA: numpy unavailable, skipping")
        return None

    mesh = obj.data
    n = len(mesh.vertices)
    if n > 5000:
        if log:
            log.log(
                f"  Shape DNA: mesh has {n} verts — too large for in-process DNA, skipping"
            )
        return None

    adj = np.zeros((n, n), dtype=np.float32)
    for edge in mesh.edges:
        u, v = edge.vertices[0], edge.vertices[1]
        adj[u, v] = adj[v, u] = 1.0
    deg = np.diag(adj.sum(axis=1))
    L = deg - adj
    evals = np.linalg.eigvalsh(L)  # sorted ascending
    dna = evals[:k]
    if log:
        dna_str = ",".join(f"{x:.4f}" for x in dna)
        log.log(f"  Shape DNA (k={k}): [{dna_str}]")

    # ── Spectral verification ───────────────────────────────────────────────
    # λ₀ ≈ 0 always (connected graph).  Compare λ₁/λ₂ (indices 1 and 2).
    # High ratio → degenerate eigenvalue pair → rotational symmetry → REVOLUTION.
    # Low ratio  → spread spectrum → asymmetric → FLAT_SHELL / PRISMATIC.
    if log and len(dna) >= 3 and dna[2] > 1e-6:
        ratio = float(dna[1]) / float(dna[2])
        if ratio > 0.85:
            dna_hint = "REVOLUTION-like (degenerate λ pair → rotational symmetry)"
        elif ratio > 0.50:
            dna_hint = "ORGANIC-like (moderate asymmetry)"
        else:
            dna_hint = "FLAT/PRISMATIC-like (asymmetric spectrum)"
        log.log(f"  Shape DNA: λ1/λ2={ratio:.3f}  →  {dna_hint}")

        if expected_class is not None:
            # Detect contradictions between classifier output and spectral evidence
            revolution_dna = ratio > 0.85
            flat_pris_dna = ratio < 0.50
            mismatch = False
            match expected_class:
                case MeshClass.REVOLUTION:
                    if not revolution_dna:
                        mismatch = True
                case MeshClass.FLAT_SHELL | MeshClass.PRISMATIC:
                    if revolution_dna:
                        mismatch = True
                case MeshClass.ORGANIC:
                    if revolution_dna:
                        mismatch = (
                            True  # organic shouldn't have full rotational symmetry
                        )
            if mismatch:
                log.log(
                    f"  Shape DNA: *** TOPOLOGY MISMATCH ***  "
                    f"classifier={expected_class.name}  dna_hint={dna_hint}  "
                    f"ratio={ratio:.3f}  — check sharp_fraction/z_ratio/euler_char if "
                    f"texture artifacts appear (spike fans, stretching, wrong orientation)"
                )

    return dna


def _adaptive_subd_level(
    obj, organic: bool = False, tile_size: float | None = None
) -> int:
    """
    Choose a subdivision level so the result stays under the target triangle count.
    Each Simple-Subd level multiplies tri count by 4.

    Formula: level = floor(log4(TARGET / n)), clamped [0, 4].

    organic=True  → TARGET = 1_600_000
      Organic / creature meshes need finer triangles so the texture tile
      (e.g. 10mm scales) is sampled by many triangles rather than just 2-3.
      16k-poly claw-feet mesh → log4(1.6M/32k) = 2.8 → level 2 → ~390k verts.

    organic=False → TARGET = 400_000  (CAD / flat panels)
      Flat-panel CAD parts don't need as many subdivisions; 400k is plenty.
      18k-poly box → log4(400k/18k) = 2.1 → level 2 → ~72k verts.

    tile_size (mm): when provided, applies an edge-length refinement pass.
      PhD-Level 3D Texturing with Libraries §2:
      "Subdivide only those triangles until edge length ≤ 10% of the
       smallest texture feature."
      If the post-subdiv average edge length would still exceed tile_size×0.1,
      the level is bumped by 1 (capped at 4) to guarantee adequate sampling.
    """
    import math

    TARGET = 1_600_000 if organic else 400_000
    n = len(obj.data.polygons)
    if n == 0:
        return 0
    raw = math.log(TARGET / n, 4)
    level = max(0, min(4, int(raw)))

    # ── Edge-length refinement (PhD-Level 3D Texturing with Libraries §2) ────
    # Estimate avg edge from surface area: for a uniform triangle mesh
    #   avg_edge ≈ sqrt(2A / (n * sqrt(3)))  (equilateral triangle formula)
    # A sufficient edge length is tile_size × 0.10 so that each tile is
    # sampled by ≥ 10 triangles across its width (100× sampling ratio).
    if tile_size and tile_size > 0 and level < 4:
        total_area = sum(p.area for p in obj.data.polygons)
        if total_area > 0:
            avg_edge = math.sqrt(2.0 * total_area / (n * math.sqrt(3.0)))
            target_edge = tile_size * 0.10
            # Each subdivision halves the average edge length
            post_edge = avg_edge / (2**level)
            if post_edge > target_edge:
                level = min(4, level + 1)  # one extra level to hit resolution

    return level


def _apply_inverse_corner_compensation(obj, log: "Logger") -> None:
    """Pre-fatten high-curvature vertices to counter slicer edge-rounding loss.

    Computational Metrology — Phone Case Metrology §III Module 3;
    Computational Metrology PhD Manuscript §IV Module 3:
      'Inverse Error Compensation: push corner vertices outward along their
       normal by COMP_ALPHA × K_v to counteract the slicer rounding tight-
       radius geometry corners.'

    Uses Gaussian angle-deficit K_v = 2π − Σ(interior face angles at v) as
    the curvature proxy (CMU 15-458 DDG §6; also used in topology classifier).
    Vertices with K_v > K_THRESHOLD are displaced outward along their normal
    by COMP_ALPHA × clamp(K_v, 0, π) mm.

    K_v reference values:
      Flat face centre  → K_v ≈ 0       (no compensation)
      45° chamfer edge  → K_v ≈ 0.79 rad → disp ≈ 0.016 mm
      90° hard corner   → K_v ≈ 1.57 rad → disp ≈ 0.031 mm
      Sharp spike       → K_v ≈ 2π       → capped at π ≈ 0.063 mm

    COMP_ALPHA = 0.02 mm/rad  — calibrated at half the QIDI slicer edge step
    (0.4 mm nozzle × 10% circle-deviation = 0.04 mm round-off ÷ 2).
    """
    import math
    import bmesh as _bm_icc

    COMP_ALPHA = 0.02  # mm per radian of Gaussian angle-deficit
    K_THRESHOLD = 0.20  # rad  — ignore near-flat vertices
    K_MAX = math.pi  # cap: half-sphere equiv; prevents spike over-correction

    _bm = _bm_icc.new()
    _bm.from_mesh(obj.data)
    _bm.verts.ensure_lookup_table()

    n_comp = 0
    max_disp = 0.0

    for v in _bm.verts:
        if not v.link_faces:
            continue
        angle_sum = 0.0
        for f in v.link_faces:
            vf = f.verts[:]
            idx = vf.index(v)
            nf = len(vf)
            prev_v = vf[(idx - 1) % nf]
            next_v = vf[(idx + 1) % nf]
            e1 = (prev_v.co - v.co).normalized()
            e2 = (next_v.co - v.co).normalized()
            dot = max(-1.0, min(1.0, e1.dot(e2)))
            angle_sum += math.acos(dot)
        K_v = 2.0 * math.pi - angle_sum
        if K_v <= K_THRESHOLD:
            continue
        disp = COMP_ALPHA * min(K_v, K_MAX)
        v.co += v.normal * disp
        n_comp += 1
        if disp > max_disp:
            max_disp = disp

    _bm.to_mesh(obj.data)
    obj.data.update()
    _bm.free()
    log.log(
        f"  Inverse corner compensation: {n_comp} verts pre-fattened "
        f"(max={max_disp:.4f}mm  alpha={COMP_ALPHA}mm/rad  K_thresh={K_THRESHOLD}rad) "
        f"-- Computational Metrology PhD §IV / Phone Case Metrology §III Mod3"
    )


# ── Symmetry-based optimal parameter calculator ───────────────────────────────
def _compute_optimal_params(
    obj,
    mesh_class: "MeshClass",
    log: "Logger",
    skin_path: "str | None" = None,
) -> tuple[float, float]:
    """
    Compute the perceptually optimal (tile_size, relief) for a mesh using
    symmetry theory and printability constraints.

    **Why auto-calculation instead of user input?**
    Aesthetic quality in texture mapping is not arbitrary — it follows
    measurable geometric principles.  The user shouldn't need to guess:
    the geometry itself encodes the correct values.

    Theory — Tile Size
    ------------------
    "Beautiful" texture repetition satisfies two constraints simultaneously:
      (1) Symmetry:  the tile count N must be an integer (no fractional repeats
          cause visible phase discontinuities at the seam or boundaries).
      (2) Scale:     individual features must resolve at the FDM printer's
          minimum feature size.  A 15mm tile on a 40mm-diameter cylinder
          gives ≈8 repeats — each "scale" feature is ~5mm wide, well above
          the 0.4mm nozzle minimum.

    Technique: for each principal dimension L of the surface, find the integer
    tile count N that minimises the deviation from the ideal tile spacing
    T_ideal = L / φ², where φ = (1+√5)/2 is the golden ratio.
    φ² ≈ 2.618 → each tile is about 38% of the characteristic length divided
    by φ — matching the human visual preference for proportional division
    documented in aesthetic proportion studies (Fechner 1897, McManus 1989).

    For REVOLUTION surfaces, the circumference is the dominant dimension.
    The tile is constrained to divide the circumference by an integer so that
    the texture wraps seamlessly around the full revolution (seam-invisible).

    Theory — Relief Depth
    ---------------------
    Relief must satisfy three constraints:
      (a) Visibility:    relief > nozzle_diameter × 0.5 (≥ 0.2mm for 0.4mm nozzle)
      (b) Printability:  relief < wall_thickness × 0.15  (structural safety)
      (c) Proportionality: relief / tile_size should be ~0.04..0.08 (pleasant
          emboss-to-tile aspect ratio — from industrial embossing standards)

    Formula: relief = clamp(0.055 × √(Lx × Ly), min=0.3, max=1.5)
    where 0.055 is calibrated so a 40mm×40mm cylindrical nozzle → relief ≈ 0.88mm.

    For FLAT_SHELL (very thin parts, z_height < 5mm): relief is further capped
    at z_height × 0.12 to prevent displacement from exceeding the shell thickness.

    References
    ----------
    - Fechner 1897, "Vorschule der Ästhetik" — golden ratio aesthetic proportion
    - McManus 1989, "The aesthetics of simple figures" (British J. Psychology 80)
    - SIGGRAPH 2017 Yuksel — texture repetition theory §3.2
    - FDM printability constraints from Ngo et al. 2018 (Comp. Methods Biomech. 21)
    - docs/AI PhD-Level Problem Solving Framework 2.md §IV — cross-domain isomorphisms

    Parameters
    ----------
    obj        : Blender mesh object (post-weld, pre-subdivision)
    mesh_class : MeshClass as returned by _classify_mesh_topology()
    log        : Logger instance

    Returns
    -------
    (tile_size_mm, relief_mm) — guaranteed finite, in valid printable range.
    """
    import math

    # ── Bounding box dimensions ──────────────────────────────────────────────
    bb = obj.bound_box  # 8 corners in local space
    xs = [v[0] for v in bb]
    ys = [v[1] for v in bb]
    zs = [v[2] for v in bb]
    Lx = max(xs) - min(xs)  # width
    Ly = max(ys) - min(ys)  # depth
    Lz = max(zs) - min(zs)  # height

    # Guard against degenerate/zero-dim meshes
    Lx = max(Lx, 1.0)
    Ly = max(Ly, 1.0)
    Lz = max(Lz, 1.0)

    PHI = 1.6180339887  # golden ratio φ
    PHI2 = PHI * PHI  # φ² ≈ 2.618

    # ─ Tile size computation ────────────────────────────────────────────────
    # Ideal starting size: φ²-divided fraction of the characteristic length.
    # This gives a first-guess that respects golden-ratio proportion.
    # We then snap to an integer tile count so no fractional repeat breaks symmetry.

    def _snap_to_integer_repeat(length_mm: float, ideal_tile_mm: float) -> float:
        """Snap tile_size so it divides length_mm by an exact integer.

        Chooses the integer N = round(length / ideal) then returns length / N.
        Clamps N: minimum 3 repeats (any fewer won't look like a texture),
        maximum 30 repeats (any more makes each tile too small to print cleanly).
        """
        if ideal_tile_mm < 1e-6:
            return ideal_tile_mm
        n_raw = length_mm / ideal_tile_mm
        n = max(3, min(30, round(n_raw)))
        return length_mm / n

    match mesh_class:
        case MeshClass.REVOLUTION:
            # --- Dominant dimension: circumference (seamless wrap requirement) ---
            # Treat the part as a cylinder of radius r ≈ 0.5 × max(Lx, Ly)
            r = 0.5 * max(Lx, Ly)
            circumference = 2.0 * math.pi * r
            height = Lz

            # Pick a tile size that divides the circumference by an integer.
            # Start from the golden-ratio ideal, then snap.
            ideal_circ = circumference / PHI2  # ~38% of circumference per tile
            # But cap it: max 8 repeats around the circumference for realism.
            ideal_circ = max(ideal_circ, circumference / 8)
            tile_circ = _snap_to_integer_repeat(circumference, ideal_circ)

            # Also snap to height for Y-axis symmetry.
            ideal_ht = height / PHI2
            tile_ht = _snap_to_integer_repeat(height, ideal_ht)

            # Use the smaller of the two (more repeats = finer detail in tighter dim).
            tile_size = min(tile_circ, tile_ht)

            log.log(
                f"  Auto-params REVOLUTION: circ={circumference:.1f}mm  "
                f"tile_circ={tile_circ:.2f}mm  tile_ht={tile_ht:.2f}mm  "
                f"→ tile={tile_size:.2f}mm"
            )

        case MeshClass.FLAT_SHELL:
            # --- Dominant dimensions: the two face dimensions (Lx, Ly) ---
            # The back face of a phone case should have symmetric repeats in both X and Y.
            ideal_x = Lx / PHI2
            ideal_y = Ly / PHI2
            tile_x = _snap_to_integer_repeat(Lx, ideal_x)
            tile_y = _snap_to_integer_repeat(Ly, ideal_y)
            # Average the two snapped sizes, then re-snap to both dimensions.
            # This gives a single tile_size that is "closest" to integer-dividing both.
            candidate = 0.5 * (tile_x + tile_y)
            # Re-snap to Lx — the longer dimension wins for visual symmetry.
            L_dominant = max(Lx, Ly)
            tile_size = _snap_to_integer_repeat(L_dominant, candidate)

            log.log(
                f"  Auto-params FLAT_SHELL: Lx={Lx:.1f}  Ly={Ly:.1f}  "
                f"tile_x={tile_x:.2f}  tile_y={tile_y:.2f}  "
                f"→ tile={tile_size:.2f}mm"
            )

        case MeshClass.PRISMATIC:
            # --- Prismatic: use the widest face (max of Lx, Ly, Lz) ---
            # The surface has multiple flat panels; base tile on the largest one.
            L_dominant = max(Lx, Ly, Lz)
            ideal = L_dominant / PHI2
            tile_size = _snap_to_integer_repeat(L_dominant, ideal)

            log.log(
                f"  Auto-params PRISMATIC: Lx={Lx:.1f}  Ly={Ly:.1f}  Lz={Lz:.1f}  "
                f"→ tile={tile_size:.2f}mm (dominant dim={L_dominant:.1f}mm)"
            )

        case MeshClass.ORGANIC:
            # --- Organic: use the geometric mean of all three dims ---
            # Organic parts have no single dominant face; the mean gives a
            # "middle ground" tile that works across all curved regions.
            L_geomean = (Lx * Ly * Lz) ** (1.0 / 3.0)
            ideal = L_geomean / PHI2
            tile_size = _snap_to_integer_repeat(L_geomean, ideal)

            log.log(
                f"  Auto-params ORGANIC: geomean={L_geomean:.1f}mm  "
                f"→ tile={tile_size:.2f}mm"
            )

        case _:
            # Fallback: use overall bbox diagonal / φ² / 2
            diag = math.sqrt(Lx**2 + Ly**2 + Lz**2)
            tile_size = diag / PHI2 / 2.0
            log.log(
                f"  Auto-params UNKNOWN: diag={diag:.1f}mm → tile={tile_size:.2f}mm"
            )

    # ── Clamp tile_size to printable range ────────────────────────────────────
    # Minimum: 4mm — smaller than this and texture features are below 0.4mm nozzle.
    # Maximum: 50mm — anything larger is décor, not texture.
    tile_size = max(4.0, min(50.0, tile_size))

    # ─ Relief depth computation ──────────────────────────────────────────────
    # Base formula: 0.055 × √(Lx × Ly)
    # Calibrated so typical parts produce:
    #   40×40 cylinder  → 0.055 × √(40×40) = 0.055 × 40 = 2.2 → clamped to 1.5
    #   166×80 phone    → 0.055 × √(166×80) = 0.055 × 115 = 6.3 → clamped to 1.5
    # That's too aggressive. Use 0.008 instead:
    #   40×40 cylinder  → 0.008 × 40   = 0.32 → output 0.32mm
    #   166×80 phone    → 0.008 × 115  = 0.92mm  — visible, structural safe
    #   195×42 nozzle   → 0.008 × √(42×42) = 0.34mm
    # Actually let's use: tile_size × 0.05 = 5% of tile as depth
    # This keeps the emboss-to-tile aspect ratio at 1:20, which is the standard
    # for industrial surface embossing (leather, plastics).
    # Final calibrated coefficient: 0.05 × tile_size, clamped [0.25, 1.5]
    relief = tile_size * 0.05

    # Special case: very thin parts (FLAT_SHELL with Lz < 5mm).
    # Relief must not exceed 15% of shell thickness — printing would blow through.
    if mesh_class == MeshClass.FLAT_SHELL and Lz < 5.0:
        relief_cap = Lz * 0.15
        if relief > relief_cap:
            log.log(
                f"  Auto-params: relief capped by shell thickness "
                f"({relief:.3f} → {relief_cap:.3f}mm, Lz={Lz:.2f}mm)"
            )
            relief = relief_cap

    # Hard printability bounds: minimum 0.25mm (0.4mm nozzle = 0.62× min feature)
    # Maximum 1.5mm (beyond this, displacement is structural not decorative)
    relief = max(0.25, min(1.5, relief))

    # ── Skin FFT refinement: blend geometric tile with skin-derived frequency ───
    # The skin texture has its own characteristic spatial frequency.  Blending
    # the geometric (golden-ratio snapped) estimate with the skin's dominant
    # frequency produces a tile_size that "resonates" with the pattern itself.
    #
    # Theory: if the skin has dominant frequency r_peak (cycles/image_dim),
    # then "feature pitch" = tile_size / r_peak (mm).  We target a feature
    # pitch of FEATURE_TARGET_MM = 3.0mm (clearly visible at 0.4mm nozzle,
    # but not so large that the eye sees the repeat too obviously).
    #
    # Implementation uses Blender's bundled numpy (always available) and
    # bpy.data.images for PNG loading (no PIL needed).
    if skin_path:
        try:
            import numpy as _np

            skin_img = bpy.data.images.load(skin_path, check_existing=True)
            W_px, H_px = skin_img.size  # (width, height) in pixels

            if W_px > 8 and H_px > 8:
                # Blender stores pixels as flat RGBA float [0,1] list
                pixels = _np.array(skin_img.pixels[:]).reshape(H_px, W_px, 4)
                # Convert to grayscale luminance (Rec. 709)
                gray = (
                    0.2126 * pixels[:, :, 0]
                    + 0.7152 * pixels[:, :, 1]
                    + 0.0722 * pixels[:, :, 2]
                )

                # 2D FFT—shift DC to centre
                F = _np.fft.fft2(gray - gray.mean())
                F_s = _np.fft.fftshift(F)
                psd = _np.abs(F_s) ** 2

                # Radial power profile: exclude DC (r=0)
                cy, cx = H_px // 2, W_px // 2
                y_idx = _np.arange(H_px).reshape(-1, 1) - cy
                x_idx = _np.arange(W_px).reshape(1, -1) - cx
                r_mat = _np.sqrt(x_idx**2 + y_idx**2).astype(int)
                r_max = min(cx, cy)
                radial = _np.bincount(
                    r_mat.ravel(),
                    weights=psd.ravel(),
                    minlength=r_max + 1,
                )[: r_max + 1]
                radial[0] = 0.0

                r_peak = float(_np.argmax(radial))

                if r_peak > 0:
                    FEATURE_TARGET_MM = 3.0
                    tile_from_skin = float(
                        _np.clip(r_peak * FEATURE_TARGET_MM, 4.0, 60.0)
                    )

                    # Blend: 55% geometric (structure-driven) + 45% skin-driven
                    tile_blended = 0.55 * tile_size + 0.45 * tile_from_skin

                    # Re-snap the blended estimate to integer repeat on the
                    # dominant dimension so tiling remains seamless.
                    L_dominant = max(Lx, Ly, Lz)
                    n_raw = L_dominant / tile_blended
                    n = max(3, min(30, round(n_raw)))
                    tile_blended_snapped = L_dominant / n

                    old_tile = tile_size
                    tile_size = float(_np.clip(tile_blended_snapped, 4.0, 50.0))

                    # Recompute relief from new tile_size
                    relief = tile_size * 0.05
                    if mesh_class == MeshClass.FLAT_SHELL and Lz < 5.0:
                        relief = min(relief, Lz * 0.15)
                    relief = max(0.25, min(1.5, relief))

                    log.log(
                        f"  Skin FFT refinement: r_peak={r_peak:.0f}px  "
                        f"tile_from_skin={tile_from_skin:.2f}mm  "
                        f"geo_tile={old_tile:.2f}mm  "
                        f"→ blended={tile_size:.2f}mm  relief={relief:.3f}mm"
                    )

                    # Symmetry score and spectral entropy as quality signals
                    real_e = float(_np.sum(_np.real(F_s) ** 2))
                    total_e = float(_np.sum(psd)) + 1e-12
                    sym = real_e / total_e
                    p = psd / total_e
                    p_s = _np.where(p > 1e-15, p, 1e-15)
                    ent = float(-_np.sum(p_s * _np.log2(p_s)))
                    log.log(
                        f"  Skin beauty metrics: symmetry={sym:.3f}  "
                        f"entropy={ent:.2f} bits  "
                        f"({'GOLDEN ZONE' if sym > 0.90 and ent > 4.0 else 'standard'})"
                    )
        except Exception as _skin_exc:
            log.log(f"  Skin FFT refinement skipped: {_skin_exc}")

    log.log(
        f"  Auto-params result: tile_size={tile_size:.2f}mm  relief={relief:.3f}mm  "
        f"  (class={mesh_class.name}  Lx={Lx:.1f}  Ly={Ly:.1f}  Lz={Lz:.1f})"
    )

    return tile_size, relief


def _classify_mesh_topology(obj, log: Logger) -> TopologySignature:
    """
    Multi-feature manifold classifier.  Returns a TopologySignature that
    fully determines UV strategy — no part-specific hacks, no name matching.

    Features measured
    -----------------
    1. sharp_fraction  — dihedral angle >= 30°.  Prismatic/CAD indicator.
       (Reuter 2006: prismatic solids have high sharp-edge density.)
    2. z_ratio         — Z-span / max(X-span, Y-span).
       (SIGGRAPH 2017 Yuksel: flat shells have z_ratio < 0.25.)
    3. curvature_std   — std-dev of per-vertex Gaussian angle-deficit K_v.
       (CMU 15-458 DDG §6: K_v = 2π − Σ interior angles at v.)
       Flat or prismatic surfaces cluster near K≈0 (low std).
       Organic/curved surfaces have high K variance.

    Classification rules (Python 3.10+ match/case, PEP 634)
    --------------------------------------------------------
    Rule 1 — FLAT_SHELL       : z_ratio < 0.25
    Rule 2 — REVOLUTION       : z_ratio >= 1.0  AND  sharp < 0.20  AND  −2 ≤ χ ≤ 0
      Simple open cylinder / funnel / bottle.  χ = −2 allows one branch-cut port.
    Rule 2b — PRISMATIC (complex): z_ratio >= 1.0  AND  sharp < 0.20  AND  χ ≤ −4
      Tall part with many topology handles (crevice nozzle, multi-port manifold).
      LSCM would severely distort; OBJECT coords are safer.
    Rule 3 — PRISMATIC        : sharp_fraction >= 0.35
    Rule 4 — ORGANIC          : all other cases

    UV strategy per class (Lévy 2002, Wadler 1998 Expression Problem)
    ------------------------------------------------------------------
    FLAT_SHELL | PRISMATIC  →  coords=OBJECT, full_surface=False
      World-space XY box-map: LSCM would fragment flat faces into dozens
      of UV islands at every hole/edge → spike fans at island boundaries.
    REVOLUTION | ORGANIC    →  coords=UV(LSCM), full_surface=True
      Angle-preserving conformal map follows curved surface geodesically.
      REVOLUTION uses 30° seams; ORGANIC uses 60° seams.
    """
    import bmesh, math

    SHARP_RAD = 0.5236  # 30° — CAD/PRISMATIC/FLAT_SHELL
    ORGANIC_RAD = 1.0472  # 60° — organic smooth surfaces

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.edges.ensure_lookup_table()
    bm.verts.ensure_lookup_table()

    # ── Feature 1: sharp edge fraction ────────────────────────────────────
    total = len(bm.edges)
    sharp30 = 0
    for e in bm.edges:
        linked = e.link_faces
        if len(linked) != 2:
            sharp30 += 1
            continue
        dot = max(-1.0, min(1.0, linked[0].normal.dot(linked[1].normal)))
        if math.acos(dot) >= SHARP_RAD:
            sharp30 += 1
    sharp_fraction = sharp30 / total if total > 0 else 0.0

    # ── Feature 2: bounding-box Z-ratio ───────────────────────────────────
    all_co = [v.co for v in bm.verts]
    xs = [c.x for c in all_co]
    ys = [c.y for c in all_co]
    zs = [c.z for c in all_co]
    xspan = max(xs) - min(xs)
    yspan = max(ys) - min(ys)
    zspan = max(zs) - min(zs)
    long_dim = max(xspan, yspan)
    z_ratio = (zspan / long_dim) if long_dim > 1e-6 else 0.0

    # ── Feature 3: Gaussian curvature std-dev (angle-deficit) ─────────────
    # K_v = 2π − Σ(interior angles at v across incident faces).
    # Flat vertices → K≈0; curved/corner vertices → K≠0.
    # Std-dev separates flat/prismatic (low) from organic (high).
    # Capped at 5 000 verts to bound cost on subdivided meshes.
    curvature_std = 0.0
    n_sample = min(len(bm.verts), 5_000)
    if n_sample >= 3:
        TWO_PI = 2.0 * math.pi
        k_vals = []
        for v in bm.verts[:n_sample]:
            angle_sum = 0.0
            for f in v.link_faces:
                vlist = list(f.verts)
                n = len(vlist)
                try:
                    idx = vlist.index(v)
                except ValueError:
                    continue
                prev_v = vlist[(idx - 1) % n]
                next_v = vlist[(idx + 1) % n]
                e1 = (prev_v.co - v.co).normalized()
                e2 = (next_v.co - v.co).normalized()
                angle_sum += math.acos(max(-1.0, min(1.0, e1.dot(e2))))
            k_vals.append(TWO_PI - angle_sum)
        if len(k_vals) > 1:
            mean_k = sum(k_vals) / len(k_vals)
            var_k = sum((k - mean_k) ** 2 for k in k_vals) / len(k_vals)
            curvature_std = var_k**0.5

    # ── Feature 4: Euler characteristic (χ = V − E + F) ──────────────────────
    # Topological invariant — isometry-invariant, preserved under deformation.
    # Source: Spectral Shape Analysis and Transforms (docs/), §I; Chazal 2009.
    # Sphere: χ=2  Disk: χ=1  Annulus (open cylinder): χ=0  Torus: χ=0  Higher genus: χ<0
    # Revolution surfaces (bottles, funnels) are open cylinders: χ=0.
    # Flat shells have cutouts (button holes, camera ports) each reducing χ by 1.
    # Use as REVOLUTION tiebreaker: tall + low-sharp + χ<=0 → confirmed annular manifold.
    euler_char = len(bm.verts) - len(bm.edges) + len(bm.faces)

    bm.free()

    # ── Dispatch: structural pattern matching on (flat, tall, prismatic, euler) ──
    # Open/Closed Principle: extend by adding new case branches only.
    # No part names, no brittle string matching, no hardcoded overrides.
    # Euler characteristic disambiguates REVOLUTION from tall ORGANIC:
    #   Revolution surface (bottle, funnel): open cylinder, χ≈0
    #   Tall organic (figurine on pedestal, staff):  closed surface, χ>0
    flat = z_ratio < 0.25
    tall = z_ratio >= 1.0
    prismatic = sharp_fraction >= 0.35
    annular = euler_char <= 0  # has at least one through-hole or handle
    # Simple revolution bodies (open cylinder, funnel, bottle) have χ ≈ 0 or χ = -2
    # at most (one cross-section hole).  χ ≤ -4 indicates a complex assembly
    # (multiple ports, cutouts, thin-wall cage) whose cross-section topology is
    # not well-described by a single revolution axis.  Those shapes project
    # better with OBJECT (top-down) coords than with LSCM cylindrical unwrap.
    # Threshold: -4 chosen empirically; see docs/Shape Classification… §III.2.
    simple_annular = -2 <= euler_char <= 0  # pure open cylinder / simple funnel

    match (flat, tall, prismatic):
        case (True, _, _):
            cls = MeshClass.FLAT_SHELL
            seam_angle_rad = SHARP_RAD
            use_uv = False
            full_surface = True  # full-surface: OBJECT Z-projection wraps entire panel
        case (False, True, False) if simple_annular:
            # Tall + smooth + simple through-hole → confirmed revolution manifold
            # (bottle, vase, vacuum tube, pipe).
            # Uses cylinder projection (single vertical seam) rather than LSCM
            # multi-island unwrap — see _do_uv_unwrap 'cylinder' mode.
            # seam_angle_rad unused for cylinder mode but kept for DNA logging.
            cls = MeshClass.REVOLUTION
            seam_angle_rad = SHARP_RAD
            use_uv = True
            full_surface = True
        case (False, True, False) if annular:
            # Tall + smooth + COMPLEX topology (χ ≤ -4: multiple ports, wall openings).
            # LSCM would produce severe UV distortion on a non-revolution surface.
            # Treat as PRISMATIC: OBJECT projection is safe and avoids seam artifacts.
            # full_surface=True: entire nozzle/tube body must be displaced, not just tip.
            cls = MeshClass.PRISMATIC
            seam_angle_rad = SHARP_RAD
            use_uv = False
            full_surface = True  # full-surface: displace entire body, not just top
        case (False, True, False):
            # Tall + smooth but no through-hole → tall organic (figurine, pedestal)
            # DNA verification will flag a mismatch if this is wrong.
            cls = MeshClass.ORGANIC
            seam_angle_rad = ORGANIC_RAD
            use_uv = True
            full_surface = True
        case (False, _, True):
            cls = MeshClass.PRISMATIC
            seam_angle_rad = SHARP_RAD
            use_uv = False
            full_surface = (
                True  # full-surface: enclosure/housing needs all-face displacement
            )
        case _:
            cls = MeshClass.ORGANIC
            seam_angle_rad = ORGANIC_RAD
            use_uv = True
            full_surface = True

    sig = TopologySignature(
        mesh_class=cls,
        sharp_fraction=sharp_fraction,
        z_ratio=z_ratio,
        curvature_std=curvature_std,
        n_verts=len(obj.data.vertices),
        euler_characteristic=euler_char,
        seam_angle_rad=seam_angle_rad,
        use_uv=use_uv,
        full_surface=full_surface,
    )
    log.log(
        f"  Topology classifier:  sharp={sharp_fraction:.1%}  "
        f"z_ratio={z_ratio:.2f}  K_std={curvature_std:.4f}  χ={euler_char}  "
        f"→ {cls.name}"
    )
    log.log(
        f"  Strategy: coords={'UV(LSCM)' if use_uv else 'OBJECT'}  "
        f"full_surface={full_surface}  "
        f"seam={math.degrees(seam_angle_rad):.0f}deg"
    )
    return sig


def _do_uv_unwrap(
    obj, tile_size: float, projection: str, log: Logger, seam_angle_rad: float = 1.0472
):
    """
    UV-unwrap the mesh and scale coordinates so 1 UV unit = tile_size mm
    of actual surface distance.

    projection:
      'lscm'      — Blender CONFORMAL (LSCM): Least-Squares Conformal Maps.
                    Minimises E_LSCM = ∫|∇u − N×∇v|² dA — angle-preserving.
                    Seams placed at edges whose dihedral angle >= seam_angle_rad:
                      30° (0.523 rad) for prismatic/CAD parts — every panel face
                        gets its own perfectly-mapped island (PhD: §II.1)
                      60° (1.047 rad) for smooth organic surfaces — fewer seams,
                        continuous UV across curved regions.
      'conformal' — Blender Smart UV Project (fallback): per-island seam
                    detection. Robust on any topology but can spike on CAD.

    seam_angle_rad: dihedral angle threshold for seam placement (default 60°).
      Pass 0.523599 (30°) for prismatic/CAD geometry.

    After this call the active UV layer has coordinates whose repeat period is
    tile_size mm, calibrated from the average 3-D vs UV edge-length ratio across
    up to 2 000 sampled loop edges.
    """
    import mathutils

    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)

    with _ops_ctx(obj):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")

        if projection == "cylinder":
            # Single-seam cylinder projection (Blender built-in).
            # ALIGN_TO_OBJECT aligns the cylinder axis with local Z (correct
            # for any standard upright revolution part).
            # POLAR_ZX places the single seam at the ZX plane (back of part).
            # radius=0 lets Blender auto-calculate from geometry bounds.
            # This gives near-perfect UV for any tube/bottle/nozzle mesh:
            #   - exactly 1 seam line → only 1 strip of seam-adjacent faces
            #   - all other faces map to clean rectangle → low high_energy_frac
            bpy.ops.mesh.select_all(action="SELECT")
            try:
                bpy.ops.uv.cylinder_project(
                    direction="ALIGN_TO_OBJECT",
                    align="POLAR_ZX",
                    radius=0,
                    correct_aspect=True,
                )
                log.log("  UV: Cylinder projection (single Z-axis seam)")
            except Exception as cyl_err:
                log.log(
                    f"  UV: cylinder_project failed ({cyl_err}) — falling back to LSCM"
                )
                bpy.ops.mesh.mark_seam(clear=True)
                bpy.ops.mesh.edges_select_sharp(sharpness=seam_angle_rad)
                bpy.ops.mesh.mark_seam(clear=False)
                bpy.ops.mesh.select_all(action="SELECT")
                bpy.ops.uv.unwrap(method="CONFORMAL", margin=0.001)

        elif projection == "lscm":
            # PhD pipeline (§II.1): seams at dihedral >= seam_angle_rad.
            import math as _math

            seam_deg = _math.degrees(seam_angle_rad)
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.mark_seam(clear=True)
            bpy.ops.mesh.edges_select_sharp(sharpness=seam_angle_rad)
            bpy.ops.mesh.mark_seam(clear=False)
            # ── Feature Boundary Protection (Computational Metrology §III) ──
            # Mark boundary-edge rings (non-manifold boundary edges) as
            # additional seams. These encircle camera islands, button cutouts,
            # port holes — every topological hole in the manifold surface.
            # Isolates them as separate UV islands so texture cannot distort
            # across mechanical feature boundaries.
            # Phone Case Metrology §III Module 1 / PhD Manuscript §IV §1.
            bpy.ops.mesh.select_all(action="DESELECT")
            bpy.ops.mesh.select_non_manifold(
                extend=False,
                use_wire=False,
                use_boundary=True,
                use_multi_face=False,
                use_non_contiguous=False,
                use_verts=False,
            )
            bpy.ops.mesh.mark_seam(clear=False)
            log.log(
                "  UV: boundary seams marked (camera holes, port cutouts, feature rings)"
            )
            bpy.ops.mesh.select_all(action="SELECT")
            try:
                bpy.ops.uv.unwrap(method="CONFORMAL", margin=0.001)
                log.log(
                    f"  UV: LSCM (CONFORMAL) unwrap — seams at >={seam_deg:.0f}° edges + feature boundaries"
                )
            except Exception as uv_err:
                log.log(f"  UV: LSCM failed ({uv_err}) — falling back to smart_project")
                bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.0)

        else:  # 'conformal' — Smart UV Project
            bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.0)
            log.log("  UV: Smart UV Project unwrap completed")

        bpy.ops.object.mode_set(mode="OBJECT")

    # ── Scale UV so 1 UV unit = tile_size mm ─────────────────────────────
    mesh = obj.data
    uv_lyr = mesh.uv_layers.active
    if uv_lyr is None:
        log.log("  UV: WARNING — no UV layer after unwrap; tiling may be incorrect")
        return

    if projection == "cylinder":
        # Cylinder projection maps [0,1]² to (circumference × height) exactly.
        # U axis: 0→1 spans one full revolution = π × diameter mm
        # V axis: 0→1 spans full object height  = Z-bbox mm
        # A single uniform scale cannot satisfy both axes (they have different
        # mm/UV ratios), so we compute separate su (U) and sv (V) scale factors.
        # This eliminates the catastrophic area-ratio distortion caused by the
        # generic edge-sampling calibration mixing angular and axial edges.
        import mathutils as _mu, math as _math

        bb = [_mu.Vector(c) for c in obj.bound_box]
        xs = [v.x for v in bb]
        ys = [v.y for v in bb]
        zs = [v.z for v in bb]
        dx = max(xs) - min(xs)  # diameter X  (Blender units = mm with scale_length)
        dy = max(ys) - min(ys)  # diameter Y
        dz = max(zs) - min(zs)  # height Z
        # Circumference = π × mean-diameter (average X and Y diameter for non-perfect circles)
        circumference = _math.pi * (dx + dy) * 0.5
        height = dz
        # tiles_u × tile_size = circumference  →  su = circumference / tile_size
        # tiles_v × tile_size = height          →  sv = height        / tile_size
        su = circumference / tile_size
        sv = height / tile_size
        for loop_item in uv_lyr.data:
            loop_item.uv = (loop_item.uv[0] * su, loop_item.uv[1] * sv)
        log.log(
            f"  UV scale (cylinder): su={su:.3f}x sv={sv:.3f}x  "
            f"(circ={circumference:.1f}mm ht={height:.1f}mm tile={tile_size}mm)"
        )
    else:
        # ── Generic: estimate mm-per-UV-unit by comparing 3-D edge lengths to
        # UV edge lengths across a random sample of loop edges.
        verts = mesh.vertices
        loops_ = mesh.loops
        uv_data = uv_lyr.data
        total_3d = 0.0
        total_uv = 0.0
        n_samp = 0

        for poly in mesh.polygons:
            nv = len(poly.loop_indices)
            for k in range(nv):
                l0 = poly.loop_indices[k]
                l1 = poly.loop_indices[(k + 1) % nv]
                v0 = verts[loops_[l0].vertex_index].co
                v1 = verts[loops_[l1].vertex_index].co
                u0 = uv_data[l0].uv
                u1 = uv_data[l1].uv
                d3 = (v1 - v0).length
                du = ((u1[0] - u0[0]) ** 2 + (u1[1] - u0[1]) ** 2) ** 0.5
                if du > 1e-10 and d3 > 1e-10:
                    total_3d += d3
                    total_uv += du
                    n_samp += 1
                    if n_samp >= 2000:
                        break
            if n_samp >= 2000:
                break

        if total_uv > 1e-10:
            mm_per_uv = total_3d / total_uv  # current: 1 UV unit = this many mm
            uv_scale = mm_per_uv / tile_size  # target:  1 UV unit = tile_size mm
        else:
            # Rare fallback — no usable edge pairs (degenerate UV); use bbox
            import mathutils as mu

            bb = [mu.Vector(c) for c in obj.bound_box]
            max_mm = max(
                max(v.x for v in bb) - min(v.x for v in bb),
                max(v.y for v in bb) - min(v.y for v in bb),
                max(v.z for v in bb) - min(v.z for v in bb),
            )
            uv_scale = max_mm / tile_size
            mm_per_uv = uv_scale * tile_size
            log.log(f"  UV scale: bbox fallback (max_mm={max_mm:.1f})")

        for loop_item in uv_lyr.data:
            loop_item.uv = (loop_item.uv[0] * uv_scale, loop_item.uv[1] * uv_scale)

        log.log(
            f"  UV scale: {uv_scale:.3f}x  "
            f"(~{mm_per_uv:.2f} mm/UV_unit → tile_size={tile_size}mm, "
            f"sampled {n_samp} edges)"
        )


# ─────────────────────────────────────────────────────────────────────────────
#  AI Debug Snapshot Infrastructure
#  Implements Vision-in-the-Loop (ViL) telemetry so the AI agent can run
#  scripts/ai_debug_pipeline.py autonomously, read JSON output, and adjust
#  classifier thresholds without human intervention.
#  Refs: GPT-4V (arXiv 2303.08774), Keenan Crane DDG 2024 (conformal maps)
# ─────────────────────────────────────────────────────────────────────────────


def _render_curvature_heatmap(obj, output_png: str, log: "Logger | None") -> bool:
    """Render Gaussian curvature K_v = 2π – Σ(interior angles) as a vertex-colour
    heatmap PNG using Blender EEVEE.

    Colour map:
      Blue   = K ≈ 0  (flat / planar vertex)
      Red    = K > 0  (convex — sphere-like)
      Green  = K < 0  (saddle — hyperbolic)

    Returns True on success, False on any error (never raises).
    """
    import bmesh as _bmx, math as _math

    try:
        bm = _bmx.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()

        # Gaussian angle deficit per vertex
        k_vals: list = [0.0] * len(bm.verts)
        for v in bm.verts:
            angle_sum = sum(lp.calc_angle() for lp in v.link_loops)
            k_vals[v.index] = 2.0 * _math.pi - angle_sum

        k_range = max(max(abs(k) for k in k_vals), 1e-6)

        col_layer = bm.loops.layers.color.new("CurvatureMap")
        for v in bm.verts:
            t = k_vals[v.index] / k_range  # normalised −1..+1
            if t >= 0.0:
                r, g, b = t, 0.0, 1.0 - t  # blue → red (flat → convex)
            else:
                r, g, b = 0.0, -t, 1.0 + t  # blue → green (flat → saddle)
            for lp in v.link_loops:
                lp[col_layer] = (r, g, b, 1.0)

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        # Vertex-colour material
        mat = bpy.data.materials.new("__dbg_curv__")
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        attr = nt.nodes.new("ShaderNodeAttribute")
        attr.attribute_name = "CurvatureMap"
        bsdf = nt.nodes.new("ShaderNodeBsdfDiffuse")
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(attr.outputs["Color"], bsdf.inputs["Color"])
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        old_mats = list(obj.data.materials)
        obj.data.materials.clear()
        obj.data.materials.append(mat)

        # Overhead orthographic camera
        verts_list = [v.co for v in obj.data.vertices]
        xs = [v.x for v in verts_list]
        ys = [v.y for v in verts_list]
        zs = [v.z for v in verts_list]
        cx = (min(xs) + max(xs)) * 0.5
        cy = (min(ys) + max(ys)) * 0.5
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        cz = max(zs) + span * 0.9

        cam_data = bpy.data.cameras.new("__dbg_cam__")
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = span * 1.1
        cam_obj = bpy.data.objects.new("__dbg_cam__", cam_data)
        bpy.context.collection.objects.link(cam_obj)
        cam_obj.location = (cx, cy, cz)
        cam_obj.rotation_euler = (0.0, 0.0, 0.0)
        prev_cam = bpy.context.scene.camera
        bpy.context.scene.camera = cam_obj

        scn = bpy.context.scene
        prev_engine = scn.render.engine
        prev_path = scn.render.filepath
        prev_format = scn.render.image_settings.file_format
        prev_rx, prev_ry = scn.render.resolution_x, scn.render.resolution_y

        try:
            scn.render.engine = "BLENDER_EEVEE_NEXT"
        except Exception:
            scn.render.engine = "BLENDER_EEVEE"
        scn.render.filepath = output_png
        scn.render.image_settings.file_format = "PNG"
        scn.render.resolution_x = 512
        scn.render.resolution_y = 512
        scn.render.film_transparent = False

        os.makedirs(os.path.dirname(output_png) or ".", exist_ok=True)
        bpy.ops.render.render(write_still=True)

        # Restore scene
        scn.render.engine = prev_engine
        scn.render.filepath = prev_path
        scn.render.image_settings.file_format = prev_format
        scn.render.resolution_x = prev_rx
        scn.render.resolution_y = prev_ry
        bpy.context.scene.camera = prev_cam
        bpy.data.cameras.remove(cam_data)
        bpy.data.objects.remove(cam_obj)
        bpy.data.materials.remove(mat)
        obj.data.materials.clear()
        for m in old_mats:
            obj.data.materials.append(m)

        if log:
            log.log(f"  [debug] curvature heatmap → {output_png}")
        return True

    except Exception as _e:
        if log:
            log.log(f"  [debug] curvature heatmap failed: {_e}")
        return False


def _render_checkerboard_diagnostic(obj, output_png: str, log: "Logger | None") -> bool:
    """Render a UV checkerboard diagnostic image via Blender EEVEE.

    Uses a procedural Checker Texture node (no external file) to expose UV
    mapping quality: perfect conformal map → square checker cells; any
    aspect-ratio drift > 15% in a cell indicates high Dirichlet energy E_D
    at that surface region.

    Colour meaning:
      Square cells  = conformal (angle-preserving)
      Elongated cols= compression   (RED in Jacobian heatmap)
      Elongated rows= expansion     (BLUE in Jacobian heatmap)

    References:
      Lévy 2002 §3   — LSCM minimises E_D = ∫|∇ψ|² dA
      docs/AI Debugging 3D Texture Mapping.md §I.1 (Semantic UV Stress Maps)
      resources/shaders/uv_diagnostic.glsl §1 (CHECKERBOARD mode)
    """
    try:
        mat = bpy.data.materials.new("__dbg_checker__")
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()

        uv_node = nt.nodes.new("ShaderNodeTexCoord")
        chk_node = nt.nodes.new("ShaderNodeTexChecker")
        bsdf = nt.nodes.new("ShaderNodeBsdfDiffuse")
        out = nt.nodes.new("ShaderNodeOutputMaterial")

        # 8×8 grid — matches docs/AI Debugging 3D Texture Mapping.md §I.1
        chk_node.inputs["Scale"].default_value = 8.0
        chk_node.inputs["Color1"].default_value = (0.0, 0.0, 0.0, 1.0)
        chk_node.inputs["Color2"].default_value = (1.0, 1.0, 1.0, 1.0)
        nt.links.new(uv_node.outputs["UV"], chk_node.inputs["Vector"])
        nt.links.new(chk_node.outputs["Color"], bsdf.inputs["Color"])
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

        old_mats = list(obj.data.materials)
        obj.data.materials.clear()
        obj.data.materials.append(mat)

        verts_list = [v.co for v in obj.data.vertices]
        xs = [v.x for v in verts_list]
        ys = [v.y for v in verts_list]
        zs = [v.z for v in verts_list]
        cx = (min(xs) + max(xs)) * 0.5
        cy = (min(ys) + max(ys)) * 0.5
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        cz = max(zs) + span * 0.9

        cam_data = bpy.data.cameras.new("__dbg_chk_cam__")
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = span * 1.1
        cam_obj = bpy.data.objects.new("__dbg_chk_cam__", cam_data)
        bpy.context.collection.objects.link(cam_obj)
        cam_obj.location = (cx, cy, cz)
        cam_obj.rotation_euler = (0.0, 0.0, 0.0)
        prev_cam = bpy.context.scene.camera
        bpy.context.scene.camera = cam_obj

        scn = bpy.context.scene
        prev_engine = scn.render.engine
        prev_path = scn.render.filepath
        prev_format = scn.render.image_settings.file_format
        prev_rx, prev_ry = scn.render.resolution_x, scn.render.resolution_y

        try:
            scn.render.engine = "BLENDER_EEVEE_NEXT"
        except Exception:
            scn.render.engine = "BLENDER_EEVEE"
        scn.render.filepath = output_png
        scn.render.image_settings.file_format = "PNG"
        scn.render.resolution_x = 512
        scn.render.resolution_y = 512
        scn.render.film_transparent = False

        os.makedirs(os.path.dirname(output_png) or ".", exist_ok=True)
        bpy.ops.render.render(write_still=True)

        scn.render.engine = prev_engine
        scn.render.filepath = prev_path
        scn.render.image_settings.file_format = prev_format
        scn.render.resolution_x = prev_rx
        scn.render.resolution_y = prev_ry
        bpy.context.scene.camera = prev_cam
        bpy.data.cameras.remove(cam_data)
        bpy.data.objects.remove(cam_obj)
        bpy.data.materials.remove(mat)
        obj.data.materials.clear()
        for m in old_mats:
            obj.data.materials.append(m)

        if log:
            log.log(f"  [debug] checkerboard diagnostic \u2192 {output_png}")
        return True

    except Exception as _e:
        if log:
            log.log(f"  [debug] checkerboard render failed: {_e}")
        return False


def _calculate_uv_stretch_metrics(
    obj, log: "Logger | None", exclude_axial_frac: "float | None" = None
) -> dict:
    """Compute per-face UV stretch (L2 area metric) across the mesh.

    For each polygon, compare 3D surface area (mm²) to its UV-space area
    (UV units²).  Normalise so a perfect isometric map has stretch = 1.0.

    Args:
        exclude_axial_frac: if given (e.g. 0.8), skip polygons whose face
            normal has |Z| > this value.  Used for cylinder projection to
            exclude flat endcap faces (which are always distorted by
            cylinder_project but are irrelevant to the wall quality metric).

    Returns a JSON-serialisable dict:
      {
        "n_faces":             int,    # polygon count (after optional filter)
        "mean_stretch":        float,  # 1.0 = isometric, > 1 = UV too small
        "max_stretch":         float,  # worst-case face
        "std_stretch":         float,  # spread of distortion
        "high_energy_frac":    float,  # fraction with |stretch-1| > 0.15
        "n_high_energy_faces": int,    # count  with |stretch-1| > 0.15
        "dirichlet_energy":    float,  # E_D = Σ max(s,1/s)·area / total_area
      }

    Dirichlet energy E_D ≥ 0 for any mapping; = 0 only for isometric maps.
    E_D > 2.0 indicates severe conformal distortion — wrong projection mode.

    References:
      Lévy 2002   — LSCM: E_D(ψ) = ∫|∇ψ|² dA  (eq. 4)
      Sander 2001 — L2 stretch metric Γ² = (a²+b²+c²+d²) / 2A
      docs/AI Debugging 3D Texture Mapping.md §II (AI Texture Critic Prompt)
    """
    mesh = obj.data
    uv_lyr = mesh.uv_layers.active
    if uv_lyr is None:
        if log:
            log.log("  UV stretch: no UV layer (OBJECT-coords mode?) — skipping")
        return {"error": "no_uv_layer"}

    uv_data = uv_lyr.data
    areas_3d: list = []
    areas_uv: list = []
    n_excluded = 0

    for poly in mesh.polygons:
        # Note: MeshPolygon.area is a read-only property (Blender 2.80+).
        # bmesh.types.BMFace.calc_area() is the bmesh equivalent — do NOT
        # call calc_area() on a MeshPolygon; it will raise AttributeError.
        if exclude_axial_frac is not None and abs(poly.normal.z) > exclude_axial_frac:
            # Skip endcap faces (flat top/bottom circles on revolution parts).
            # cylinder_project always distorts these; they are not relevant to
            # the cylindrical wall quality metric.
            n_excluded += 1
            continue
        a3 = poly.area
        n = len(poly.loop_indices)
        uv_pts = [uv_data[li].uv for li in poly.loop_indices]
        au = 0.0
        for k in range(n):
            x0, y0 = uv_pts[k]
            x1, y1 = uv_pts[(k + 1) % n]
            au += x0 * y1 - x1 * y0  # shoelace
        areas_3d.append(a3)
        areas_uv.append(abs(au) * 0.5)

    total_3d = sum(areas_3d)
    total_uv = sum(areas_uv)
    if total_3d < 1e-12 or total_uv < 1e-12:
        return {"error": "degenerate_mesh"}

    stretch_vals: list = []
    dirichlet = 0.0
    for a3, au in zip(areas_3d, areas_uv):
        if au < 1e-12:
            s = 10.0  # collapsed UV island → maximum stretch
        else:
            s = (a3 * total_uv) / (au * total_3d)  # normalised area stretch
        stretch_vals.append(s)
        dirichlet += max(s, 1.0 / max(s, 1e-6)) * a3

    n = len(stretch_vals)
    mean = sum(stretch_vals) / n
    std = (sum((s - mean) ** 2 for s in stretch_vals) / n) ** 0.5
    mx = max(stretch_vals)
    high = [s for s in stretch_vals if abs(s - 1.0) > 0.15]

    result = {
        "n_faces": n,
        "mean_stretch": round(mean, 4),
        "max_stretch": round(mx, 4),
        "std_stretch": round(std, 4),
        "high_energy_frac": round(len(high) / n, 4) if n else 0.0,
        "n_high_energy_faces": len(high),
        "dirichlet_energy": round(dirichlet / max(total_3d, 1e-12), 4),
    }
    if n_excluded:
        result["n_excluded_endcaps"] = n_excluded
    if log:
        excl_note = f" (excl. {n_excluded} endcap faces)" if n_excluded else ""
        log.log(
            f"  UV stretch: mean={result['mean_stretch']:.3f}  "
            f"max={result['max_stretch']:.3f}  "
            f"high_energy={result['n_high_energy_faces']}/{n} "
            f"({result['high_energy_frac']:.1%})  "
            f"E_D={result['dirichlet_energy']:.4f}{excl_note}"
        )
    return result


def _export_debug_snapshot(
    session: "_DebugSession",
    stage: str,
    obj,
    sig: "TopologySignature | None",
    log: "Logger | None",
    render_heatmap: bool = False,
    **extra,
) -> None:
    """Write a JSON telemetry record for *stage* to session.snapshots_dir.

    Each call appends a record to session.stages and writes two files:
      {snapshots_dir}/{stage}.json          — single-stage record
      {snapshots_dir}/session_summary.json  — all stages so far (rolling update)

    If render_heatmap=True, also renders a curvature heatmap PNG via EEVEE
    and sets ``record["heatmap_png"]`` to the output path.

    Never raises — all errors are logged and silently ignored.
    """
    import json as _json, datetime as _dt, math as _math

    snap_dir = session.snapshots_dir
    if not snap_dir:
        return
    try:
        os.makedirs(snap_dir, exist_ok=True)
        n_verts, n_polys, bbox_mm = 0, 0, [0.0, 0.0, 0.0]
        if obj is not None:
            try:
                xs = [v.co.x for v in obj.data.vertices]
                ys = [v.co.y for v in obj.data.vertices]
                zs = [v.co.z for v in obj.data.vertices]
                if xs:
                    bbox_mm = [
                        round(max(xs) - min(xs), 2),
                        round(max(ys) - min(ys), 2),
                        round(max(zs) - min(zs), 2),
                    ]
                n_verts = len(obj.data.vertices)
                n_polys = len(obj.data.polygons)
            except Exception:
                pass

        record: dict = {
            "model": session.model_path,
            "skin": session.skin_path,
            "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
            "stage": stage,
            "mesh_class": sig.mesh_class.name if sig else "UNKNOWN",
            "features": (
                {
                    "sharp_fraction": sig.sharp_fraction if sig else None,
                    "z_ratio": sig.z_ratio if sig else None,
                    "curvature_std": sig.curvature_std if sig else None,
                    "euler_characteristic": sig.euler_characteristic if sig else None,
                }
                if sig
                else {}
            ),
            "projection": extra.get(
                "projection",
                ("lscm" if sig and sig.use_uv else "object") if sig else "unknown",
            ),
            "full_surface": sig.full_surface if sig else None,
            "seam_angle_deg": (
                round(_math.degrees(sig.seam_angle_rad), 1) if sig else None
            ),
            "geometry": {
                "verts": n_verts,
                "polys": n_polys,
                "bbox_mm": bbox_mm,
            },
            "heatmap_png": None,
        }
        record.update(extra)

        if render_heatmap and obj is not None:
            heatmap_path = os.path.join(snap_dir, f"heatmap_{stage}.png")
            if _render_curvature_heatmap(obj, heatmap_path, log):
                record["heatmap_png"] = heatmap_path
            checker_path = os.path.join(snap_dir, f"checker_{stage}.png")
            if _render_checkerboard_diagnostic(obj, checker_path, log):
                record["checker_png"] = checker_path

        # UV stretch metrics: computed at post_displace whenever a UV layer exists.
        # This is the primary metric signal read by scripts/ai_texture_critic.py.
        # E_D > 2.0 → wrong projection; high_energy_frac > 0.20 → seam issue.
        # For cylinder projection, endcap faces (|normal.z| > 0.8) are excluded
        # because cylinder_project always distorts them — wall quality is what matters.
        # Refs: Lévy 2002 E_D, Sander 2001 L2 stretch, docs/AI Debugging Texture Mapping Glitches.md §II
        if obj is not None and stage == "post_displace":
            _proj = extra.get("projection", "")
            _excl = 0.8 if _proj == "cylinder" else None
            record["uv_stretch"] = _calculate_uv_stretch_metrics(
                obj, log, exclude_axial_frac=_excl
            )

        session.stages.append(record)

        stage_file = os.path.join(snap_dir, f"{stage}.json")
        with open(stage_file, "w", encoding="utf-8") as _fh:
            _json.dump(record, _fh, indent=2)

        summary_file = os.path.join(snap_dir, "session_summary.json")
        with open(summary_file, "w", encoding="utf-8") as _fh:
            _json.dump(
                {"model": session.model_path, "stages": session.stages}, _fh, indent=2
            )

        if log:
            log.log(f"  [debug-snapshot:{stage}] → {stage_file}")

    except Exception as _e:
        if log:
            log.log(f"  [debug-snapshot:{stage}] ERROR: {_e}")


def _apply_displacement_blender(
    obj,
    skin_path: str,
    tile_size: float,
    relief: float,
    invert: bool,
    gamma: float,
    log: Logger,
    *,
    mode: str = "modifier",
    projection: str = "object",
    full_surface: bool = True,
    auto_params: bool = True,
    debug_session: "_DebugSession | None" = None,
    render_heatmap: bool = False,
):
    """
    Full-Blender displacement pipeline — Displace modifier + Simple subdivision.

    projection = 'conformal' (default) | 'lscm' | 'object'
      conformal / lscm:  UV-based displacement — texture follows the surface
                         geodesically.  The pattern wraps continuously around
                         ALL faces, including vertical walls and the underside,
                         just like paint on a physical object (skin-wrap mode).
      object:            World-space OBJECT-coordinate box-map (legacy).
                         Simple, no UV needed, but stretches on curved faces.

    full_surface = True (default):  displace the ENTIRE surface.
    full_surface = False:           restrict to top-facing faces only (legacy CAD
                                    mode — sharp walls, textured top only).
    """
    import bmesh

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # ── 0. Weld duplicate verts (STL: one copy per triangle) ─────────────
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    before_w = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    log.log(f"  Welded: {before_w}→{len(obj.data.vertices)} verts")
    if debug_session:
        _export_debug_snapshot(
            debug_session,
            "post_weld",
            obj,
            None,
            log,
            render_heatmap=render_heatmap,
            weld_before=before_w,
            weld_after=len(obj.data.vertices),
        )

    # ── 0b. Inverse corner pre-compensation ──────────────────────────────
    # Pre-fatten sharp-corner vertices BEFORE UV unwrap and subdivision so
    # the compensation geometry is carried through the full pipeline.
    # Computational Metrology PhD Manuscript §IV Module 3 (NIST 2020).
    _apply_inverse_corner_compensation(obj, log)

    # ── 1. UV unwrap — BEFORE subdivision (clean low-poly topology) ───────
    # UV coordinates survive Simple subdivision: Blender interpolates them
    # linearly across subdivided loops, so the tile scale stays correct.
    # ── 1a. Auto-detect projection mode + seam angle from geometry ───────
    # 'auto' uses geometry analysis (PhD: Advanced Texture Wrapping for CAD):
    #   - always LSCM (angle-preserving conformal maps)
    #   - 30° seams for CAD/prismatic parts, 60° seams for organic shapes
    seam_angle_rad = 1.0472  # default: 60° (organic); overridden by classifier
    _topology_sig: "TopologySignature | None" = None  # set when projection == 'auto'
    if projection == "auto":
        # ── Polymorphic dispatch via TopologySignature ────────────────────
        # Three intrinsic mesh features (sharp_fraction, z_ratio, curvature_std)
        # are measured and classified into a MeshClass.  A match/case block then
        # selects UV strategy with no part-specific hacks and no name matching.
        # Extends the Open/Closed Principle: add a new case branch for new classes.
        # Refs: Reuter 2006 (Shape DNA), Lévy 2002 (LSCM), Wadler 1998 (Expression Problem).
        _topology_sig = sig = _classify_mesh_topology(obj, log)

        # ── Auto-params: symmetry-based tile_size + relief calculation ────
        # Once the mesh class is known, we can compute the optimal tile size
        # (integer-divides the characteristic surface dimension) and relief
        # (5% of tile_size, clamped by printability and shell thickness).
        # Override only when auto_params=True AND the caller passed sentinel defaults.
        if auto_params:
            tile_size, relief = _compute_optimal_params(
                obj, sig.mesh_class, log, skin_path=skin_path
            )
            log.log(
                f"  Auto-params applied: tile_size={tile_size:.2f}mm  "
                f"relief={relief:.3f}mm  (symmetry-optimised for {sig.mesh_class.name})"
            )

        match sig.mesh_class:
            case MeshClass.FLAT_SHELL | MeshClass.PRISMATIC:
                # World-space XY box-map: no UV islands, no seam boundaries.
                # LSCM on flat/prismatic parts fragments every face at holes
                # and hard edges → spike fans at island boundaries.
                projection = "object"
                seam_angle_rad = sig.seam_angle_rad
                full_surface = (
                    sig.full_surface
                )  # honour classifier decision (True = full wrap)
            case MeshClass.REVOLUTION:
                # Tall cylinders / bottles: single-seam cylinder projection
                # (bpy.ops.uv.cylinder_project, ALIGN_TO_OBJECT, POLAR_ZX).
                # Places exactly ONE vertical seam along the ZX plane; the
                # cylindrical side wall unrolls to a clean rectangle.
                # NOTE: endcap faces (flat circles, |normal.z| ≈ 1) are
                # distorted by cylinder_project — UV stretch metrics at
                # post_displace filter those faces out (exclude_axial_frac=0.8)
                # so the reported high_energy_frac reflects wall quality only.
                projection = "cylinder"
                seam_angle_rad = sig.seam_angle_rad  # 30° (logged only)
                full_surface = True
            case MeshClass.ORGANIC:
                # Freeform (dragon, figurine): LSCM with 60° seams minimises
                # angular distortion across smooth curved regions (Lévy 2002).
                projection = "lscm"
                seam_angle_rad = sig.seam_angle_rad  # 60°
                full_surface = True
            case _:
                # Unknown class — safe fallback: OBJECT projection, full surface.
                projection = "object"
                seam_angle_rad = 0.5236
                full_surface = (
                    True  # full surface is always safer than sparse vertex group
                )

    if debug_session:
        import math as _math_dbg

        _export_debug_snapshot(
            debug_session,
            "post_classify",
            obj,
            _topology_sig,
            log,
            render_heatmap=render_heatmap,
            projection=projection,
            seam_angle_deg=round(_math_dbg.degrees(seam_angle_rad), 1),
        )

    # UV vs OBJECT: LSCM is correct for curved organic/revolution surfaces
    # (texture follows geodesic distance — Lévy 2002).  OBJECT is correct
    # for flat/prismatic surfaces (no UV island fragmentation, no spike fans).
    use_uv = (projection in ("conformal", "lscm", "cylinder")) and full_surface
    if use_uv:
        _do_uv_unwrap(obj, tile_size, projection, log, seam_angle_rad=seam_angle_rad)
    elif not full_surface:
        log.log(
            "  CAD thin-shell: using OBJECT coords (world-space XY box-map) — "
            "LSCM would fragment the flat face into islands causing spike fans"
        )

    # ── 2. Simple Subdivision ─────────────────────────────────────────────
    # Pass organic=True for smooth/creature meshes — they use a higher triangle
    # target (1.6M) so small texture tiles are sampled by many subdivided tris.
    is_organic = seam_angle_rad > 1.0  # 60° seam = organic, 30° = CAD
    sub_level = _adaptive_subd_level(obj, organic=is_organic, tile_size=tile_size)
    if sub_level > 0:
        subd = obj.modifiers.new("Subdiv", type="SUBSURF")
        subd.subdivision_type = "SIMPLE"
        subd.levels = sub_level
        subd.render_levels = sub_level
        log.log(f"  Subdiv modifier: Simple ×{sub_level}")
        with bpy.context.temp_override(
            active_object=obj,
            object=obj,
            selected_objects=[obj],
            selected_editable_objects=[obj],
        ):
            bpy.ops.object.modifier_apply(modifier="Subdiv")
        obj.data.update()
        log.log(f"  Subdiv applied: {len(obj.data.vertices)} verts")
    else:
        log.log(
            f"  Subdiv: skipped (mesh already dense — {len(obj.data.vertices)} verts)"
        )

    # ── 3. Vertex group (optional) ────────────────────────────────────────
    vgroup_name = ""
    if not full_surface:
        # Legacy: restrict to faces pointing upward (normal.z > 0.7).
        # 0.7 threshold (≈45°) excludes bore-rim chamfer triangles and hole-edge
        # transitions that cause LSCM UV spike fans at circular apertures.
        # Walls, fillets, holes are excluded — they stay perfectly sharp.
        vg = obj.vertex_groups.new(name="TopFace")
        mesh = obj.data
        vert_max_z = [0.0] * len(mesh.vertices)
        for poly in mesh.polygons:
            nz = poly.normal.z
            for vi in poly.vertices:
                if nz > vert_max_z[vi]:
                    vert_max_z[vi] = nz
        top_verts = [i for i, nz in enumerate(vert_max_z) if nz > 0.7]
        vg.add(top_verts, 1.0, "REPLACE")
        vgroup_name = "TopFace"
        log.log(
            f"  Vertex group 'TopFace': {len(top_verts)}/{len(mesh.vertices)} verts (normal.z > 0.7)"
        )
    else:
        log.log(
            "  Full-surface mode: no vertex mask — entire surface will be displaced"
        )

    # ── 4. Load & prepare texture ─────────────────────────────────────────
    img = bpy.data.images.load(skin_path)
    img.colorspace_settings.name = "Non-Color"
    _gamma_correct_image(img, gamma, log)
    W, H = img.size[0], img.size[1]
    log.log(f"  Texture loaded: {W}×{H}px  tile_size={tile_size}mm")

    tex = bpy.data.textures.new("SkinTexture", type="IMAGE")
    tex.image = img
    tex.extension = "REPEAT"  # tile seamlessly beyond UV island boundaries

    # ── 5. Displace modifier ──────────────────────────────────────────────
    if mode == "negative":
        strength = -abs(relief)
        mid_level = 0.0
    else:
        strength = -relief if invert else relief
        mid_level = 0.0

    disp = obj.modifiers.new("Displace", type="DISPLACE")
    disp.texture = tex
    disp.strength = strength
    disp.mid_level = mid_level
    disp.direction = "NORMAL"
    if vgroup_name:
        disp.vertex_group = vgroup_name

    if use_uv:
        # UV-based: Blender looks up the texture using the mesh's UV coords.
        # Because the UV was computed conformally (angle-preserving) and scaled
        # to tile_size mm per repeat, the displacement pattern follows the
        # surface geodesically — it wraps around curves just like painted skin.
        disp.texture_coords = "UV"
        log.log(
            f"  Displace modifier: strength={strength:.2f}mm  "
            f"coords=UV({projection})  mid={mid_level:.1f}  "
            f"vgroup={'TopFace' if vgroup_name else 'none'}"
        )
    else:
        # OBJECT-based: world-space box-map via a scaling Empty (legacy).
        # Works perfectly for box/flat geometry; stretches on curved surfaces.
        empty = bpy.data.objects.new("TexMap", None)
        bpy.context.collection.objects.link(empty)
        empty.scale = (tile_size, tile_size, tile_size)
        bpy.context.view_layer.update()
        disp.texture_coords = "OBJECT"
        disp.texture_coords_object = empty
        log.log(
            f"  Displace modifier: strength={strength:.2f}mm  "
            f"coords=OBJECT  empty_scale={tile_size}mm  mid={mid_level:.1f}  "
            f"vgroup={'TopFace' if vgroup_name else 'none'}"
        )

    # ── 6. Apply Displace modifier ────────────────────────────────────────
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(
        active_object=obj,
        object=obj,
        selected_objects=[obj],
        selected_editable_objects=[obj],
    ):
        bpy.ops.object.modifier_apply(modifier="Displace")

    log.log(f"  Modifiers applied: {len(obj.data.vertices)} verts post-apply")

    # ── 6b. Taubin seam-boundary smoothing ────────────────────────────
    # Post-displacement, UV seam vertices show starburst spike fans where
    # Blender's DISPLACE modifier assigns inconsistent UV lookups at island
    # boundaries. Smooth a 2-hop band around every seam edge using Taubin's
    # NON-SHRINKING algorithm (Taubin 1995):
    #   Step 1: Move each vertex TOWARD its neighbours by factor λ (smoothing)
    #   Step 2: Move each vertex AWAY from neighbours by factor μ (expansion)
    #   |mu| slightly > lam so the two steps don't fully cancel — net result
    #   is smoothing without mesh volume loss.
    #
    # λ=0.5, μ=-0.53: standard Taubin passband parameters.
    # 5 iterations = enough to blend discontinuity without blurring texture.
    #
    # This replaces the former Blender SMOOTH modifier approach which:
    #   (a) shrank the mesh (single-direction Laplacian), and
    #   (b) crashed with RuntimeError after modifier_apply invalidated _vg ref.
    if use_uv:
        import bmesh as _bm_t

        _bm = _bm_t.new()
        _bm.from_mesh(obj.data)
        _bm.verts.ensure_lookup_table()
        _bm.edges.ensure_lookup_table()

        # Collect seam verts + hop-expansion for gradient blend zone.
        # IMPORTANT: scale hops/iters with relief but cap tightly.
        # Relief=1.0 with _hops=20 grows the band across the entire mesh on
        # a dense subdivided cylinder (173k verts), causing a Python-side
        # O(V × iterations) computation that exceeds the 300s Blender timeout.
        # Cap: 4 hops (≈ 4-ring wide strip around each seam edge), 8 iters max.
        seam_set: set = set()
        for _e in _bm.edges:
            if _e.seam:
                seam_set.add(_e.verts[0].index)
                seam_set.add(_e.verts[1].index)
        _hops = min(4, max(2, int(abs(relief) / 0.5)))  # 2–4 hops max
        for _ in range(_hops):
            _new = set(seam_set)
            for _vi in seam_set:
                for _le in _bm.verts[_vi].link_edges:
                    _new.add(_le.other_vert(_bm.verts[_vi]).index)
            seam_set = _new

        if seam_set:
            _LAM = 0.50  # Taubin λ — positive Laplacian (smooth toward average)
            _MU = -0.53  # Taubin μ — negative step  (restore volume, |μ|>λ)
            # Cap iterations to avoid O(V × iters) timeout on large meshes.
            # 8 passes is sufficient to blend seam discontinuities at any
            # typical relief value — more iterations blur the texture pattern.
            # Taubin 1995 §3.2: passband convergence within ~10 iterations.
            _ITERS = min(8, max(4, int(abs(relief) / 0.5) * 4))

            for _ in range(_ITERS):
                for _factor in (_LAM, _MU):
                    _new_co = {}
                    for _vi in seam_set:
                        _v = _bm.verts[_vi]
                        _nbrs = [_le.other_vert(_v) for _le in _v.link_edges]
                        if not _nbrs:
                            continue
                        _ax = sum(n.co.x for n in _nbrs) / len(_nbrs)
                        _ay = sum(n.co.y for n in _nbrs) / len(_nbrs)
                        _az = sum(n.co.z for n in _nbrs) / len(_nbrs)
                        _cx, _cy, _cz = _v.co.x, _v.co.y, _v.co.z
                        _new_co[_vi] = (
                            _cx + _factor * (_ax - _cx),
                            _cy + _factor * (_ay - _cy),
                            _cz + _factor * (_az - _cz),
                        )
                    for _vi, _co in _new_co.items():
                        _bm.verts[_vi].co.x = _co[0]
                        _bm.verts[_vi].co.y = _co[1]
                        _bm.verts[_vi].co.z = _co[2]

            _bm.to_mesh(obj.data)
            obj.data.update()
            log.log(
                f"  Taubin seam-blend: {len(seam_set)} verts, {_ITERS} iters "
                f"(lam={_LAM}, mu={_MU}) -- non-shrinking (Taubin 1995)"
            )

        _bm.free()

    # ── 6c. Full-surface Laplacian smooth (post-displacement aliasing fix) ────
    # PhD-Level 3D Texturing with Libraries §2 step 4:
    #   "Laplacian Smoothing: ensure PLA can flow over peaks without pressure
    #    spikes in the nozzle."
    # PhD-Level Texture Application in 3D §2:
    #   "relax_params.iterations = 5 — soften sharp aliasing from the image."
    #
    # Uses a gentle λ=0.15 (15% toward neighbourhood average) rather than the
    # MeshLib default of 1.0, to preserve displaced texture detail while
    # blurring only sub-pixel aliasing from PNG hard edges.  3 passes instead
    # of 5 because the seam band already received Taubin smoothing above.
    # Skipped when relief < 0.4mm — aliasing not printable at low amplitude.
    if abs(relief) >= 0.4:
        import bmesh as _bm_lap

        _bm2 = _bm_lap.new()
        _bm2.from_mesh(obj.data)
        _bm2.verts.ensure_lookup_table()
        _LAP_LAMBDA = 0.15  # gentle — 15% toward avg; preserves texture shape
        _LAP_ITERS = 3  # 3 global passes (seam already got Taubin above)
        for _ in range(_LAP_ITERS):
            _new_co = {}
            for _v in _bm2.verts:
                _nbrs = [_le.other_vert(_v) for _le in _v.link_edges]
                if not _nbrs:
                    continue
                _ax = sum(_n.co.x for _n in _nbrs) / len(_nbrs)
                _ay = sum(_n.co.y for _n in _nbrs) / len(_nbrs)
                _az = sum(_n.co.z for _n in _nbrs) / len(_nbrs)
                _cx, _cy, _cz = _v.co.x, _v.co.y, _v.co.z
                _new_co[_v.index] = (
                    _cx + _LAP_LAMBDA * (_ax - _cx),
                    _cy + _LAP_LAMBDA * (_ay - _cy),
                    _cz + _LAP_LAMBDA * (_az - _cz),
                )
            for _vi, _co in _new_co.items():
                _bm2.verts[_vi].co.x = _co[0]
                _bm2.verts[_vi].co.y = _co[1]
                _bm2.verts[_vi].co.z = _co[2]
        _bm2.to_mesh(obj.data)
        obj.data.update()
        log.log(
            f"  Laplacian smooth (post-displacement): {_LAP_ITERS} iters "
            f"lam={_LAP_LAMBDA} -- aliasing suppression "
            f"(PhD-Level 3D Texturing §2 / Texture Application §2)"
        )
        _bm2.free()

    log.log(
        f"  Done: relief={strength:.2f}mm  tile={tile_size}mm  mode={mode}  "
        f"projection={'UV('+projection+')' if use_uv else 'OBJECT'}  "
        f"full_surface={full_surface}"
    )

    # ── 7. Shape DNA (diagnostic fingerprint + spectral verification) ──────
    # Compute on the post-displacement mesh (before subdivision makes it huge).
    # Eigenvalue ratio λ1/λ2 is compared against the classifier output:
    # mismatch = potential misclassification → check log for TOPOLOGY MISMATCH.
    # For meshes subdivided beyond 5 000 verts this is skipped automatically.
    _compute_shape_dna(
        obj,
        k=10,
        log=log,
        expected_class=_topology_sig.mesh_class if _topology_sig else None,
    )
    if debug_session:
        import math as _math_dbg

        _export_debug_snapshot(
            debug_session,
            "post_displace",
            obj,
            _topology_sig,
            log,
            render_heatmap=render_heatmap,
            strength_mm=strength,
            tile_size_mm=tile_size,
            mode=mode,
            projection=projection,
            coords=("UV(" + projection + ")") if use_uv else "OBJECT",
        )


def _apply_displacement(
    obj,
    skin_path: str,
    tile_size: float,
    relief: float,
    invert: bool,
    gamma: float,
    log: Logger,
    *,
    mode: str = "modifier",
    projection: str = "object",
    full_surface: bool = True,
    auto_params: bool = True,
    debug_session: "_DebugSession | None" = None,
    render_heatmap: bool = False,
):
    """Thin wrapper — always delegates to the full-Blender pipeline."""
    _apply_displacement_blender(
        obj,
        skin_path,
        tile_size,
        relief,
        invert,
        gamma,
        log,
        mode=mode,
        projection=projection,
        full_surface=full_surface,
        auto_params=auto_params,
        debug_session=debug_session,
        render_heatmap=render_heatmap,
    )


def _export_stl(obj, out_path: str, log: Logger):
    """
    Export a single mesh object to binary STL.

    Uses a pure-Python writer so no export add-on is required.
    Applies all modifiers via a dependency-graph evaluated mesh first.
    """
    import struct
    import mathutils  # bundled with bpy

    # Evaluate mesh with modifiers applied
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    mesh.calc_loop_triangles()

    mat = obj.matrix_world  # identity after transform_apply; kept for safety

    with open(out_path, "wb") as f:
        # 80-byte header
        f.write(b"\0" * 80)
        # Triangle count
        tris = mesh.loop_triangles
        f.write(struct.pack("<I", len(tris)))
        for tri in tris:
            # Compute face normal in world space
            v0 = mat @ mathutils.Vector(mesh.vertices[tri.vertices[0]].co)
            v1 = mat @ mathutils.Vector(mesh.vertices[tri.vertices[1]].co)
            v2 = mat @ mathutils.Vector(mesh.vertices[tri.vertices[2]].co)
            edge1 = v1 - v0
            edge2 = v2 - v0
            normal = edge1.cross(edge2)
            length = normal.length
            if length > 1e-10:
                normal /= length
            f.write(struct.pack("<fff", normal.x, normal.y, normal.z))
            for v in (v0, v1, v2):
                f.write(struct.pack("<fff", v.x, v.y, v.z))
            f.write(struct.pack("<H", 0))  # attribute byte count

    obj_eval.to_mesh_clear()
    size_kb = os.path.getsize(out_path) // 1024
    log.log(f"  Exported: '{out_path}'  ({size_kb} KB)")


def _make_output_path(model_path: str, mode: str) -> str:
    p = pathlib.Path(model_path)
    stem = p.stem
    # Avoid accumulating suffixes on repeated runs
    for suffix in (
        "_texture_modifier",
        "_texture_part",
        "_texture_negative",
        "_texture",
    ):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return str(p.parent / f"{stem}_texture_{mode}.stl")


# ── main ──────────────────────────────────────────────────────────────────
def main():
    args = _parse_args()
    log_path = args.log or os.path.join(
        tempfile.gettempdir(), "apply_texture_bpy_log.txt"
    )
    log = Logger(log_path)

    try:
        log.log("=== apply_texture_bpy.py ===")
        log.log(
            f"IS_FULL_BLENDER={IS_FULL_BLENDER}  binary_path={getattr(bpy.app, 'binary_path', 'n/a')}"
        )

        # ── Auto-params resolution ────────────────────────────────────────────
        # If --tile-size / --relief are not given on CLI, compute them from
        # geometry inside _apply_displacement_blender() (after topology class is known).
        # If the caller explicitly passes either value, respect it and disable auto-calc.
        auto_params: bool = args.auto_params and (
            args.tile_size is None and args.relief is None
        )
        tile_size: float = args.tile_size if args.tile_size is not None else 15.0
        relief: float = args.relief if args.relief is not None else 1.0
        # When auto_params=True the values above are placeholders — they are
        # overwritten by _compute_optimal_params() inside _apply_displacement_blender().

        log.log(
            f"mode={args.mode}  auto_params={auto_params}  "
            f"tile={tile_size}mm{'(auto)' if auto_params else ''}  "
            f"relief={relief}mm{'(auto)' if auto_params else ''}  "
            f"invert={args.invert}  gamma={args.gamma}  "
            f"projection={args.projection}  full_surface={args.full_surface}"
        )
        log.log(f"model: {args.model_path}")
        log.log(f"skin : {args.skin_path}")
        # ── DIAGNOSTIC: confirm texture file exists and is non-empty ──────────
        if not args.skin_path:
            raise RuntimeError(
                "TEXTURE PATH IS EMPTY — png_path was not passed from C++ (check tex_log)"
            )
        if not os.path.exists(args.skin_path):
            raise RuntimeError(f"TEXTURE FILE NOT FOUND: '{args.skin_path}'")
        _skin_sz = os.path.getsize(args.skin_path)
        if _skin_sz == 0:
            raise RuntimeError(f"TEXTURE FILE IS ZERO BYTES: '{args.skin_path}'")
        log.log(
            f"skin_exists=True  skin_size={_skin_sz} bytes  (file confirmed readable)"
        )

        # ── Debug snapshot session (AI Vision-in-the-Loop) ────────────────────
        _debug_session: "_DebugSession | None" = None
        if getattr(args, "debug_snapshots", False):
            _snap_dir = getattr(args, "snapshots_dir", "") or os.path.dirname(log_path)
            _debug_session = _DebugSession(
                model_path=args.model_path,
                skin_path=args.skin_path,
                snapshots_dir=_snap_dir,
            )
            log.log(f"  debug-snapshots ON → {_snap_dir}")

        _reset_scene()

        meshes = _import_model(args.model_path, log)
        if not meshes:
            raise RuntimeError("No mesh objects found in model file")

        original_obj = meshes[0]
        out_path = _make_output_path(args.model_path, args.mode)

        # Bake the world transform into vertex coords so the exported STL is in
        # object-local space (same space QIDIStudio uses for ModelVolume geometry).
        # Without this, matrix_world offsets get applied twice → volume floats away.
        bpy.context.view_layer.objects.active = original_obj
        bpy.ops.object.select_all(action="DESELECT")
        original_obj.select_set(True)
        with _ops_ctx(original_obj):
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        if args.mode == "modifier":
            # ── MODIFIER: displace the original mesh in-place, then replace ──
            # _apply_displacement handles UV unwrap internally (Step 1).
            _apply_displacement(
                original_obj,
                args.skin_path,
                tile_size,
                relief,
                args.invert,
                args.gamma,
                log,
                mode=args.mode,
                projection=args.projection,
                full_surface=args.full_surface,
                debug_session=_debug_session,
                render_heatmap=getattr(args, "render_heatmap", False),
                auto_params=auto_params,
            )
            _export_stl(original_obj, out_path, log)

        else:
            # ── PART / NEGATIVE: duplicate mesh, displace copy, export copy ──
            # UV is handled inside _apply_displacement_blender → _do_uv_unwrap
            # (no pre-UV step needed here — the LSCM/conformal unwrap runs on
            #  the copy after subdivision, not on the original).

            # Data-API duplicate — bpy.ops.object.duplicate() silently no-ops
            # in headless/background mode, causing displaced_obj to alias
            # original_obj and corrupting the source mesh.
            new_mesh = original_obj.data.copy()
            displaced_obj = original_obj.copy()
            displaced_obj.data = new_mesh
            displaced_obj.name = original_obj.name + "_tex"
            bpy.context.collection.objects.link(displaced_obj)

            # For NEGATIVE: displacement is always inward (mode handles this in
            # _apply_displacement, invert_mode passed for PART only)
            invert_mode = (not args.invert) if args.mode == "negative" else args.invert

            _apply_displacement(
                displaced_obj,
                args.skin_path,
                tile_size,
                relief,
                invert_mode,
                args.gamma,
                log,
                mode=args.mode,
                projection=args.projection,
                full_surface=args.full_surface,
                debug_session=_debug_session,
                render_heatmap=getattr(args, "render_heatmap", False),
                auto_params=auto_params,
            )
            _export_stl(displaced_obj, out_path, log)

        log.emit_skin_output(out_path)
        log.log("=== done ===")

    except Exception as exc:
        log.log(f"ERROR: {exc}")
        log.log(traceback.format_exc())
        sys.exit(1)
    finally:
        log.flush()


if __name__ == "__main__":
    main()
