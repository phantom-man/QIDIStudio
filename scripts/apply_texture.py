#!/usr/bin/env python3
"""
apply_texture.py — Tile a dragon scale (or any SVG/PNG) texture across a 3D mesh
               surface using vertex displacement.  Called from QIDIStudio via
               right-click → "Apply Script..." or run standalone.

Usage:
    python apply_texture.py  <model_file>  [options]

    <model_file>  STL or 3MF file to modify IN-PLACE (QIDIStudio passes this
                  automatically when launched from "Apply Script...").

Options:
    --svg    <path>    SVG file to use as texture source.  Defaults to the
                       last SVG path stored in scripts/.last_svg.txt, or
                       prompts you to pick one.
    --depth  <mm>      Displacement depth in mm (default: 0.5)
    --tile   <n>       Tile count per axis (default: auto based on part size / 25mm)
    --axis   <x|y|z>   Projection axis for UV mapping (default: z = top face)
    --subdivide <n>    Mesh subdivision passes before displacement (default: 3)
    --smooth           Apply Laplacian smoothing to scale tips after displacement

Example:
    python apply_texture.py lid.stl --svg dragon_scale_42.svg --depth 0.4 --tile 8
"""

import sys
import os
import argparse
import pathlib
import struct

# ── Dependency check ─────────────────────────────────────────────────────────
_missing = []
for pkg in ("pyvista", "numpy", "PIL", "trimesh"):
    try:
        __import__(pkg)
    except ImportError:
        _missing.append(pkg)
if _missing:
    print(f"ERROR: Missing packages: {', '.join(_missing)}")
    print(f"Run:  pip install -r {pathlib.Path(__file__).parent}/requirements.txt")
    sys.exit(1)

import numpy as np
import pyvista as pv
import trimesh
from PIL import Image

# ── Load .env for API keys (optional — only needed for ai_texture.py) ─────────
_env_path = pathlib.Path(__file__).parent.parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass  # dotenv not installed — API keys unavailable but not needed here


# ─────────────────────────────────────────────────────────────────────────────
# SVG → numpy heightmap
# ─────────────────────────────────────────────────────────────────────────────

def svg_to_heightmap(svg_path: str, size_px: int = 512) -> np.ndarray:
    """Rasterise an SVG to a square greyscale heightmap (0..1 float32)."""
    try:
        import cairosvg
        png_bytes = cairosvg.svg2png(url=svg_path, output_width=size_px, output_height=size_px)
        img = Image.open(__import__("io").BytesIO(png_bytes)).convert("L")
    except ImportError:
        # Fallback: use Pillow to open if already PNG, otherwise raise
        img = Image.open(svg_path).convert("L").resize((size_px, size_px), Image.LANCZOS)
    return np.asarray(img, dtype=np.float32) / 255.0


def png_to_heightmap(path: str, size_px: int = 512) -> np.ndarray:
    img = Image.open(path).convert("L").resize((size_px, size_px), Image.LANCZOS)
    return np.asarray(img, dtype=np.float32) / 255.0


# ─────────────────────────────────────────────────────────────────────────────
# Core displacement
# ─────────────────────────────────────────────────────────────────────────────

def apply_displacement(mesh: pv.PolyData,
                       heightmap: np.ndarray,
                       depth_mm: float,
                       tiles: int,
                       axis: str) -> pv.PolyData:
    """
    Project the mesh onto the chosen axis to get UV coords, tile them, sample
    the heightmap, then move each vertex outward along its surface normal by
    depth_mm * heightmap_value.
    """
    pts = np.array(mesh.points)
    bbox_min = pts.min(axis=0)
    bbox_max = pts.max(axis=0)
    span     = bbox_max - bbox_min
    span[span == 0] = 1.0  # avoid div-zero

    # UV projection: pick two axes perpendicular to the chosen axis
    ax_map = {"x": (1, 2), "y": (0, 2), "z": (0, 1)}
    u_ax, v_ax = ax_map.get(axis.lower(), (0, 1))

    u = (pts[:, u_ax] - bbox_min[u_ax]) / span[u_ax]  # 0..1
    v = (pts[:, v_ax] - bbox_min[v_ax]) / span[v_ax]

    # Tile (multiply UV to repeat n times across the surface)
    u_tiled = (u * tiles) % 1.0
    v_tiled = (v * tiles) % 1.0

    # Sample heightmap using bilinear lookup
    H, W = heightmap.shape
    ix = np.clip((u_tiled * (W - 1)).astype(int), 0, W - 1)
    iy = np.clip((v_tiled * (H - 1)).astype(int), 0, H - 1)
    heights = heightmap[iy, ix]   # 0..1

    # Compute vertex normals (needed to push outward correctly)
    mesh_with_normals = mesh.compute_normals(cell_normals=False, point_normals=True)
    normals = np.array(mesh_with_normals.point_normals)

    # Displace
    displaced_pts = pts + normals * (heights[:, np.newaxis] * depth_mm)
    result = mesh.copy()
    result.points = displaced_pts
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("model_file",         help="STL or 3MF file to modify in-place")
    p.add_argument("--svg",   default=None, help="SVG or PNG texture file")
    p.add_argument("--depth", type=float, default=0.5, help="Displacement depth (mm)")
    p.add_argument("--tile",  type=int,   default=0,   help="Tile count (0=auto)")
    p.add_argument("--axis",  default="z", choices=["x","y","z"], help="Projection axis")
    p.add_argument("--subdivide", type=int, default=3, help="Subdivision passes")
    p.add_argument("--smooth", action="store_true", help="Laplacian smoothing after displacement")
    args = p.parse_args()

    model_path = pathlib.Path(args.model_file)
    if not model_path.exists():
        print(f"ERROR: model file not found: {model_path}", file=sys.stderr)
        sys.exit(1)

    # ── Resolve SVG ───────────────────────────────────────────────────────────
    svg_path = args.svg
    last_svg_file = pathlib.Path(__file__).parent / ".last_svg.txt"
    if svg_path is None and last_svg_file.exists():
        svg_path = last_svg_file.read_text().strip()
    if svg_path is None:
        print("ERROR: No texture file specified.  Use --svg <file.svg>", file=sys.stderr)
        sys.exit(1)
    if not pathlib.Path(svg_path).exists():
        print(f"ERROR: texture file not found: {svg_path}", file=sys.stderr)
        sys.exit(1)
    # Remember for next run
    last_svg_file.write_text(str(svg_path))

    print(f"Model   : {model_path}")
    print(f"Texture : {svg_path}")
    print(f"Depth   : {args.depth} mm")

    # ── Load mesh ─────────────────────────────────────────────────────────────
    suffix = model_path.suffix.lower()
    if suffix == ".stl":
        mesh = pv.read(str(model_path))
    elif suffix == ".3mf":
        # trimesh handles 3MF; convert to pyvista
        tm = trimesh.load(str(model_path), force="mesh")
        if isinstance(tm, trimesh.Scene):
            geoms = list(tm.geometry.values())
            tm = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
        mesh = pv.wrap(tm)
    else:
        print(f"Unsupported format: {suffix}  (use .stl or .3mf)", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded  : {mesh.n_points} pts, {mesh.n_cells} cells")

    # ── Subdivide for resolution ───────────────────────────────────────────────
    if args.subdivide > 0:
        print(f"Subdividing {args.subdivide}x …", end=" ", flush=True)
        mesh = mesh.subdivide(args.subdivide, subfilter="linear")
        print(f"→ {mesh.n_points} pts")

    # ── Build heightmap ───────────────────────────────────────────────────────
    print("Generating heightmap …", end=" ", flush=True)
    ext = pathlib.Path(svg_path).suffix.lower()
    if ext == ".svg":
        heightmap = svg_to_heightmap(svg_path)
    else:
        heightmap = png_to_heightmap(svg_path)
    print(f"→ {heightmap.shape[0]}×{heightmap.shape[1]} px")

    # ── Auto tile count ───────────────────────────────────────────────────────
    tiles = args.tile
    if tiles <= 0:
        bounds = mesh.bounds
        ax_map = {"x": (2,4), "y": (0,2), "z": (0,2)}
        # uses XY span for Z-axis projection (top face)
        span_u = bounds[1]-bounds[0]  # X span
        span_v = bounds[3]-bounds[2]  # Y span
        tiles = max(1, round(max(span_u, span_v) / 25.0))
        print(f"Auto tile: {tiles}×{tiles} (object {span_u:.0f}×{span_v:.0f} mm)")
    else:
        print(f"Tile    : {tiles}×{tiles}")

    # ── Displace ──────────────────────────────────────────────────────────────
    print("Displacing vertices …", end=" ", flush=True)
    displaced = apply_displacement(mesh, heightmap, args.depth, tiles, args.axis)
    print("done")

    # ── Optional smoothing ────────────────────────────────────────────────────
    if args.smooth:
        try:
            import open3d as o3d
            print("Smoothing …", end=" ", flush=True)
            pts  = np.array(displaced.points)
            tris = displaced.faces.reshape(-1, 4)[:, 1:]
            o3d_mesh = o3d.geometry.TriangleMesh()
            o3d_mesh.vertices  = o3d.utility.Vector3dVector(pts)
            o3d_mesh.triangles = o3d.utility.Vector3iVector(tris)
            o3d_mesh = o3d_mesh.filter_smooth_laplacian(10)
            displaced.points = np.asarray(o3d_mesh.vertices)
            print("done")
        except ImportError:
            print("(open3d not installed — skipping smoothing)")

    # ── Save back ─────────────────────────────────────────────────────────────
    print(f"Saving  : {model_path} …", end=" ", flush=True)
    if suffix == ".stl":
        displaced.save(str(model_path))
    elif suffix == ".3mf":
        # Convert pyvista → trimesh → 3MF
        pts  = np.array(displaced.points)
        tris = displaced.faces.reshape(-1, 4)[:, 1:]
        tm_out = trimesh.Trimesh(vertices=pts, faces=tris)
        tm_out.export(str(model_path))
    print("done")
    print(f"\nSuccess — reload the model in QIDIStudio to see the result.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
