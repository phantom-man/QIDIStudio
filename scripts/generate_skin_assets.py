#!/usr/bin/env python3
"""
generate_skin_assets.py
========================
Pre-generate all QIDIStudio skin-texture displacement-map assets using
Google Imagen 3 via Vertex AI (ADC — run 'gcloud auth application-default login' first).

Generates 20 images per texture category across 28 categories = 560 PNG files.
All images are proper black-and-white top-down orthographic displacement maps
suitable for import to QIDIStudio's "Add Skin" feature.

Output structure:
    install_dir/resources/assets/<category>/<category>_01.png  ...  _20.png

Usage:
    python generate_skin_assets.py                         # all categories
    python generate_skin_assets.py --category reptile_scales  # one category
    python generate_skin_assets.py --list                  # list categories
    python generate_skin_assets.py --dry-run               # show prompts, no API calls
    python generate_skin_assets.py --resume                # skip already-generated files

Requirements:
    pip install google-cloud-aiplatform vertexai Pillow

Authentication:
    gcloud auth application-default login
"""

import argparse
import os
import sys
import time
import pathlib
from typing import Iterator
from PIL import Image

# ── Config ────────────────────────────────────────────────────────────────────
GCP_PROJECT  = "crafty-hook-483415-b3"
GCP_LOCATION = "us-central1"
IMG_MODEL    = "imagen-3.0-generate-001"

# Primary output: QIDIStudio install directory.
# Override with QIDI_ASSETS_DIR env var for non-default install paths:
#   set QIDI_ASSETS_DIR=D:\MyInstall\resources\assets
INSTALL_ASSETS = pathlib.Path(
    os.environ.get("QIDI_ASSETS_DIR",
                   r"C:\QIDISrc\QIDIStudio\install_dir\resources\assets")
)
# Mirror: fork repo for version control (small PNGs are OK to commit)
FORK_ASSETS    = pathlib.Path(__file__).parent.parent / "resources" / "assets"

# ── Prompt building ───────────────────────────────────────────────────────────
# Every prompt ends with this invariant suffix that forces the right image type
# for QIDIStudio's vertex-displacement pipeline.
_SUFFIX = (
    ", top-down orthographic view, high contrast black and white, "
    "no shading, no 3D lighting, no shadows, flat 2D displacement map, "
    "seamless tileable pattern, mathematically precise, 8k resolution detail"
)

# 4 scale modifiers × 5 depth modifiers = 20 combinations
_SCALE_MODS = [
    "fine-pitch micro-scale",
    "small-scale",
    "medium-scale",
    "large coarse-scale",
]
_DEPTH_MODS = [
    "shallow subtle relief, soft gradients",
    "medium depth relief, clear definition",
    "deep pronounced relief, strong contrast",
    "extreme sharp angular relief, maximum contrast",
    "ultra-fine micro-relief, tight pitch, delicate detail",
]


def _make_20_prompts(base: str) -> list[str]:
    """Generate 20 prompt variants from a base description."""
    out = []
    for scale in _SCALE_MODS:
        for depth in _DEPTH_MODS:
            out.append(f"{scale}, {base}, {depth}{_SUFFIX}")
    return out  # exactly 20: 4 × 5


# ── Texture categories ────────────────────────────────────────────────────────
# Key = directory name, value = base description for the prompt
CATEGORIES: dict[str, str] = {

    # ── Organic skin / biological surfaces ───────────────────────────────────

    "reptile_scales": (
        "ultra-detailed seamless reptilian skin texture, "
        "sharp interlocking hexagonal scales, biological snake skin pattern, "
        "geometric tessellation of overlapping keratin plates"
    ),
    "dragon_scales": (
        "ultra-detailed fantasy dragon scales, "
        "large overlapping diamond-shaped armored scales, "
        "deep ridges between each scale plate, mythological reptile skin"
    ),
    "fish_scales": (
        "seamless fish scale pattern, "
        "semicircular overlapping ctenoid scales, aquatic surface texture, "
        "concentric rings on each scale, dense tessellation"
    ),
    "crocodile_skin": (
        "crocodile and alligator ostoderm skin pattern, "
        "irregular bony scutes and plates, asymmetric bumpy armor texture, "
        "pitted surface with keeled ridges between plates"
    ),
    "shark_skin": (
        "microscopic shark skin denticle pattern, "
        "tiny placoid scale teeth covering entire surface, hydrodynamic ridges, "
        "uniform directional texture like fine sand under magnification"
    ),
    "feather_pattern": (
        "bird feather barb and barbule pattern, "
        "overlapping herringbone feather arrangement, "
        "fine parallel vane structure with interlocking hooks"
    ),
    "leather_pebble": (
        "full-grain pebbled leather texture, "
        "irregular raised bumps covering entire surface uniformly, "
        "natural hide grain pattern, tactile surface similar to fine leather goods"
    ),
    "pine_cone_scales": (
        "pine cone scale pattern, "
        "large geometric overlapping bracts arranged in Fibonacci spiral, "
        "woody seed protective plates, conifer cone surface texture"
    ),
    "armadillo_plates": (
        "armadillo shell plate pattern, "
        "rigid overlapping osteoderms in banded rows, "
        "regular geometric carapace with sutured edges between plates"
    ),

    # ── Industrial / machined metal surfaces ─────────────────────────────────

    "chainmail": (
        "chainmail armor ring pattern, "
        "interlocked metal rings in 4-in-1 weave pattern, "
        "each ring linking four neighbors, medieval armor surface"
    ),
    "diamond_knurl": (
        "diamond knurl machine-tool pattern, "
        "crossed diagonal raised ridges forming perfect diamond grid, "
        "CNC-machined grip texture surface for metal shafts and handles"
    ),
    "hammered_metal": (
        "hammered metal surface texture, "
        "overlapping circular peening dimples from ball-peen hammer, "
        "artisan blacksmith beaten plate surface, depth creates reflective facets"
    ),
    "carbon_fiber": (
        "2x2 twill weave carbon fiber composite pattern, "
        "diagonal weave of interlocked tows at 45 degrees, "
        "aerospace material surface texture, glossy weave pattern under magnification"
    ),
    "riveted_metal": (
        "industrial riveted metal plate pattern, "
        "regular grid of flat-head rivet circles on steel plate, "
        "boiler plate or ship hull surface texture, each rivet slightly raised"
    ),
    "chain_link": (
        "chain-link fence diamond pattern, "
        "interlocked wire segments forming tilted square grid, "
        "galvanized wire mesh surface as seen from above"
    ),

    # ── Natural / geological surfaces ─────────────────────────────────────────

    "bark_texture": (
        "tree bark surface texture, "
        "deep fissures and ridges in organic random pattern, "
        "old growth hardwood bark with deep crevices and raised furrows"
    ),
    "wood_grain": (
        "straight wood grain surface texture, "
        "parallel flowing grain lines with ring variation, "
        "quartersawn lumber face grain, dense fine wood fiber pattern"
    ),
    "cobblestone": (
        "cobblestone paving surface, "
        "irregular rounded stone pavers with deep mortar joints, "
        "old European street cobble pattern, each stone slightly convex"
    ),
    "coral_texture": (
        "brain coral surface texture, "
        "organic labyrinthine ridge and valley pattern of stony coral, "
        "meandrine convolutions of coral polyp architecture"
    ),
    "lava_rock": (
        "vesicular basalt lava rock surface, "
        "porous surface with gas bubble voids of varying size, "
        "volcanic rock texture with scattered pits and rough matrix"
    ),

    # ── Geometric and decorative patterns ────────────────────────────────────

    "honeycomb": (
        "perfect hexagonal honeycomb grid pattern, "
        "natural bee honeycomb with raised cell walls, "
        "mathematical tessellation of regular hexagons, engineered precision"
    ),
    "voronoi_cells": (
        "organic Voronoi tessellation pattern, "
        "irregular polygonal cells divided by straight edges, "
        "biological foam cell structure, natural crack pattern"
    ),
    "celtic_knotwork": (
        "Celtic knotwork interlace pattern, "
        "over-under weaving ribbon with no loose ends, "
        "continuous interlaced strand forming geometric knot"
    ),
    "moroccan_tiles": (
        "Moroccan zellige tilework geometric pattern, "
        "Islamic star-and-polygon tessellation with eight-point stars, "
        "Alhambra-style geometric interlace, mathematical precision"
    ),
    "circuit_board": (
        "printed circuit board trace pattern, "
        "electrical traces, via pads and solder pads on PCB surface, "
        "high-tech electronic surface with conductor routing"
    ),
    "woven_basket": (
        "over-under basket weave pattern, "
        "square plaiting with alternating warp and weft elements, "
        "wicker or rattan woven surface texture"
    ),
    "brick_pattern": (
        "standard running bond brick pattern, "
        "rectangular bricks with offset mortar joints, "
        "masonry wall surface with recessed mortar, each brick slightly raised"
    ),
    "herringbone": (
        "herringbone floor tile pattern, "
        "rectangular tiles arranged in V-shaped zigzag, "
        "parquet floor pattern with alternating 45-degree angles"
    ),
}


def iter_generation_jobs(categories: list[str]) -> Iterator[tuple[str, int, str]]:
    """Yield (category, index_1_based, prompt) for every image to generate."""
    for cat in categories:
        base   = CATEGORIES[cat]
        prompts = _make_20_prompts(base)
        for i, prompt in enumerate(prompts, start=1):
            yield cat, i, prompt


# ── Procedural pattern generation (Shapely + PIL — no API calls) ──────────────
#
# For geometric categories where math beats AI: generates mathematically precise,
# perfectly seamless B&W displacement maps locally at zero cost.
#
# 20 variants = 4 tile pitches × 5 depth-gradient styles
#   Pitches (tiles across image): 4, 6, 10, 16
#   Depths:  flat | bevel | dome | sharp | micro

try:
    import math as _math
    import random as _random
    from shapely.geometry import (Polygon as _SPoly, Point as _SPoint,
                                   MultiPoint as _SMultiPt)
    from shapely.ops import voronoi_diagram as _voronoi
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False

_PROC_IMG     = 512
_PROC_PITCHES = [4, 6, 10, 16]
_PROC_DEPTHS  = ["flat", "bevel", "dome", "sharp", "micro"]


def _apply_depth(img: "Image.Image", style: str) -> "Image.Image":
    """Apply distance-transform depth gradient to a binary polygon mask."""
    if style == "flat":
        return img
    try:
        import numpy as _np
        from scipy.ndimage import distance_transform_edt as _dte
        arr  = _np.asarray(img, dtype=_np.float32)
        dist = _dte(arr > 127).astype(_np.float32)
        d    = dist / max(float(dist.max()), 1e-5)
        if   style == "bevel":  out = d
        elif style == "dome":   out = _np.cos((1.0 - d) * _math.pi / 2.0)
        elif style == "sharp":  out = _np.minimum(d * 4.0, 1.0)
        else:                   out = _np.cos((1.0 - _np.minimum(d * 2.0, 1.0)) * _math.pi / 2.0)
        return Image.fromarray((out * 255.0).clip(0, 255).astype(_np.uint8), "L")
    except ImportError:
        return img   # scipy absent — stay flat


def _render(polys: list, depth: str) -> "Image.Image":
    """Render Shapely polygons (world coords 0..1 × 0..1) to a grayscale PIL image."""
    from PIL import ImageDraw
    img  = Image.new("L", (_PROC_IMG, _PROC_IMG), 0)
    draw = ImageDraw.Draw(img)
    S    = _PROC_IMG

    def _fill(poly):
        if poly.is_empty:
            return
        if poly.geom_type == "MultiPolygon":
            for g in poly.geoms: _fill(g)
            return
        if poly.geom_type != "Polygon":
            return
        draw.polygon([(x * S, (1 - y) * S) for x, y in poly.exterior.coords], fill=255)
        for hole in poly.interiors:
            draw.polygon([(x * S, (1 - y) * S) for x, y in hole.coords], fill=0)

    for p in polys:
        _fill(p)
    return _apply_depth(img, depth)


def _gen_honeycomb(n: int, depth: str) -> "Image.Image":
    pitch = 1.0 / n
    ir    = pitch * 0.45                        # inner radius leaves ~10% gap for walls
    row_h = pitch * _math.sqrt(3) / 2
    polys = []
    for row in range(-1, int(1.3 / row_h) + 2):
        for col in range(-1, n + 2):
            cx = (col + (0.5 if row % 2 else 0.0)) * pitch
            cy = row * row_h
            polys.append(_SPoly([(cx + ir * _math.cos(_math.pi / 6 + _math.pi * 2 * k / 6),
                                   cy + ir * _math.sin(_math.pi / 6 + _math.pi * 2 * k / 6))
                                  for k in range(6)]))
    return _render(polys, depth)


def _gen_diamond_knurl(n: int, depth: str) -> "Image.Image":
    pitch = 1.0 / n
    h     = pitch * 0.41
    polys = []
    for i in range(-1, n + 2):
        for j in range(-1, n + 2):
            for dx, dy in [(0.0, 0.0), (0.5, 0.5)]:
                cx, cy = (i + dx) * pitch, (j + dy) * pitch
                polys.append(_SPoly([(cx, cy + h), (cx + h, cy),
                                      (cx, cy - h), (cx - h, cy)]))
    return _render(polys, depth)


def _gen_voronoi_cells(n: int, depth: str, seed: int = 42) -> "Image.Image":
    from shapely.geometry import box as _sbox
    rng    = _random.Random(seed + n)
    canvas = _sbox(0, 0, 1, 1)
    pts    = [(rng.uniform(0.02, 0.98), rng.uniform(0.02, 0.98)) for _ in range(n * n)]
    border = [(x, y) for x in [-0.1, 0.5, 1.1] for y in [-0.1, 0.5, 1.1]]
    regions = _voronoi(_SMultiPt(pts + border), envelope=canvas.buffer(0.05)).geoms
    polys   = [r.intersection(canvas).buffer(-0.003)
               for r in regions if not r.intersection(canvas).is_empty]
    return _render([p for p in polys if not p.is_empty], depth)


def _gen_chainmail(n: int, depth: str) -> "Image.Image":
    pitch = 1.0 / n
    r_out, r_in = pitch * 0.46, pitch * 0.28
    row_p = pitch * 0.87
    polys = []
    for row in range(-1, int(1.3 / row_p) + 2):
        for col in range(-1, n + 2):
            cx = (col + (0.5 if row % 2 else 0.0)) * pitch
            cy = row * row_p
            polys.append(_SPoint(cx, cy).buffer(r_out)
                          .difference(_SPoint(cx, cy).buffer(r_in)))
    return _render(polys, depth)


def _gen_brick_pattern(n: int, depth: str) -> "Image.Image":
    from shapely.geometry import box as _sbox
    pitch = 1.0 / n
    bw  = pitch * 1.95
    bh  = pitch * 0.85
    gap = pitch * 0.10
    polys = []
    row_h = bh + gap
    for row in range(-1, int(1.3 / row_h) + 2):
        offset = (0.5 if row % 2 else 0.0) * (bw + gap)
        cy = row * row_h
        for col in range(-1, n + 2):
            cx = col * (bw + gap) + offset
            polys.append(_sbox(cx, cy, cx + bw, cy + bh))
    return _render(polys, depth)


def _gen_herringbone(n: int, depth: str) -> "Image.Image":
    from shapely.geometry import box as _sbox
    pitch = 1.0 / n
    pw  = pitch * 1.9   # plank length
    ph  = pitch * 0.42  # plank width
    gap = pitch * 0.06
    step = pw + gap
    polys = []
    for i in range(-2, int(1.5 / step) + 3):
        for j in range(-2, int(1.5 / step) + 3):
            ox, oy = i * step, j * step
            polys.append(_sbox(ox, oy, ox + pw, oy + ph))                      # horizontal
            polys.append(_sbox(ox + pw - ph, oy - pw + ph, ox + pw, oy))       # vertical
    return _render(polys, depth)


def _gen_riveted_metal(n: int, depth: str) -> "Image.Image":
    pitch = 1.0 / n
    r     = pitch * 0.34
    polys = [_SPoint((i + 0.5) * pitch, (j + 0.5) * pitch).buffer(r)
             for i in range(-1, n + 2) for j in range(-1, n + 2)]
    return _render(polys, depth)


# Map category → generator.  Only populated when Shapely is importable.
PROCEDURAL_GENERATORS: dict = {
    "honeycomb":      _gen_honeycomb,
    "diamond_knurl":  _gen_diamond_knurl,
    "voronoi_cells":  _gen_voronoi_cells,
    "chainmail":      _gen_chainmail,
    "brick_pattern":  _gen_brick_pattern,
    "herringbone":    _gen_herringbone,
    "riveted_metal":  _gen_riveted_metal,
} if _HAS_SHAPELY else {}


def generate_procedural(category: str, idx: int, out_path: pathlib.Path) -> bool:
    """
    Generate image `idx` (1-based, 1-20) for a procedural category.
    20 variants = 4 pitches × 5 depth styles (flat/bevel/dome/sharp/micro).
    Returns True on success, False if category not procedural or error.
    """
    gen = PROCEDURAL_GENERATORS.get(category)
    if gen is None:
        return False
    i_zero  = idx - 1
    n_tiles = _PROC_PITCHES[i_zero // 5]
    depth   = _PROC_DEPTHS[i_zero % 5]
    try:
        img = gen(n_tiles, depth)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_path))
        return True
    except Exception as e:
        print(f"    Procedural error ({n_tiles}t/{depth}): {e}")
        return False


# ── Vertex AI image generation ────────────────────────────────────────────────
_model = None

def _get_model():
    global _model
    if _model is None:
        from vertexai.preview.vision_models import ImageGenerationModel
        import vertexai
        vertexai.init(project=GCP_PROJECT, location=GCP_LOCATION)
        _model = ImageGenerationModel.from_pretrained(IMG_MODEL)
        print(f"Imagen model loaded: {IMG_MODEL}")
    return _model


def generate_one(prompt: str, out_path: pathlib.Path, retries: int = 3) -> bool:
    """Generate a single image and save it as PNG.  Returns True on success."""
    for attempt in range(1, retries + 1):
        try:
            model = _get_model()
            result = model.generate_images(
                prompt=prompt,
                number_of_images=1,
                aspect_ratio="1:1",
                safety_filter_level="block_few",
                person_generation="dont_allow",
            )
            if not result.images:
                print(f"    WARNING: empty result (attempt {attempt})")
                time.sleep(2.0)
                continue

            out_path.parent.mkdir(parents=True, exist_ok=True)
            result.images[0].save(str(out_path))
            return True

        except Exception as e:
            wait = 4.0 * attempt
            print(f"    ERROR attempt {attempt}/{retries}: {e}")
            if attempt < retries:
                print(f"    Waiting {wait:.0f}s …")
                time.sleep(wait)

    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--category", default=None,
        help="Generate only this one category (default: all).")
    parser.add_argument("--list",     action="store_true",
        help="List all categories and exit.")
    parser.add_argument("--dry-run",  action="store_true",
        help="Print all prompts but make no API calls.")
    parser.add_argument("--resume",   action="store_true",
        help="Skip images that already exist on disk.")
    parser.add_argument("--out-dir",  default=None,
        help=f"Override output root directory (default: {INSTALL_ASSETS}).")
    parser.add_argument("--procedural-only", action="store_true",
        help="Only generate procedural categories (no API calls). Ignored if Shapely not installed.")
    args = parser.parse_args()

    if args.list:
        n_proc = len(PROCEDURAL_GENERATORS)
        print(f"{len(CATEGORIES)} texture categories  ({n_proc} procedural/local, rest via Vertex AI):")
        for cat, base in CATEGORIES.items():
            tag    = " [local]" if cat in PROCEDURAL_GENERATORS else ""
            n_words = len(base.split())
            print(f"  {cat:<28}{tag:<10} — {base[:55]}{'...' if n_words > 10 else ''}")
        return

    # Determine output root
    out_root = pathlib.Path(args.out_dir) if args.out_dir else INSTALL_ASSETS
    print(f"Output root : {out_root}")
    print(f"Fork mirror : {FORK_ASSETS}")

    # Determine which categories to generate
    categories = list(CATEGORIES.keys())
    if args.category:
        if args.category not in CATEGORIES:
            print(f"ERROR: unknown category '{args.category}'.")
            print(f"Available: {', '.join(CATEGORIES.keys())}")
            sys.exit(1)
        categories = [args.category]

    total    = len(categories) * 20
    done     = 0
    skipped  = 0
    failed   = 0

    print(f"\nPlan: {len(categories)} categories × 20 images = {total} total")
    if PROCEDURAL_GENERATORS:
        proc_cats = [c for c in categories if c in PROCEDURAL_GENERATORS]
        print(f"  {len(proc_cats)} procedural (local, no API): {', '.join(proc_cats)}")
    if args.dry_run:
        print("DRY-RUN — no API calls will be made.\n")

    for cat, idx, prompt in iter_generation_jobs(categories):
        fname    = f"{cat}_{idx:02d}.png"
        out_path = out_root / cat / fname
        fork_path = FORK_ASSETS / cat / fname

        if args.resume and out_path.exists():
            skipped += 1
            done += 1
            continue

        is_proc = cat in PROCEDURAL_GENERATORS
        tag     = " [local]" if is_proc else " [AI]"
        print(f"[{done+1}/{total}] {cat}/{fname}{tag}")
        if args.dry_run:
            if not is_proc:
                print(f"  Prompt: {prompt[:120]}")
            done += 1
            continue

        # Try procedural generator first (instant, no API), then fall back to AI.
        ok = False
        if is_proc:
            ok = generate_procedural(cat, idx, out_path)
        if not ok:
            if args.procedural_only:
                continue    # skip AI call; don't count toward done/skipped/failed
            ok = generate_one(prompt, out_path)
            if ok:
                time.sleep(1.1)   # rate-limit only AI calls

        if ok:
            # Mirror to fork repo
            fork_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(str(out_path), str(fork_path))
            done += 1
            print(f"  OK  ({out_path.stat().st_size // 1024} KB)")
        else:
            failed += 1
            done += 1
            print(f"  FAILED {'(procedural)' if is_proc else 'after retries'}")

    print(f"\n=== Done  generated={done - skipped - failed}  "
          f"skipped={skipped}  failed={failed}  total={total} ===")
    if failed:
        print("Re-run with --resume to retry failed images.")


if __name__ == "__main__":
    main()
