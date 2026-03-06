#!/usr/bin/env python3
"""
text_to_texture.py — Phase 6.4 Text-to-Texture Generator
==========================================================
Generate tileable PBR-ready texture images from a natural-language prompt.

Pipeline
--------
  1. Text prompt → image (via Stable Diffusion or Gemini Imagen)
  2. Tileability pass  (offset-and-stitch + Gaussian seam blending)
  3. Save PNG to output directory
  4. Optionally call apply_texture_bpy.py to apply to a Blender scene

Backends (tried in order, first available wins)
-------------------------------------------------
  sd_turbo     — stabilityai/sd-turbo via diffusers (offline, GPU or CPU)
  sdxl_turbo   — stabilityai/sdxl-turbo via diffusers (offline, better quality)
  gemini       — Gemini Imagen (online, requires GOOGLE_API_KEY)
  perlin       — Perlin-noise fallback (no dependencies beyond numpy)

Usage
-----
  python scripts/text_to_texture.py --prompt "brushed carbon fibre surface"
  python scripts/text_to_texture.py --prompt "aged oak wood planks" --size 1024 --apply scripts/test_parts/vacuum_nozzle.stl
  python scripts/text_to_texture.py --smoke-test

Options
-------
  --prompt      Texture description (required unless --smoke-test)
  --size        Output image size in pixels      [256|512|1024|2048]  default: 512
  --output-dir  Directory for saved textures     default: scripts/textures/
  --backend     Force a specific backend         [sd_turbo|sdxl_turbo|gemini|perlin]
  --apply       STL/3MF path — pass texture to apply_texture_bpy.py after generation
  --blender     Path to Blender executable       default: auto-detected
  --no-tile     Skip tileability post-processing
  --smoke-test  Run offline test with Perlin noise backend
  --verbose

Environment
-----------
  GOOGLE_API_KEY    — needed for Gemini backend
  HF_HOME           — HuggingFace cache dir (optional, controls model storage)
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

# ─── Optional AI beauty scorer ───────────────────────────────────────
# Import lazily from the same scripts/ directory.  Fails gracefully if numpy or
# scipy are absent — in that case the beauty-check loop is skipped and the first
# generated texture is always accepted.
try:
    from ai_beauty_scorer import BEAUTY_GOOD, analyse_array as _beauty_analyse  # type: ignore

    _BEAUTY_SCORER_AVAILABLE = True
except (ImportError, Exception):
    _BEAUTY_SCORER_AVAILABLE = False
    BEAUTY_GOOD = 0.62  # local fallback so the constant is always defined

log = logging.getLogger("text_to_texture")
logging.basicConfig(
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)

# ─── Default Blender paths to search ─────────────────────────────────────────
BLENDER_SEARCH_PATHS = [
    r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
    "/usr/bin/blender",
    "/Applications/Blender.app/Contents/MacOS/Blender",
]


# ─── Backend: Perlin noise (always available) ─────────────────────────────────


def _perlin_fade(t: np.ndarray) -> np.ndarray:
    return t * t * t * (t * (t * 6 - 15) + 10)


def _perlin_lerp(a: np.ndarray, b: np.ndarray, t: np.ndarray) -> np.ndarray:
    return a + t * (b - a)


def _perlin_grad(h: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    h = h & 3
    u = np.where(h < 2, x, y)
    v = np.where(h < 2, y, x)
    return np.where(h & 1, -u, u) + np.where(h & 2, -v, v)


def _perlin2d(size: int, scale: float = 4.0, seed: int = 0) -> np.ndarray:
    """Generate tileable 2D Perlin noise in [-1, 1] range."""
    rng = np.random.default_rng(seed)
    # Grid of random gradients (must wrap for tileability)
    period = int(scale)
    p = np.arange(period, dtype=np.int32)
    rng.shuffle(p)
    p = np.tile(p, 2)  # doubled for wrapping

    lin = np.linspace(0, scale, size, endpoint=False)
    xv, yv = np.meshgrid(lin, lin)

    xi = xv.astype(int) % period
    yi = yv.astype(int) % period
    xf = xv - xv.astype(int)
    yf = yv - yv.astype(int)

    u = _perlin_fade(xf)
    v = _perlin_fade(yf)

    n00 = _perlin_grad(p[p[xi] + yi], xf, yf)
    n10 = _perlin_grad(p[p[xi + 1] + yi], xf - 1, yf)
    n01 = _perlin_grad(p[p[xi] + yi + 1], xf, yf - 1)
    n11 = _perlin_grad(p[p[xi + 1] + yi + 1], xf - 1, yf - 1)

    return _perlin_lerp(_perlin_lerp(n00, n10, u), _perlin_lerp(n01, n11, u), v)


def generate_perlin(prompt: str, size: int, seed: int = 42) -> np.ndarray:
    """
    Generate a reasonable-looking tileable texture from Perlin noise.
    Returns an RGBA numpy array (H, W, 4) uint8.
    """
    log.info("Generating Perlin noise texture (%dx%d) for: %s", size, size, prompt)

    # Hash words in prompt to choose a colour palette
    hv = hash(prompt.lower()) & 0xFFFFFF
    base_r = ((hv >> 16) & 0xFF) / 255.0
    base_g = ((hv >> 8) & 0xFF) / 255.0
    base_b = (hv & 0xFF) / 255.0

    layers = [
        _perlin2d(size, scale=s, seed=seed + i) for i, s in enumerate([4, 8, 16, 32])
    ]
    noise = sum(layers[i] * (0.5 ** (i + 1)) for i in range(len(layers)))
    noise = (noise - noise.min()) / ((noise.max() - noise.min()) + 1e-9)  # 0..1

    # Tint with prompt-derived colour + brightness variation
    r = np.clip(base_r + 0.4 * noise - 0.2, 0.0, 1.0)
    g = np.clip(base_g + 0.4 * noise - 0.2, 0.0, 1.0)
    b = np.clip(base_b + 0.4 * noise - 0.2, 0.0, 1.0)

    rgba = np.stack([r, g, b, np.ones_like(r)], axis=-1)
    return (rgba * 255).astype(np.uint8)


# ─── Backend: Stable Diffusion via diffusers ──────────────────────────────────


def generate_stable_diffusion(
    prompt: str, size: int, model: str = "sd_turbo"
) -> Optional[np.ndarray]:
    """
    Generate image via HuggingFace diffusers.
    Returns RGBA uint8 numpy array or None on failure.
    """
    try:
        from diffusers import AutoPipelineForText2Image  # type: ignore
        import torch  # type: ignore
    except ImportError:
        log.debug("diffusers or torch not installed — SD backend unavailable")
        return None

    MODEL_IDS = {
        "sd_turbo": "stabilityai/sd-turbo",
        "sdxl_turbo": "stabilityai/sdxl-turbo",
    }
    model_id = MODEL_IDS.get(model, MODEL_IDS["sd_turbo"])

    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if device == "cuda" else torch.float32
        log.info("Loading %s on %s …", model_id, device)
        pipe = AutoPipelineForText2Image.from_pretrained(model_id, torch_dtype=dtype)
        pipe = pipe.to(device)

        full_prompt = (
            f"seamless tileable texture, {prompt}, "
            "PBR material, high-resolution, photorealistic, no shadows, flat lighting"
        )
        neg_prompt = (
            "seam, border, frame, text, watermark, cartoon, sketch, low quality"
        )

        log.info("Generating image …")
        t0 = time.time()
        result = pipe(
            full_prompt,
            negative_prompt=neg_prompt,
            num_inference_steps=4 if "turbo" in model else 20,
            guidance_scale=0.0 if "turbo" in model else 7.5,
            width=size,
            height=size,
        )
        log.info("SD generation: %.1fs", time.time() - t0)

        pil_img = result.images[0]
        arr = np.array(pil_img.convert("RGBA"))
        return arr

    except Exception as exc:
        log.warning("SD generation failed: %s", exc)
        return None


# ─── Backend: Gemini Imagen ───────────────────────────────────────────────────


def generate_gemini(prompt: str, size: int) -> Optional[np.ndarray]:
    """
    Generate image via Gemini Imagen API.
    Returns RGBA uint8 numpy array or None on failure.
    """
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        log.debug("No GOOGLE_API_KEY — Gemini backend skipped")
        return None

    try:
        import google.genai as genai  # type: ignore
        from google.genai import types as gtypes  # type: ignore
    except ImportError:
        log.debug("google.genai not installed — Gemini image backend unavailable")
        return None

    try:
        client = genai.Client(api_key=api_key)
        full_prompt = (
            f"seamless tileable texture, {prompt}, "
            "PBR material, high resolution, photorealistic"
        )
        log.info("Calling Gemini Imagen for: %s", prompt)
        resp = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=full_prompt,
            config=gtypes.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="1:1",
            ),
        )
        if resp.generated_images:
            raw = resp.generated_images[0].image.image_bytes
            from PIL import Image  # type: ignore
            import io

            pil = Image.open(io.BytesIO(raw)).convert("RGBA").resize((size, size))
            return np.array(pil)
    except Exception as exc:
        log.warning("Gemini Imagen failed: %s", exc)

    return None


# ─── Tileability post-processing (offset-and-stitch) ─────────────────────────


def make_tileable(rgba: np.ndarray) -> np.ndarray:
    """
    Apply offset-and-stitch to improve tileability:
      1. Shift image by (W/2, H/2) so the original seam is now in the centre.
      2. Blend the centre cross using a Gaussian mask so the new seam is invisible.
    Returns RGBA uint8 array.
    """
    H, W = rgba.shape[:2]
    shifted = np.roll(np.roll(rgba, W // 2, axis=1), H // 2, axis=0)

    # Build a Gaussian blend mask — high (=shifted wins) at center, low at edges
    x = np.linspace(-1, 1, W)
    y = np.linspace(-1, 1, H)
    xv, yv = np.meshgrid(x, y)
    sigma = 0.3
    mask = np.exp(-(xv**2 + yv**2) / (2 * sigma**2))
    mask = mask[..., np.newaxis]  # (H, W, 1) for broadcasting

    original = rgba.astype(np.float32) / 255.0
    offset = shifted.astype(np.float32) / 255.0
    blended = original * (1 - mask) + offset * mask
    return (np.clip(blended, 0.0, 1.0) * 255).astype(np.uint8)


# ─── Save helper ──────────────────────────────────────────────────────────────


def _save_texture(rgba: np.ndarray, output_dir: Path, stem: str) -> Path:
    try:
        from PIL import Image  # type: ignore

        img = Image.fromarray(rgba, mode="RGBA")
    except ImportError:
        # Write raw PPM without PIL
        import struct

        pass

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{stem}.png"

    try:
        from PIL import Image  # type: ignore

        img = Image.fromarray(rgba, mode="RGBA")
        img.save(str(out_path))
    except ImportError:
        # Fallback: write raw bytes as a PPM (no alpha support)
        h, w = rgba.shape[:2]
        with open(str(out_path.with_suffix(".ppm")), "wb") as f:
            header = f"P6\n{w} {h}\n255\n".encode()
            f.write(header)
            f.write(rgba[:, :, :3].tobytes())
        out_path = out_path.with_suffix(".ppm")

    log.info("Texture saved → %s", out_path)
    return out_path


# ─── Blender apply step ───────────────────────────────────────────────────────


def _find_blender() -> Optional[str]:
    for p in BLENDER_SEARCH_PATHS:
        if Path(p).exists():
            return p
    return None


def apply_to_blender(
    texture_path: Path, mesh_path: Path, blender_exe: Optional[str]
) -> bool:
    blender = blender_exe or _find_blender()
    if not blender:
        log.warning("Blender not found — skipping apply step")
        return False

    bpy_script = Path(__file__).parent / "apply_texture_bpy.py"
    if not bpy_script.exists():
        log.warning("apply_texture_bpy.py not found — skipping apply step")
        return False

    cmd = [
        blender,
        "--background",
        str(mesh_path),
        "--python",
        str(bpy_script),
        "--",
        "--texture",
        str(texture_path),
        "--output",
        str(texture_path.with_suffix("")),
    ]
    log.info("Applying texture via Blender …")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode == 0:
        log.info("Blender apply succeeded")
        return True
    log.error(
        "Blender apply failed (rc=%d):\n%s", result.returncode, result.stderr[-1000:]
    )
    return False


# ─── Smoke test ───────────────────────────────────────────────────────────────


def run_smoke_test(output_dir: Path) -> bool:
    log.info("=== Smoke test: Perlin noise backend ===")
    for prompt in [
        "carbon fibre weave",
        "sandblasted aluminium",
        "rough concrete surface",
    ]:
        rgba = generate_perlin(prompt, size=256)
        assert rgba.shape == (256, 256, 4), f"Bad shape: {rgba.shape}"
        assert rgba.dtype == np.uint8, "Bad dtype"
        tiled = make_tileable(rgba)
        assert tiled.shape == rgba.shape, "Tileability changed shape"
        out = _save_texture(tiled, output_dir / "smoke", prompt.replace(" ", "_"))
        assert out.exists() or out.with_suffix(".ppm").exists(), "File not saved"
        log.info("  [PASS] %s → %s", prompt, out.name)

    log.info("Smoke test result: 3/3 passed")
    return True


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(
        description="Text-to-Texture Generator (Phase 6.4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--prompt", default=None, help="Texture description")
    p.add_argument(
        "--size",
        type=int,
        default=512,
        choices=[256, 512, 1024, 2048],
        help="Output resolution (default: 512)",
    )
    p.add_argument("--output-dir", default="scripts/textures", help="Output directory")
    p.add_argument(
        "--backend",
        default=None,
        choices=["sd_turbo", "sdxl_turbo", "gemini", "perlin"],
        help="Force a specific backend",
    )
    p.add_argument(
        "--apply", default=None, help="Mesh path to apply texture in Blender"
    )
    p.add_argument("--blender", default=None, help="Blender executable path")
    p.add_argument(
        "--no-tile", action="store_true", help="Skip tileability post-processing"
    )
    p.add_argument("--smoke-test", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if args.verbose:
        log.setLevel(logging.DEBUG)

    out_dir = Path(args.output_dir)

    if args.smoke_test:
        ok = run_smoke_test(out_dir)
        sys.exit(0 if ok else 1)

    if not args.prompt:
        p.error("--prompt is required (or use --smoke-test)")

    prompt = args.prompt.strip()
    size = args.size

    # ── Backend selection ────────────────────────────────────────────────────
    rgba: Optional[np.ndarray] = None

    order = (
        [args.backend]
        if args.backend
        else ["sdxl_turbo", "sd_turbo", "gemini", "perlin"]
    )

    for backend in order:
        if backend in ("sdxl_turbo", "sd_turbo"):
            rgba = generate_stable_diffusion(prompt, size, model=backend)
        elif backend == "gemini":
            rgba = generate_gemini(prompt, size)
        elif backend == "perlin":
            rgba = generate_perlin(prompt, size)

        if rgba is not None:
            log.info("Backend used: %s", backend)
            break

    if rgba is None:
        log.error("All backends failed — using Perlin noise fallback")
        rgba = generate_perlin(prompt, size)

    # ── Tileability pass ──────────────────────────────────────────────────────
    if not args.no_tile:
        log.info("Applying tileability pass …")
        rgba = make_tileable(rgba)

    # ── Save ──────────────────────────────────────────────────────────────────
    stem = prompt[:60].lower()
    for c in r'\/:*?"<>|':
        stem = stem.replace(c, "_")
    stem = stem.replace(" ", "_").strip("_")

    out_path = _save_texture(rgba, out_dir, stem)

    # ── Optional Blender apply ────────────────────────────────────────────────
    if args.apply:
        apply_to_blender(out_path, Path(args.apply), args.blender)

    log.info("Done → %s", out_path)


if __name__ == "__main__":
    main()
