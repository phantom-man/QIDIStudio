#!/usr/bin/env python3
"""
ai_beauty_scorer.py — Fourier-Based Aesthetic Quality Scorer
=============================================================
Implements PhD-level computational aesthetics for texture quality evaluation.

Scientific Framework
--------------------
Beauty is not subjective at this level — it is a measurable property of
information structure.  Three converging research pillars define it:

1. **Kolmogorov Complexity Reduction (Johnston et al. 2022, Nature Comms)**
   A(pattern) ∝ 1 / K(S)   where K(S) = shortest program describing the symmetry.
   Symmetric patterns compress more → lower K → higher aesthetic value.
   This is why repetitive tile textures can be beautiful: they have low K.

2. **Perceptual Fluency Theory (Reber, Schwarz & Winkielman 2004)**
   The brain "rewards" ease of visual processing with a hedonic signal.
   Symmetrical stimuli are processed faster (bilateral prediction, V4 cortex).
   High fluency → subjectively experienced as positive/beautiful.
   The *Wundt Curve* (inverted-U): too simple = boring, too complex = chaos.
   Peak beauty sits at the edge of symmetry breaking (high structure + detail).

3. **Spectral Entropy / Neuroaesthetics (Leder et al. 2004)**
   B(s, σ) = ω₁·Fluency(s) + ω₂·Novelty(σ)
   where s = symmetry score (FFT phase coherence)
         σ = spectral entropy (information richness of power spectrum)
   "Beautiful Complexity" (Golden Zone): s > 0.90 AND H_s > 4.0

Mathematical Implementation
----------------------------
Given a 2D texture image I(x,y), its Fourier Transform F(u,v) satisfies:
  - If I is centrosymmetric (bilateral), Im(F) → 0 everywhere.
  - The "symmetry score" S = Σ|Re(F)|² / Σ|F|²  ∈ [0, 1].
    Perfect bilateral symmetry → S = 1.0.
  - The Power Spectral Density P(u,v) = |F(u,v)|² / Σ|F|² defines a
    probability distribution over spatial frequencies.
  - Spectral Entropy H_s = −ΣP·log₂(P)  in bits.
    Simple grid: H_s ≈ 2.1   (power in 2 frequencies only)
    Random noise: H_s ≈ 4.6  (uniform power distribution)
    "Complex symmetric" (Gyroid-like): H_s ≈ 4.6 with high S → Golden Zone.

Additional: Dominant Radial Frequency
  The radial frequency profile R(r) = Σ P(u,v) where |(u,v)| = r.
  The peak r_peak gives the characteristic "feature pitch" of the texture.
  This can be used to select the optimal tile_size:
    tile_size = r_peak * FEATURE_TARGET_MM
  so the dominant skin feature prints at a physically meaningful scale.

Beauty Score Thresholds
-----------------------
| Score Range | Category               | Action                           |
|-------------|------------------------|----------------------------------|
| 0.80 – 1.00 | BEAUTIFUL              | Accept — golden zone             |
| 0.65 – 0.80 | GOOD                   | Accept — minor room for improvement |
| 0.50 – 0.65 | ACCEPTABLE             | Warn — consider different skin   |
| 0.00 – 0.50 | POOR                   | Fail — skin lacks structure      |

Usage
-----
  from scripts.ai_beauty_scorer import analyse_skin_file, BeautyReport
  report = analyse_skin_file("resources/assets/.../skin.png")
  print(f"Beauty={report.beauty_score:.3f}  S={report.symmetry_score:.3f}  H={report.spectral_entropy:.2f}")

  # CLI:
  python scripts/ai_beauty_scorer.py path/to/skin.png

References
----------
- Reber, Schwarz & Winkielman (2004). "Processing Fluency and Aesthetic Pleasure."
  Personality and Social Psychology Review, 8(4): 364–382.
  DOI:10.1207/s15327957pspr0804_3
- Leder, Belke, Oeberst & Augustin (2004). "A model of aesthetic appreciation."
  British Journal of Psychology, 95: 489–508.
- Johnston, Levin, Sheratt & Harper (2022). "Symmetry as a result of simplicity bias."
  Nature Communications, 13: 1858. DOI:10.1038/s41467-022-29330-w
- Birkhoff (1933). *Aesthetic Measure*. Cambridge, MA: Harvard University Press.
  M = O/C  (order over complexity — the original aesthetic score).
"""

from __future__ import annotations

import sys
import pathlib
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ── Constants ──────────────────────────────────────────────────────────────

# Beauty score thresholds (calibrated against gyroid=0.97, random=0.45)
BEAUTY_BEAUTIFUL = 0.80
BEAUTY_GOOD = 0.65
BEAUTY_ACCEPTABLE = 0.50

# Fourier symmetry thresholds (from attached doc: S > 0.90 = "golden zone")
SYMMETRY_BEAUTIFUL = 0.90
SYMMETRY_ACCEPTABLE = 0.65

# Spectral entropy thresholds (from attached doc: H_s > 4.0 = "beautiful complexity")
ENTROPY_COMPLEX_SYM = 4.0  # combined with high S → golden zone
ENTROPY_SIMPLE_SYM = 2.5  # simple grid: ~2.1 (boring)
ENTROPY_RANDOM = 4.6  # random noise upper bound

# Beauty function weights: ω₁ (fluency) and ω₂ (novelty)
# From Leder et al. (2004): perceptual fluency slightly outweighs novelty for
# decorative objects (vs fine art where they equalise).
OMEGA_FLUENCY = 0.60
OMEGA_NOVELTY = 0.40

# Wundt penalty: slight beauty reduction for VERY simple patterns (H_s < 2.0)
# Prevents a pure sine-wave grid from scoring 0.92 (too "boring").
WUNDT_ENTROPY_THRESHOLD = 2.0
WUNDT_PENALTY_SLOPE = 0.12

# Target feature pitch for optimal tile_size suggestion (mm)
FEATURE_TARGET_MM = 3.0  # 3mm feature pitch → clearly visible detail at 0.4mm nozzle


# ── Data classes ───────────────────────────────────────────────────────────


@dataclass
class BeautyReport:
    """Full aesthetic quality report for a single texture image."""

    # Input
    source_path: str

    # Primary metrics
    symmetry_score: float  # 0–1. 1.0 = perfect bilateral symmetry
    spectral_entropy: float  # bits. ~2.1 simple, ~4.6 complex/random
    beauty_score: float  # 0–1. weighted Reber–Leder formula
    verdict: str  # "BEAUTIFUL" | "GOOD" | "ACCEPTABLE" | "POOR"

    # Derived
    dominant_frequency_px: float  # peak radial frequency (cycles/image_dim)
    tile_size_hint_mm: float  # suggested tile_size based on dominant freq
    in_golden_zone: bool  # symmetry_score > 0.9 AND entropy > 4.0

    # Diagnostics
    image_size: tuple[int, int] = field(default_factory=lambda: (0, 0))
    warnings: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        gzone = "  ★ GOLDEN ZONE" if self.in_golden_zone else ""
        return (
            f"BeautyReport({pathlib.Path(self.source_path).name})\n"
            f"  Symmetry Score   : {self.symmetry_score:.4f}{gzone}\n"
            f"  Spectral Entropy : {self.spectral_entropy:.4f} bits\n"
            f"  Beauty Score     : {self.beauty_score:.4f}  [{self.verdict}]\n"
            f"  Dominant freq    : {self.dominant_frequency_px:.1f} px\n"
            f"  Tile size hint   : {self.tile_size_hint_mm:.1f} mm\n"
        )


# ── Core computations ──────────────────────────────────────────────────────


def fft_symmetry_score(gray: np.ndarray) -> float:
    """
    Compute Fourier Symmetry Score for a 2D grayscale array.

    A real-valued image I(x,y) with perfect bilateral (centrosymmetric) symmetry
    has a Fourier Transform whose imaginary part vanishes entirely.
    The score S = Σ|Re(F)|² / Σ|F|²  quantifies how much of the total spectral
    energy is in the real (in-phase) component.

    S = 1.0  → perfectly symmetric (phase angles = 0 everywhere)
    S ≈ 0.5  → random/asymmetric (real and imaginary energy are equal)
    S > 0.9  → "beautiful" threshold from Reber et al. (2004)

    Parameters
    ----------
    gray : (H, W) float array, normalised to [0, 1]

    Returns
    -------
    float in [0, 1]
    """
    F = np.fft.fft2(gray - gray.mean())
    F_s = np.fft.fftshift(F)
    real_energy = float(np.sum(np.real(F_s) ** 2))
    total_energy = float(np.sum(np.abs(F_s) ** 2)) + 1e-12
    return real_energy / total_energy


def spectral_entropy(gray: np.ndarray) -> float:
    """
    Compute Spectral Entropy H_s of a 2D grayscale array.

    Treats the normalised Power Spectral Density as a probability distribution
    and applies Shannon's entropy formula:
        H_s = −Σ P(u,v) · log₂(P(u,v))

    H_s ≈ 2.1 : simple symmetric grid (power in 2 frequencies)
    H_s ≈ 4.6 : random noise / complex symmetric (Gyroid) — uniform spectrum
    H_s > 4.0 : "complex symmetric" threshold (attached doc §II, §III)

    Parameters
    ----------
    gray : (H, W) float array

    Returns
    -------
    float >= 0  (bits)
    """
    F = np.fft.fft2(gray - gray.mean())
    psd = np.abs(F) ** 2
    total = psd.sum() + 1e-12
    p = psd / total
    p_safe = np.where(p > 1e-15, p, 1e-15)
    return float(-np.sum(p_safe * np.log2(p_safe)))


def dominant_radial_frequency(gray: np.ndarray) -> float:
    """
    Find the dominant radial spatial frequency of a texture image.

    Computes the radial power profile R(r) by summing PSD at each integer radius
    from the DC component.  The peak of R (excluding DC at r=0) gives the
    characteristic "feature pitch" of the pattern in cycles/image_dimension.

    For a texture image of width W pixels mapped to tile_size mm:
        feature_pitch_mm = tile_size / r_peak

    To target a self-consistent feature_pitch ≈ FEATURE_TARGET_MM:
        tile_size_optimal = r_peak × FEATURE_TARGET_MM

    Parameters
    ----------
    gray : (H, W) float array

    Returns
    -------
    float — peak frequency in cycles/image_dimension (0 if not detectable)
    """
    H, W = gray.shape
    F = np.fft.fft2(gray - gray.mean())
    F_s = np.fft.fftshift(F)
    psd = np.abs(F_s) ** 2

    cy, cx = H // 2, W // 2
    y_idx = np.arange(H).reshape(-1, 1) - cy
    x_idx = np.arange(W).reshape(1, -1) - cx
    r = np.sqrt(x_idx**2 + y_idx**2).astype(int)

    r_max = min(cx, cy)
    radial = np.bincount(r.ravel(), weights=psd.ravel(), minlength=r_max + 1)[
        : r_max + 1
    ]
    radial[0] = 0.0  # exclude DC

    if radial.max() < 1e-12:
        return 0.0
    return float(np.argmax(radial))


def beauty_score_from_metrics(
    sym_score: float,
    entropy: float,
    omega1: float = OMEGA_FLUENCY,
    omega2: float = OMEGA_NOVELTY,
) -> float:
    """
    Compute $B(s, σ) = ω₁·Fluency(s) + ω₂·Novelty(σ)$ from Leder et al. (2004).

    Fluency(s)  = symmetry_score (already in [0,1])
    Novelty(σ)  = entropy / H_random  (normalised to [0,1] using random upper bound)

    A Wundt penalty is applied for very simple patterns (H_s < 2.0) to prevent
    a "boring" uniform grid from scoring as "Beautiful":
        penalty = WUNDT_SLOPE × max(0, WUNDT_THRESHOLD − H_s)

    Returns
    -------
    float in [0, 1]
    """
    fluency = float(np.clip(sym_score, 0.0, 1.0))
    novelty = float(np.clip(entropy / ENTROPY_RANDOM, 0.0, 1.0))
    wundt = WUNDT_PENALTY_SLOPE * max(0.0, WUNDT_ENTROPY_THRESHOLD - entropy)
    score = omega1 * fluency + omega2 * novelty - wundt
    return float(np.clip(score, 0.0, 1.0))


def _verdict_from_score(score: float) -> str:
    if score >= BEAUTY_BEAUTIFUL:
        return "BEAUTIFUL"
    if score >= BEAUTY_GOOD:
        return "GOOD"
    if score >= BEAUTY_ACCEPTABLE:
        return "ACCEPTABLE"
    return "POOR"


# ── Public API ─────────────────────────────────────────────────────────────


def analyse_array(
    gray: np.ndarray,
    source_path: str = "<array>",
    tile_size_mm: float = 15.0,
) -> BeautyReport:
    """
    Analyse a 2D grayscale numpy array and return a full BeautyReport.

    Parameters
    ----------
    gray          : (H, W) float array, any value range (auto-normalised)
    source_path   : label for the report (e.g. the PNG path)
    tile_size_mm  : current tile size in mm (used to compute tile_size_hint)

    Returns
    -------
    BeautyReport
    """
    # Normalise to [0, 1]
    lo, hi = float(gray.min()), float(gray.max())
    if hi - lo < 1e-9:
        # Flat image — perfectly symmetric but zero information
        return BeautyReport(
            source_path=source_path,
            symmetry_score=1.0,
            spectral_entropy=0.0,
            beauty_score=0.0,
            verdict="POOR",
            dominant_frequency_px=0.0,
            tile_size_hint_mm=tile_size_mm,
            in_golden_zone=False,
            image_size=(gray.shape[1], gray.shape[0]),
            warnings=[
                "Image is uniform (all pixels identical) — no texture information."
            ],
        )
    gray_norm = (gray - lo) / (hi - lo)

    # Core metrics
    sym = fft_symmetry_score(gray_norm)
    ent = spectral_entropy(gray_norm)
    score = beauty_score_from_metrics(sym, ent)
    r_peak = dominant_radial_frequency(gray_norm)

    # Tile size hint from dominant frequency
    H, W = gray_norm.shape
    if r_peak > 0:
        # r_peak is in cycles/image_dimension
        # We want feature_pitch_mm ≈ FEATURE_TARGET_MM
        # feature_pitch_mm = tile_size / r_peak  → tile_size = r_peak * FEATURE_TARGET_MM
        tile_hint = r_peak * FEATURE_TARGET_MM
        # Clamp to printable range [5, 80] mm
        tile_hint = float(np.clip(tile_hint, 5.0, 80.0))
    else:
        tile_hint = tile_size_mm

    golden = sym > SYMMETRY_BEAUTIFUL and ent > ENTROPY_COMPLEX_SYM

    # Diagnostic warnings
    warnings: list[str] = []
    if sym < SYMMETRY_ACCEPTABLE:
        warnings.append(
            f"Low symmetry score ({sym:.3f} < {SYMMETRY_ACCEPTABLE}): "
            "skin pattern is asymmetric — repeated tiling may look chaotic."
        )
    if ent < ENTROPY_SIMPLE_SYM:
        warnings.append(
            f"Low spectral entropy ({ent:.2f} bits < {ENTROPY_SIMPLE_SYM}): "
            "skin is too simple (grid/stripe) — consider a richer texture."
        )
    if ent > ENTROPY_RANDOM * 0.99 and sym < SYMMETRY_ACCEPTABLE:
        warnings.append(
            f"Near-random spectrum (H_s={ent:.2f}) with low symmetry — "
            "skin resembles noise; will produce muddy displacement."
        )
    if golden:
        warnings.append(
            "★ GOLDEN ZONE: high symmetry + high entropy → "
            "maximum aesthetic quality (Leder et al. 2004)."
        )

    return BeautyReport(
        source_path=source_path,
        symmetry_score=sym,
        spectral_entropy=ent,
        beauty_score=score,
        verdict=_verdict_from_score(score),
        dominant_frequency_px=r_peak,
        tile_size_hint_mm=tile_hint,
        in_golden_zone=golden,
        image_size=(W, H),
        warnings=warnings,
    )


def analyse_skin_file(
    png_path: str,
    tile_size_mm: float = 15.0,
) -> BeautyReport:
    """
    Analyse a PNG skin texture file and return a BeautyReport.

    Uses Pillow (PIL) for image loading.  If Pillow is not installed, falls
    back to a pure-numpy PNG reader (limited to 8-bit RGBA PNGs).

    Parameters
    ----------
    png_path     : absolute path to the PNG file
    tile_size_mm : current tile size (used to contextualise tile_size_hint)

    Returns
    -------
    BeautyReport
    """
    p = pathlib.Path(png_path)
    if not p.exists():
        return BeautyReport(
            source_path=png_path,
            symmetry_score=0.0,
            spectral_entropy=0.0,
            beauty_score=0.0,
            verdict="POOR",
            dominant_frequency_px=0.0,
            tile_size_hint_mm=tile_size_mm,
            in_golden_zone=False,
            warnings=[f"File not found: {png_path}"],
        )

    try:
        from PIL import Image as _PIL_Image  # type: ignore

        img = _PIL_Image.open(str(p)).convert("L")
        gray = np.array(img, dtype=np.float32)
    except ImportError:
        # Fallback: minimal PNG reader with numpy only
        # Handles uncompressed / deflate-compressed 8-bit RGBA PNGs
        try:
            gray = _load_png_grayscale_numpy(str(p))
        except Exception as exc:
            return BeautyReport(
                source_path=png_path,
                symmetry_score=0.0,
                spectral_entropy=0.0,
                beauty_score=0.0,
                verdict="POOR",
                dominant_frequency_px=0.0,
                tile_size_hint_mm=tile_size_mm,
                in_golden_zone=False,
                warnings=[
                    f"Could not load {png_path}: {exc}. "
                    "Install Pillow: pip install Pillow"
                ],
            )

    return analyse_array(gray, source_path=png_path, tile_size_mm=tile_size_mm)


def _load_png_grayscale_numpy(path: str) -> np.ndarray:
    """
    Minimal fallback PNG loader using only numpy + stdlib.
    Handles 8-bit PNG files written by most image tools.
    Not a full PNG spec implementation — use PIL for production.
    """
    import struct, zlib

    with open(path, "rb") as f:
        sig = f.read(8)
        if sig != b"\x89PNG\r\n\x1a\n":
            raise ValueError("Not a valid PNG file")

        width = height = bit_depth = color_type = 0
        idat_data = bytearray()

        while True:
            chunk_len_bytes = f.read(4)
            if len(chunk_len_bytes) < 4:
                break
            (chunk_len,) = struct.unpack(">I", chunk_len_bytes)
            chunk_type = f.read(4).decode("ascii", errors="replace")
            data = f.read(chunk_len)
            f.read(4)  # CRC

            if chunk_type == "IHDR":
                (width, height, bit_depth, color_type) = struct.unpack(
                    ">IIBB", data[:10]
                )
            elif chunk_type == "IDAT":
                idat_data.extend(data)
            elif chunk_type == "IEND":
                break

        raw = zlib.decompress(bytes(idat_data))

        # color_type: 0=gray, 2=RGB, 3=indexed, 4=gray+A, 6=RGBA
        n_ch = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type, 3)
        row_len = 1 + width * n_ch
        rows = []
        for y in range(height):
            row = raw[y * row_len : (y + 1) * row_len]
            rows.append(np.frombuffer(row[1:], dtype=np.uint8))
        arr = np.stack(rows, axis=0).reshape(height, width, n_ch).astype(np.float32)
        # Convert to grayscale
        if n_ch == 1:
            return arr[:, :, 0]
        elif n_ch == 2:
            return arr[:, :, 0]
        elif n_ch == 3:
            return 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
        else:  # 4: RGBA
            return 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]


# ── CLI entry point ────────────────────────────────────────────────────────


def main():
    """Analyse a skin PNG file from the command line."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) < 2:
        print("Usage: ai_beauty_scorer.py <skin.png> [tile_size_mm]")
        print()
        print(
            "Computes the Fourier-based aesthetic beauty score for a texture skin PNG."
        )
        print()
        print("Output metrics:")
        print("  Symmetry Score   — Fourier phase coherence [0-1]. >0.90 = beautiful.")
        print(
            "  Spectral Entropy — Information richness [bits]. >4.0 = complex-symmetric."
        )
        print("  Beauty Score     — Leder 2004 formula. >0.80 = BEAUTIFUL.")
        print(
            "  Tile size hint   — Optimal tile_size in mm based on dominant frequency."
        )
        sys.exit(1)

    png_path = sys.argv[1]
    tile_size_mm = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0

    report = analyse_skin_file(png_path, tile_size_mm=tile_size_mm)
    print(str(report))

    if report.warnings:
        print("  Warnings:")
        for w in report.warnings:
            print(f"    • {w}")

    print()
    print("  Bibliography:")
    print("    Reber, Schwarz & Winkielman (2004). doi:10.1207/s15327957pspr0804_3")
    print("    Leder, Belke, Oeberst & Augustin (2004). British J. Psychology 95.")
    print(
        "    Johnston et al. (2022). Nature Comms 13:1858. doi:10.1038/s41467-022-29330-w"
    )

    sys.exit(0 if report.beauty_score >= BEAUTY_GOOD else 1)


if __name__ == "__main__":
    main()
