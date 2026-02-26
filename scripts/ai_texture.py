#!/usr/bin/env python3
"""
ai_texture.py — Generate an AI texture via Vertex AI Imagen 3 or Replicate/Flux,
                then apply it as a displacement map to a 3D mesh.

Usage:
    python ai_texture.py  <model_file>  [options]

    <model_file>   STL or 3MF to modify IN-PLACE.  QIDIStudio passes this
                   automatically when launched from "Apply Script...".

Options:
    --prompt  "…"   Image generation prompt  (default: dragon scale tile)
    --depth   <mm>  Displacement depth in mm  (default: 0.5)
    --tile    <n>   Tile count per axis        (default: auto)
    --axis    <z>   UV projection axis         (default: z)
    --subdivide <n> Subdivision passes         (default: 3)
    --backend  <vertex|replicate|file>
                    vertex   — Vertex AI Imagen 3 (ADC, best quality)
                    replicate — Flux Schnell (API token, fast)
                    file      — Load last saved texture; regenerate only when not found
    --save-png <path>  Save the generated heightmap PNG to this path
    --load-png <path>  Skip AI generation, use this PNG directly

API keys:
    Loaded from  .env  in the repository root, or from environment variables.
    GOOGLE_API_KEY         — Vertex AI fallback (API-key auth)
    GOOGLE_CLOUD_PROJECT   — crafty-hook-483415-b3
    REPLICATE_API_TOKEN    — Replicate API token

Examples:
    python ai_texture.py lid.stl --prompt "seamless dragon scale pattern, dark blue metallic"
    python ai_texture.py base.stl --backend replicate --prompt "celtic knotwork seamless tile"
    python ai_texture.py knob.stl --load-png generated/pattern.png --depth 0.8
"""

import sys
import os
import argparse
import pathlib
import io
import tempfile

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

# ── Optional: load .env ───────────────────────────────────────────────────────
_env_path = pathlib.Path(__file__).parent.parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass  # dotenv not installed


# ─────────────────────────────────────────────────────────────────────────────
# AI backends
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_PROMPT = (
    "seamless dragon scale texture tile, photorealistic, metallic dark blue and gold, "
    "high contrast, black background, top-down view, square tile, no perspective, "
    "isolated pattern, ultra-detailed"
)


def generate_vertex_ai(prompt: str) -> bytes:
    """Generate via Vertex AI Imagen 3 using Application Default Credentials."""
    import vertexai
    from vertexai.preview.vision_models import ImageGenerationModel

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "crafty-hook-483415-b3")
    location = "us-central1"
    print(f"  Vertex AI project: {project}")
    vertexai.init(project=project, location=location)

    model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-001")
    response = model.generate_images(
        prompt=prompt,
        number_of_images=1,
        aspect_ratio="1:1",
        guidance_scale=21,
    )
    if not response.images:
        raise RuntimeError("Vertex AI returned no images")
    img = response.images[0]
    # img._image_bytes → raw PNG bytes
    return img._image_bytes


def generate_replicate(prompt: str) -> bytes:
    """Generate via Replicate / Flux Schnell."""
    import replicate
    import urllib.request

    token = os.environ.get("REPLICATE_API_TOKEN", "")
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN not set in environment or .env")
    os.environ["REPLICATE_API_TOKEN"] = token

    print("  Replicate / Flux Schnell …")
    output = replicate.run(
        "black-forest-labs/flux-schnell",
        input={"prompt": prompt, "num_inference_steps": 4, "output_format": "png"},
    )
    # output is a list of file-like URLs or FileOutput objects
    url = str(output[0])
    with urllib.request.urlopen(url) as r:
        return r.read()


def generate_google_api_key(prompt: str) -> bytes:
    """Fallback: use google-generativeai with API key auth."""
    import google.generativeai as genai
    from google.generativeai import types

    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel("imagen-3.0-generate-001")
    result = model.generate_content(
        prompt,
        generation_config=types.GenerationConfig(
            response_modalities=["IMAGE"],
        ),
    )
    for part in result.candidates[0].content.parts:
        if part.inline_data:
            return part.inline_data.data
    raise RuntimeError("google-generativeai returned no image data")


# ─────────────────────────────────────────────────────────────────────────────
# PNG bytes → greyscale heightmap
# ─────────────────────────────────────────────────────────────────────────────

def png_bytes_to_heightmap(png_bytes: bytes, size_px: int = 512) -> np.ndarray:
    img = Image.open(io.BytesIO(png_bytes)).convert("L").resize((size_px, size_px), Image.LANCZOS)
    return np.asarray(img, dtype=np.float32) / 255.0


def file_to_heightmap(path: str, size_px: int = 512) -> np.ndarray:
    img = Image.open(path).convert("L").resize((size_px, size_px), Image.LANCZOS)
    return np.asarray(img, dtype=np.float32) / 255.0


# ─────────────────────────────────────────────────────────────────────────────
# Displacement (same logic as apply_texture.py — keep in sync)
# ─────────────────────────────────────────────────────────────────────────────

def apply_displacement(mesh: pv.PolyData,
                       heightmap: np.ndarray,
                       depth_mm: float,
                       tiles: int,
                       axis: str) -> pv.PolyData:
    pts    = np.array(mesh.points)
    bb_min = pts.min(axis=0)
    bb_max = pts.max(axis=0)
    span   = bb_max - bb_min
    span[span == 0] = 1.0

    ax_map = {"x": (1, 2), "y": (0, 2), "z": (0, 1)}
    u_ax, v_ax = ax_map.get(axis.lower(), (0, 1))

    u = ((pts[:, u_ax] - bb_min[u_ax]) / span[u_ax] * tiles) % 1.0
    v = ((pts[:, v_ax] - bb_min[v_ax]) / span[v_ax] * tiles) % 1.0

    H, W = heightmap.shape
    ix = np.clip((u * (W - 1)).astype(int), 0, W - 1)
    iy = np.clip((v * (H - 1)).astype(int), 0, H - 1)
    heights = heightmap[iy, ix]

    mesh_n  = mesh.compute_normals(cell_normals=False, point_normals=True)
    normals = np.array(mesh_n.point_normals)

    result        = mesh.copy()
    result.points = pts + normals * (heights[:, np.newaxis] * depth_mm)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    pp = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    pp.add_argument("model_file")
    pp.add_argument("--prompt",     default=_DEFAULT_PROMPT)
    pp.add_argument("--depth",      type=float, default=0.5)
    pp.add_argument("--tile",       type=int,   default=0)
    pp.add_argument("--axis",       default="z", choices=["x","y","z"])
    pp.add_argument("--subdivide",  type=int,   default=3)
    pp.add_argument("--backend",    default="vertex",
                    choices=["vertex", "replicate", "google_key"])
    pp.add_argument("--save-png",   default=None)
    pp.add_argument("--load-png",   default=None)
    args = pp.parse_args()

    model_path = pathlib.Path(args.model_file)
    if not model_path.exists():
        print(f"ERROR: model file not found: {model_path}", file=sys.stderr)
        sys.exit(1)

    # ── Load or generate texture ───────────────────────────────────────────
    if args.load_png:
        print(f"Loading texture: {args.load_png}")
        heightmap = file_to_heightmap(args.load_png)
    else:
        print(f"Generating texture via {args.backend} …")
        print(f"  Prompt: {args.prompt[:80]}…" if len(args.prompt) > 80 else f"  Prompt: {args.prompt}")
        try:
            if args.backend == "vertex":
                png_bytes = generate_vertex_ai(args.prompt)
            elif args.backend == "replicate":
                png_bytes = generate_replicate(args.prompt)
            else:
                png_bytes = generate_google_api_key(args.prompt)
        except Exception as e:
            print(f"ERROR: AI generation failed: {e}", file=sys.stderr)
            sys.exit(2)

        if args.save_png:
            pathlib.Path(args.save_png).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(args.save_png).write_bytes(png_bytes)
            print(f"  Saved PNG: {args.save_png}")
        else:
            # Auto-save next to model for reproducibility
            auto_png = model_path.with_suffix(".ai_texture.png")
            auto_png.write_bytes(png_bytes)
            print(f"  Saved PNG: {auto_png}")

        heightmap = png_bytes_to_heightmap(png_bytes)
    print(f"  Heightmap: {heightmap.shape[0]}×{heightmap.shape[1]} px")

    # ── Load mesh ──────────────────────────────────────────────────────────
    suffix = model_path.suffix.lower()
    if suffix == ".stl":
        mesh = pv.read(str(model_path))
    elif suffix == ".3mf":
        tm = trimesh.load(str(model_path), force="mesh")
        if isinstance(tm, trimesh.Scene):
            geoms = list(tm.geometry.values())
            tm = trimesh.util.concatenate(geoms) if len(geoms) > 1 else geoms[0]
        mesh = pv.wrap(tm)
    else:
        print(f"Unsupported format: {suffix}", file=sys.stderr)
        sys.exit(1)
    print(f"Loaded  : {mesh.n_points} pts, {mesh.n_cells} cells")

    # ── Subdivide ──────────────────────────────────────────────────────────
    if args.subdivide > 0:
        print(f"Subdividing {args.subdivide}x …", end=" ", flush=True)
        mesh = mesh.subdivide(args.subdivide, subfilter="linear")
        print(f"→ {mesh.n_points} pts")

    # ── Auto tile ──────────────────────────────────────────────────────────
    tiles = args.tile
    if tiles <= 0:
        bnd = mesh.bounds
        span_u = bnd[1] - bnd[0]
        span_v = bnd[3] - bnd[2]
        tiles  = max(1, round(max(span_u, span_v) / 25.0))
        print(f"Auto tile: {tiles}×{tiles}")

    # ── Displace ───────────────────────────────────────────────────────────
    print("Displacing vertices …", end=" ", flush=True)
    displaced = apply_displacement(mesh, heightmap, args.depth, tiles, args.axis)
    print("done")

    # ── Save ───────────────────────────────────────────────────────────────
    print(f"Saving  : {model_path} …", end=" ", flush=True)
    if suffix == ".stl":
        displaced.save(str(model_path))
    else:
        pts  = np.array(displaced.points)
        tris = displaced.faces.reshape(-1, 4)[:, 1:]
        trimesh.Trimesh(vertices=pts, faces=tris).export(str(model_path))
    print("done")
    print("\nSuccess — reload the model in QIDIStudio to see the result.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
