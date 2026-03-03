#!/usr/bin/env python3
"""
apply_skin.py — Add Skin script for QIDIStudio
================================================
Called by QIDIStudio "Add Skin..." right-click menu item:

    python apply_skin.py  <model_path>  <skin_asset_path>  [options]

  model_path      : path to the STL or 3MF on disk that QIDIStudio will reload
  skin_asset_path : SVG, PNG, JPG to tile as a surface texture / displacement relief

Exit codes:  0=success  2=cancelled  1=error
Log file   : %TEMP%\apply_skin_log.txt  (always written — check here on failure)

Requirements (install once):
    pip install trimesh numpy Pillow
Optional for SVG rasterisation:
    pip install cairosvg
"""

# ── Log file — opened BEFORE any imports so import errors are captured too ───
import sys
import os
import pathlib
import datetime

_LOG_PATH = (
    pathlib.Path(os.environ.get("TEMP", str(pathlib.Path.home())))
    / "apply_skin_log.txt"
)


class _Tee:
    """Write to both the original stream and a log file simultaneously."""

    def __init__(self, stream, log_fh):
        self._stream = stream
        self._log = log_fh

    def write(self, msg):
        try:
            self._stream.write(msg)
            self._stream.flush()
        except Exception:
            pass
        try:
            self._log.write(msg)
            self._log.flush()
        except Exception:
            pass

    def flush(self):
        try:
            self._stream.flush()
        except Exception:
            pass
        try:
            self._log.flush()
        except Exception:
            pass

    def fileno(self):
        return self._stream.fileno()


_log_fh = open(_LOG_PATH, "w", encoding="utf-8", errors="replace")
_log_fh.write(f"=== apply_skin.py  {datetime.datetime.now().isoformat()} ===\n")
_log_fh.write(f"Args: {sys.argv}\n")
_log_fh.write(f"Python: {sys.version}\n\n")
_log_fh.flush()

sys.stdout = _Tee(sys.__stdout__, _log_fh)
sys.stderr = _Tee(sys.__stderr__, _log_fh)
print(f"Log: {_LOG_PATH}")

# ── Dependency check ──────────────────────────────────────────────────────────
import traceback
import math

MISSING = []
for _pkg in ("numpy", "trimesh", "PIL"):
    try:
        __import__(_pkg)
    except ImportError:
        MISSING.append(_pkg)

if MISSING:
    print(f"ERROR: Missing packages: {', '.join(MISSING)}")
    print(f"  Run:  pip install {' '.join(MISSING)}")
    _log_fh.close()
    sys.exit(1)

import re as _re
import numpy as np
import trimesh
from PIL import Image

print(f"numpy {np.__version__}  trimesh {trimesh.__version__}")


# ── Namespace helpers ─────────────────────────────────────────────────────────


def _register_all_namespaces(raw_bytes: bytes, et_module) -> None:
    """
    Scan raw XML bytes for ALL 'xmlns:prefix="uri"' declarations and register
    them with ElementTree.  This is REQUIRED before calling ET.tostring() so
    that attribute names like 'p:UUID' are preserved verbatim instead of being
    silently renamed to 'ns0:UUID', 'ns1:UUID', etc.  QIDIStudio's 3MF parser
    rejects files where those production-spec attribute names are wrong, and
    the resulting scene appears empty.
    """
    text = raw_bytes.decode("utf-8", errors="replace")
    for m in _re.finditer(r'xmlns:(\w+)\s*=\s*"([^"]+)"', text):
        prefix, uri = m.group(1), m.group(2)
        et_module.register_namespace(prefix, uri)


# ── Heightmap helpers ─────────────────────────────────────────────────────────


def _load_raw(
    asset_path: str, size_px: int = 512, invert: bool = True, gamma: float = 0.7
) -> "np.ndarray":
    """
    Load SVG or raster → float32 heightmap [0, 1], square size_px.

    invert=True (default): dark pixels become HIGH displacement.
        Dragon/reptile scale images are rendered with dark scale bodies and
        bright edges. Inverting makes each scale body a raised dome with
        the crevice between scales as the low point — the correct 3D look.
        Set invert=False for images where white already means 'raised'.

    gamma<1 (default 0.7): power curve applied AFTER invert+stretch.
        Makes the scale dome profile rounded (smooth bell) rather than a
        sharp-edged linear ramp. Values > 1 sharpen the effect.
    """
    ext = pathlib.Path(asset_path).suffix.lower()
    if ext == ".svg":
        try:
            import cairosvg, io as _io

            png = cairosvg.svg2png(
                url=asset_path, output_width=size_px, output_height=size_px
            )
            img = Image.open(_io.BytesIO(png)).convert("L")
            print(f"  SVG via cairosvg: {img.size}")
        except ImportError:
            print("  cairosvg not installed — treating SVG as solid displacement.")
            return np.ones((size_px, size_px), dtype=np.float32)
        except Exception as e:
            print(f"  SVG rasterise failed ({e}) — using solid block.")
            return np.ones((size_px, size_px), dtype=np.float32)
    else:
        img = Image.open(asset_path).convert("L")

    img = img.resize((size_px, size_px), Image.LANCZOS)
    arr = np.asarray(img, dtype=np.float32) / 255.0

    # Histogram stretch — ensure we use the full [0, 1] range regardless of
    # how dark the source image is (dragon scale PNGs are typically mean~0.2)
    lo, hi = arr.min(), arr.max()
    span = hi - lo
    if span > 1e-4:
        arr = (arr - lo) / span
    print(
        f"  Heightmap raw: {arr.shape}  min={lo:.3f}  max={hi:.3f}  (stretched to 0..1)"
    )

    if invert:
        arr = 1.0 - arr
        print(f"  Inverted (dark scale bodies → high displacement)")

    if gamma != 1.0:
        arr = arr**gamma
        print(f"  Gamma {gamma} applied (dome-shaped scale profile)")

    return arr


def _sample_tiled(
    hmap: "np.ndarray", u_mm: "np.ndarray", v_mm: "np.ndarray", tile_mm: float
) -> "np.ndarray":
    """
    Sample a single-tile heightmap with world-space coordinates in mm.
    Tiles infinitely by taking the fractional part of (position / tile_mm).
    This gives a uniform scale density regardless of bounding-box size —
    every tile_mm of surface gets exactly one scale, even on narrow parts.
    """
    H, W = hmap.shape
    u_frac = np.mod(u_mm / tile_mm, 1.0)
    v_frac = np.mod(v_mm / tile_mm, 1.0)
    ix = np.clip((u_frac * (W - 1)).astype(np.int32), 0, W - 1)
    iy = np.clip((v_frac * (H - 1)).astype(np.int32), 0, H - 1)
    return hmap[iy, ix]


# ── Projection functions ──────────────────────────────────────────────────────
# Each _project_*() function receives the mesh vertex array, normals, bounding
# box, heightmap and tile pitch, and returns a 1-D heights array (mm, one entry
# per vertex).  _displace() detects the right projector and calls it.
#
# To add a new geometry type:
#   1. Write def _project_myshape(verts, norms, bb_min, bb_max, hmap, tile_mm)
#   2. Add an elif branch in _pick_projector() that returns it.


def _project_cylindrical(
    verts: "np.ndarray",
    norms: "np.ndarray",
    bb_min: "np.ndarray",
    bb_max: "np.ndarray",
    hmap: "np.ndarray",
    tile_mm: float,
    long_axis: int,
) -> "np.ndarray":
    """
    Cylindrical projection — for elongated objects (tubes, nozzles, shafts).

    Wraps UV continuously around the long axis so the pattern tiles with
    zero seams going around the circumference:
        u = arc_length (atan2 × mean_radius)  — around the tube
        v = position along the long axis      — up/down the tube

    This eliminates the hard seam that winner-takes-all triplanar produces
    where the dominant axis flips from XZ→YZ at the 90° point around the tube.
    """
    radial_axes = [i for i in range(3) if i != long_axis]
    a, b = radial_axes

    centre_a = (bb_min[a] + bb_max[a]) / 2.0
    centre_b = (bb_min[b] + bb_max[b]) / 2.0

    ra = verts[:, a] - centre_a
    rb = verts[:, b] - centre_b

    mean_radius = ((bb_max[a] - bb_min[a]) + (bb_max[b] - bb_min[b])) / 4.0
    mean_radius = max(mean_radius, 1.0)  # guard against degenerate mesh

    theta = np.arctan2(rb, ra)  # [-π, +π] radians
    u_mm = theta * mean_radius  # arc-length in mm
    v_mm = verts[:, long_axis] - bb_min[long_axis]

    # Snap tile pitch so an integer number fits exactly around the circumference.
    # Without this atan2 creates a visible seam where the fractional tile repeats.
    circumference = 2.0 * np.pi * mean_radius
    n_tiles = max(1, round(circumference / tile_mm))
    tile_mm_u = circumference / n_tiles  # adjusted pitch for u only

    print(
        f"  Projection: cylindrical (long_axis={'XYZ'[long_axis]}, "
        f"R≈{mean_radius:.1f} mm, {n_tiles} tiles/rev, "
        f"u_tile={tile_mm_u:.2f} mm)"
    )
    return _sample_tiled(hmap, u_mm, v_mm, tile_mm_u)


def _project_triplanar(
    verts: "np.ndarray",
    norms: "np.ndarray",
    bb_min: "np.ndarray",
    bb_max: "np.ndarray",
    hmap: "np.ndarray",
    tile_mm: float,
) -> "np.ndarray":
    """
    Winner-takes-all triplanar projection — for blocky / flat objects.

    Each vertex independently picks the single projection plane most aligned
    with its surface normal (XY, XZ, or YZ).  No blending between planes
    means no destructive-interference crumpling on oblique faces.

    A hard seam is still visible where the dominant plane switches (e.g. at
    the corners of a box), but it is far less objectionable than the foil-
    crumple produced by linear-blend triplanar at oblique angles.
    """
    px = verts[:, 0] - bb_min[0]
    py = verts[:, 1] - bb_min[1]
    pz = verts[:, 2] - bb_min[2]

    w_xy = np.abs(norms[:, 2])  # XY plane (top/bottom):   weight = |norm_z|
    w_xz = np.abs(norms[:, 1])  # XZ plane (front/back):   weight = |norm_y|
    w_yz = np.abs(norms[:, 0])  # YZ plane (left/right):   weight = |norm_x|

    dominant = np.argmax(np.stack([w_xy, w_xz, w_yz], axis=1), axis=1)

    samp_xy = _sample_tiled(hmap, px, py, tile_mm)
    samp_xz = _sample_tiled(hmap, px, pz, tile_mm)
    samp_yz = _sample_tiled(hmap, py, pz, tile_mm)

    print(f"  Projection: triplanar winner-takes-all")
    return np.where(dominant == 0, samp_xy, np.where(dominant == 1, samp_xz, samp_yz))


def _pick_projector(
    bb_min: "np.ndarray", bb_max: "np.ndarray", verts: "np.ndarray | None" = None
):
    """
    Examine the bounding box and return the best projection callable.

    Returns a lambda that accepts (verts, norms, bb_min, bb_max, hmap, tile_mm)
    so _displace() always calls the same interface regardless of projector type.

    Rules (in priority order):
      • Elongated (longest dim ≥ 2.5× median)  →  cylindrical, unless the
        cross-section IQ test (Shapely) reveals it is actually flat/slab-like:
        IQ = 4π×A/P²  (circle=1.0, square=0.785, 5:1-rect=0.384).
        Threshold 0.55 rejects anything flatter than a 2.7:1 rectangle.
      • Everything else                         →  triplanar
    """
    dims = bb_max - bb_min
    order = np.argsort(dims)
    long_axis = int(order[2])
    long_dim = dims[long_axis]
    med_dim = dims[order[1]]

    if med_dim > 0 and (long_dim / med_dim) >= 2.5:
        # ── Shapely circularity guard ──────────────────────────────────────
        # Aspect ratio alone incorrectly promotes flat elongated slabs
        # (e.g. 300×30×5 mm ruler: ratio=10) to cylindrical projection.
        # Cross-section IQ catches them: the two short axes are projected;
        # a circle → IQ≈1, square → 0.785, thin slab → near 0.
        iq = 1.0  # assume circular if check fails
        if verts is not None:
            try:
                import math as _m
                from shapely.geometry import MultiPoint as _MP

                ra = [i for i in range(3) if i != long_axis]  # radial axes
                hull = _MP(verts[:, ra]).convex_hull
                if hull.geom_type == "Polygon" and hull.length > 0:
                    iq = 4.0 * _m.pi * hull.area / (hull.length**2)
                    verdict = (
                        "cylindrical"
                        if iq >= 0.55
                        else "triplanar (flat cross-section)"
                    )
                    print(f"  Cross-section IQ={iq:.3f} \u2192 {verdict}")
            except Exception:
                pass  # Shapely absent or hull failed — proceed with aspect ratio
        if iq >= 0.55:
            # Capture long_axis in the closure so the interface stays uniform
            return lambda v, n, mn, mx, h, t: _project_cylindrical(
                v, n, mn, mx, h, t, long_axis
            )

    return _project_triplanar


# ── Displacement driver ───────────────────────────────────────────────────────


def _displace(
    mesh: "trimesh.Trimesh",
    hmap: "np.ndarray",
    tile_mm: float,
    bb_min=None,
    bb_max=None,
    max_edge_hint: float = 2.5,
    force_projection: str | None = None,
) -> "trimesh.Trimesh":
    """
    Displace mesh vertices along surface normals by amounts sampled from *hmap*.

    Automatically selects the best UV projection for the object's geometry
    via _pick_projector() and delegates to the corresponding _project_*()
    function.  All projectors use world-space tiling (every tile_mm of surface
    = exactly one complete tile, independent of bounding-box size).

    bb_min/bb_max    : global bounding box of the whole 3MF so tile phase is
                       consistent across multi-mesh assemblies.
    max_edge_hint    : the subdivision target edge length (mm).  Heights are
                       clamped to 40% of this value to prevent fold-over
                       non-manifold edges.  Matches the --max-edge argument.
    """
    verts = np.array(mesh.vertices, dtype=np.float64)
    norms = np.array(mesh.vertex_normals, dtype=np.float64)

    if bb_min is None:
        bb_min = verts.min(axis=0)
        bb_max = verts.max(axis=0)
    else:
        bb_min = np.asarray(bb_min, dtype=np.float64)
        bb_max = np.asarray(bb_max, dtype=np.float64)

    if force_projection == "cylindrical":
        dims = bb_max - bb_min
        long_axis = int(np.argmax(dims))
        projector = lambda v, n, mn, mx, h, t: _project_cylindrical(
            v, n, mn, mx, h, t, long_axis
        )  # noqa: E731
        print(f"  Projection: cylindrical (forced, long_axis={'XYZ'[long_axis]})")
    elif force_projection == "triplanar":
        projector = _project_triplanar
        print("  Projection: triplanar (forced)")
    else:
        projector = _pick_projector(bb_min, bb_max, verts=verts)
    heights = projector(verts, norms, bb_min, bb_max, hmap, tile_mm)

    # Clamp displacement to 40% of the subdivision target edge length.
    # This is the physical threshold below which no two displaced vertices
    # can collide and create non-manifold (fold-over) edges.  Using the
    # parameter-level target edge (max_edge_hint) instead of the actual
    # post-subdivision minimum avoids being tripped by tiny degenerate edges
    # that survive from the original source mesh.
    if max_edge_hint > 0:
        max_safe = max_edge_hint * 0.4
        heights = np.minimum(heights, max_safe)
        print(
            f"  Displacement clamped to ≤ {max_safe:.3f} mm (40% of target edge {max_edge_hint:.3f} mm)"
        )

    displaced = verts + norms * heights[:, np.newaxis]
    delta_max = np.linalg.norm(displaced - verts, axis=1).max()
    print(f"  Max displacement: {delta_max:.3f} mm")
    return trimesh.Trimesh(vertices=displaced, faces=mesh.faces, process=True)


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("model_path", help="Source 3MF or STL file")
    p.add_argument("skin_path", help="SVG, PNG, JPG skin asset to tile")
    p.add_argument(
        "--tile-size", type=float, default=15.0, help="Tile pitch mm (default 15)"
    )
    p.add_argument(
        "--relief",
        type=float,
        default=1.0,
        help="Max displacement depth mm (default 1.0)",
    )
    p.add_argument(
        "--max-edge",
        type=float,
        default=2.5,
        help="Subdivide mesh until all edges ≤ this mm (default 2.5, 0=skip)",
    )
    p.add_argument(
        "--invert",
        action="store_true",
        default=True,
        help="Invert heightmap so dark scale bodies become raised domes (default ON)",
    )
    p.add_argument(
        "--no-invert",
        dest="invert",
        action="store_false",
        help="Disable inversion — use for images where white=raised",
    )
    p.add_argument(
        "--gamma",
        type=float,
        default=0.7,
        help="Power curve after invert: <1 rounds dome profiles, >1 sharpens (default 0.7)",
    )
    p.add_argument(
        "--projection",
        choices=["auto", "cylindrical", "triplanar"],
        default="auto",
        help="UV projection mode: auto (smart-pick), cylindrical (tubes/nozzles), triplanar (blocky parts). Default: auto",
    )
    p.add_argument(
        "--log", default=None, help="Override log file path (QIDIStudio passes this)"
    )
    args = p.parse_args()

    # ── Validate paths ────────────────────────────────────────────────────────
    if not os.path.exists(args.model_path):
        print(f"ERROR: model file not found:\n  {args.model_path}")
        return 1
    if not os.path.exists(args.skin_path):
        print(f"ERROR: skin asset not found:\n  {args.skin_path}")
        return 1

    print()
    print(f"Model : {args.model_path}")
    print(f"Skin  : {args.skin_path}")
    print(
        f"Tile  : {args.tile_size} mm   Relief: {args.relief} mm   Max-edge: {args.max_edge} mm"
    )
    print(
        f"Invert: {args.invert}   Gamma: {args.gamma}   Projection: {args.projection}"
    )
    print()

    import zipfile as _zf
    import xml.etree.ElementTree as _ET
    import io as _io

    ns3 = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    _ET.register_namespace("", ns3)

    model_p = pathlib.Path(args.model_path)

    # ── STL → minimal in-memory 3MF conversion ─────────────────────────────────
    # apply_skin.py operates on 3MF (zip-XML) internally.  When given an STL we
    # build a minimal conforming 3MF in-memory so the rest of the code path is
    # unchanged.  The output suffix is forced to .3mf in this case.
    _stl_source: pathlib.Path | None = None
    if model_p.suffix.lower() == ".stl":
        print(f"STL input detected — converting to in-memory 3MF …")
        _stl_source = model_p
        _stl_mesh = trimesh.load(str(model_p), force="mesh")
        _verts = _stl_mesh.vertices  # (N,3) float64
        _faces = _stl_mesh.faces  # (M,3) int
        ns3 = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
        _vert_lines = "\n          ".join(
            f'<vertex x="{v[0]:.6f}" y="{v[1]:.6f}" z="{v[2]:.6f}"/>' for v in _verts
        )
        _tri_lines = "\n          ".join(
            f'<triangle v1="{f[0]}" v2="{f[1]}" v3="{f[2]}"/>' for f in _faces
        )
        _model_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<model unit="millimeter" xml:lang="en-US" xmlns="{ns3}">\n'
            f"  <resources>\n"
            f'    <object id="1" type="model">\n'
            f"      <mesh>\n"
            f"        <vertices>\n"
            f"          {_vert_lines}\n"
            f"        </vertices>\n"
            f"        <triangles>\n"
            f"          {_tri_lines}\n"
            f"        </triangles>\n"
            f"      </mesh>\n"
            f"    </object>\n"
            f"  </resources>\n"
            f"  <build>\n"
            f'    <item objectid="1"/>\n'
            f"  </build>\n"
            f"</model>\n"
        ).encode()
        _content_types = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            b'<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
            b"</Types>"
        )
        _rels = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            b'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
            b"</Relationships>"
        )
        _buf = _io.BytesIO()
        with _zf.ZipFile(_buf, "w", compression=_zf.ZIP_DEFLATED) as _zw:
            _zw.writestr("[Content_Types].xml", _content_types)
            _zw.writestr("_rels/.rels", _rels)
            _zw.writestr("3D/3dmodel.model", _model_xml)
        # Write temp 3MF next to the STL so output path works normally.
        model_p = model_p.with_suffix(".3mf")
        model_p.write_bytes(_buf.getvalue())
        print(f"  → temporary 3MF written: {model_p}  ({len(_buf.getvalue()):,} bytes)")

    # ── Output path: strip previous _skin suffix so re-runs overwrite correctly ─
    stem = model_p.stem
    if stem.endswith("_skin"):
        stem = stem[:-5]
    out_p = model_p.with_name(stem + "_skin" + model_p.suffix)

    # ── Read all files in zip, parse every .model file for mesh objects ─────────
    # QIDIStudio puts each geometry in 3D/Objects/object_N.model;
    # 3D/3dmodel.model is just a component reference with no mesh data.
    print("─── Scanning 3MF structure ───")
    try:
        zip_bytes = {}
        with _zf.ZipFile(str(model_p), "r") as zin:
            for entry in zin.infolist():
                zip_bytes[entry.filename] = zin.read(entry.filename)
    except Exception as e:
        print(f"ERROR reading 3MF: {e}")
        traceback.print_exc()
        return 1

    def _ns(tag):
        return f"{{{ns3}}}{tag}"

    # Parse every *.model file, collect mesh objects with live element refs.
    model_trees = {}  # filename → (tree, root)  — serialised back after displacement
    mesh_objects = []  # list of (verts_el, tris_el, vtag, ttag, loc_verts, loc_faces)
    all_global_verts = []

    for fname, fbytes in zip_bytes.items():
        if not fname.endswith(".model"):
            continue
        # Register ALL namespace prefixes from this file's raw bytes so that
        # ET.tostring() later preserves 'p:UUID', 'QIDIStudio:uuid', etc.
        # Without this step every non-default prefix gets renamed 'ns0:', 'ns1:'
        # and QIDIStudio silently fails to load the geometry (shows empty scene).
        _register_all_namespaces(fbytes, _ET)
        try:
            tree = _ET.parse(_io.BytesIO(fbytes))
            root = tree.getroot()
        except Exception:
            continue
        model_trees[fname] = (tree, root)

        for obj_el in root.iter(_ns("object")):
            mesh_el = obj_el.find(".//" + _ns("mesh"))
            if mesh_el is None:
                mesh_el = obj_el.find(".//mesh")
            if mesh_el is None:
                continue

            verts_el = mesh_el.find(_ns("vertices"))
            if verts_el is None:
                verts_el = mesh_el.find("vertices")
            tris_el = mesh_el.find(_ns("triangles"))
            if tris_el is None:
                tris_el = mesh_el.find("triangles")
            if verts_el is None or tris_el is None:
                continue

            ns_ok = mesh_el.find(_ns("vertices")) is not None
            vtag = _ns("vertex") if ns_ok else "vertex"
            ttag = _ns("triangle") if ns_ok else "triangle"

            loc_verts = [
                [float(v.get("x", 0)), float(v.get("y", 0)), float(v.get("z", 0))]
                for v in verts_el
            ]
            loc_faces = [
                [int(t.get("v1", 0)), int(t.get("v2", 0)), int(t.get("v3", 0))]
                for t in tris_el
            ]
            if not loc_verts or not loc_faces:
                continue

            mesh_objects.append((verts_el, tris_el, vtag, ttag, loc_verts, loc_faces))
            all_global_verts.extend(loc_verts)

    if not mesh_objects:
        print("ERROR: no mesh objects found in 3MF")
        return 1

    gv = np.array(all_global_verts, dtype=np.float64)
    global_bb_min = gv.min(axis=0)
    global_bb_max = gv.max(axis=0)
    g_span = global_bb_max - global_bb_min
    dims = sorted(g_span, reverse=True)
    print(
        f"  {len(mesh_objects)} mesh object(s) | "
        f"global BB: {dims[0]:.1f} x {dims[1]:.1f} x {dims[2]:.1f} mm | "
        f"{len(all_global_verts):,} source verts"
    )

    # ── Heightmap (single tile, scaled by relief) ─────────────────────────────
    print(f"\n─── Building heightmap ───")
    try:
        single = (
            _load_raw(args.skin_path, invert=args.invert, gamma=args.gamma)
            * args.relief
        )
    except Exception as e:
        print(f"ERROR building heightmap: {e}")
        traceback.print_exc()
        return 1

    # ── Per-object: subdivide → displace (global BB) → update XML in-place ────
    print(f"\n─── Processing {len(mesh_objects)} object(s) ───")
    total_out_verts = 0

    for idx, (verts_el, tris_el, vtag, ttag, loc_verts, loc_faces) in enumerate(
        mesh_objects
    ):

        local_mesh = trimesh.Trimesh(
            vertices=np.array(loc_verts, dtype=np.float64),
            faces=np.array(loc_faces, dtype=np.int32),
            process=False,
        )
        v_in = len(local_mesh.vertices)

        # Subdivide — midpoint only (no Loop), preserves sharp corners.
        # max_iter=6 caps at ×64 original verts to prevent memory blowup.
        if args.max_edge > 0:
            try:
                new_v, new_f = trimesh.remesh.subdivide_to_size(
                    local_mesh.vertices,
                    local_mesh.faces,
                    max_edge=args.max_edge,
                    max_iter=6,
                )
                # process=True merges near-duplicate seam vertices created by
                # subdivision so they move together during displacement instead
                # of pulling apart and creating non-manifold edges.
                local_mesh = trimesh.Trimesh(vertices=new_v, faces=new_f, process=True)
            except Exception as sub_e:
                print(f"  obj[{idx}] WARN: subdivide failed ({sub_e}) — skipping")

        # Displace using GLOBAL bounding box so tile phase is consistent
        # across all objects and scales line up at object boundaries.
        displaced_local = _displace(
            local_mesh,
            single,
            args.tile_size,
            bb_min=global_bb_min,
            bb_max=global_bb_max,
            max_edge_hint=args.max_edge if args.max_edge > 0 else 0,
            force_projection=None if args.projection == "auto" else args.projection,
        )

        # Repair: merge duplicate/degenerate faces introduced by displacement.
        # ONLY use process=True (merge_vertices + remove_degenerate_faces +
        # consistent winding within each connected component).
        #
        # DO NOT call fix_normals() or fill_holes() on an open (non-watertight)
        # mesh like the nozzle.  fix_normals() cannot distinguish inside from
        # outside without a closed surface, so it flips entire face patches to
        # achieve topological consistency — inverting their normals and making
        # them cave inward.  That produces the "aluminum foil" crumpled patches
        # visible on non-watertight parts.  fill_holes() likewise adds spurious
        # cap geometry at every open boundary edge.
        try:
            displaced_local = trimesh.Trimesh(
                vertices=displaced_local.vertices,
                faces=displaced_local.faces,
                process=True,  # safe: merges verts, drops degenerate tris
            )
            print(
                f"  obj[{idx}]: repair OK — "
                f"{len(displaced_local.faces):,} faces, "
                f"watertight={displaced_local.is_watertight}"
            )
        except Exception as repair_e:
            print(f"  obj[{idx}] WARN: repair step failed ({repair_e}) — continuing")

        total_out_verts += len(displaced_local.vertices)
        print(
            f"  obj[{idx}]: {v_in} src → {len(displaced_local.vertices):,} displaced verts"
        )

        # Rewrite <vertices> in-place
        for v in list(verts_el):
            verts_el.remove(v)
        for vx, vy, vz in displaced_local.vertices:
            el = _ET.SubElement(verts_el, vtag)
            el.set("x", f"{vx:.6f}")
            el.set("y", f"{vy:.6f}")
            el.set("z", f"{vz:.6f}")

        # Rewrite <triangles> in-place
        for t in list(tris_el):
            tris_el.remove(t)
        for i0, i1, i2 in displaced_local.faces:
            el = _ET.SubElement(tris_el, ttag)
            el.set("v1", str(int(i0)))
            el.set("v2", str(int(i1)))
            el.set("v3", str(int(i2)))

    # ── Serialise every updated .model tree back to bytes ─────────────────────
    for fname, (tree, root_el) in model_trees.items():
        zip_bytes[fname] = b'<?xml version="1.0" encoding="UTF-8"?>\n' + _ET.tostring(
            root_el, encoding="unicode", xml_declaration=False
        ).encode("utf-8")

    # ── Write output 3MF: original zip contents with all .model files replaced ──
    print(f"\n─── Saving \u2192 {out_p.name} ───")
    try:
        with _zf.ZipFile(str(out_p), "w", compression=_zf.ZIP_DEFLATED) as zout:
            for fname, fbytes in zip_bytes.items():
                zout.writestr(fname, fbytes)
    except Exception as e:
        print(f"ERROR saving 3MF: {e}")
        traceback.print_exc()
        return 1

    kb = out_p.stat().st_size // 1024
    print(
        f"  Written: {out_p}  ({kb:,} KB)  |  {total_out_verts:,} total displaced verts"
    )

    print(f"\n\u2713 Success")
    print(f"SKIN_OUTPUT: {out_p}")
    print(f"LOG_FILE: {_LOG_PATH}")
    return 0


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        rc = 2
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    except Exception:
        print("\n=== Unhandled exception ===")
        traceback.print_exc()
        rc = 1
    finally:
        print(f"\n=== Exit code: {rc} ===")
        try:
            _log_fh.close()
        except Exception:
            pass
    sys.exit(rc)
