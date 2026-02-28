"""
M2 Gear Optimization Rules
Profile: ASA-GF + 0.4mm nozzle

Purpose: Optimize print parameters for M2 module involute gears.
Key concerns:
  - Tooth geometry fidelity (outer wall speed / flow)
  - Layer bonding under torque (fan management)
  - First-layer adhesion (temperature ramp)
  - Bridge quality (tooth tip overhangs if spiral/bevel gears)

Based on:
  - GcodeTools MoveTypes feature detection
  - CNC Kitchen research on FFF gear printing
  - Empirical testing on Qidi Q2 with Fibreheart ASA-GF

Import convention: other rule files should follow the same interface.
  inject(block, profile, context) -> list[str] of GCode lines to insert BEFORE block
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..refiner import BlockContext

# Move type string constants (QIDIStudio / OrcaSlicer slicer comment format)
# GcodeTools reads these from ;TYPE:... comment lines injected by the slicer.
TYPE_OUTER_WALL    = "OUTER_WALL"
TYPE_INNER_WALL    = "INNER_WALL"
TYPE_SPARSE_INFILL = "SPARSE_INFILL"
TYPE_SOLID_INFILL  = "SOLID_INFILL"
TYPE_BRIDGE        = "BRIDGE"
TYPE_SUPPORT       = "SUPPORT"
TYPE_SKIRT         = "SKIRT_BRIM"
TYPE_PRIME_TOWER   = "PRIME_TOWER"

RULE_ID          = "m2_gear"
RULE_DESCRIPTION = "M2 module gear — tooth geometry + layer bonding optimization"
RULE_VERSION     = "1.0.0"

FAN_MAX = 255  # 0–255 scale; 255 = 100% fan speed


# ---------------------------------------------------------------------------
# Per-feature parameter overrides
# These override the base profile values for this specific use-case.
# ---------------------------------------------------------------------------

OVERRIDES = {
    # ── OUTER WALL (gear tooth surfaces) ──────────────────────────────────
    # Most critical: these lines define the tooth geometry.
    # Slow down so the motion system tracks the involute profile accurately.
    # Fan=0 maximizes layer-to-layer fusion (ASA torque resistance).
    # Temp +5°C over nominal for better melt fusion on thin tooth walls.
    TYPE_OUTER_WALL: {
        "speed_mm_s":  20,    # mm/s — slow outer walls
        "nozzle_temp":  275,  # °C — slightly hotter for better fusion
        "fan":          0,    # off — maximize layer bonding
        "flow_ratio": 1.02,   # slight over-extrude fills micro-voids
        "accel":      1000,   # mm/s² — lower accel = better path following
        "comment":    "M2 outer wall: slow + hot + no fan",
    },

    # ── INNER WALLS ────────────────────────────────────────────────────────
    # Less critical than outer — can run faster.
    # Still no fan (we're inside ASA — warping is a risk).
    TYPE_INNER_WALL: {
        "speed_mm_s":  40,
        "nozzle_temp":  270,
        "fan":          0,
        "flow_ratio": 1.00,
        "accel":      2000,
        "comment":    "M2 inner wall: moderate speed, no fan",
    },

    # ── SOLID INFILL (top/bottom faces) ────────────────────────────────────
    # Hub face and gear face. Light cooling improves flatness.
    TYPE_SOLID_INFILL: {
        "speed_mm_s":  30,
        "nozzle_temp":  270,
        "fan":          50,   # ~20% — light cooling for flat surfaces
        "flow_ratio": 1.00,
        "accel":      3000,
        "comment":    "M2 solid infill: moderate, light fan",
    },

    # ── SPARSE INFILL ──────────────────────────────────────────────────────
    # Interior — speed up here to reclaim time lost on slow outer walls.
    # For gear hubs that should be solid, set infill=100% in slicer instead.
    TYPE_SPARSE_INFILL: {
        "speed_mm_s":  80,
        "nozzle_temp":  265,
        "fan":          80,   # 31% — ok for interior
        "flow_ratio": 0.98,
        "accel":      5000,
        "comment":    "M2 sparse infill: fast",
    },

    # ── BRIDGES ────────────────────────────────────────────────────────────
    # Can occur at tooth tips in spiral bevel gears, and at hub bores.
    # Under-extrude + max fan for bridge quality.
    TYPE_BRIDGE: {
        "speed_mm_s":  20,
        "nozzle_temp":  265,
        "fan":          FAN_MAX,  # 100%
        "flow_ratio": 0.90,
        "accel":      1500,
        "comment":    "M2 bridge: max fan, under-extrude",
    },

    # ── SUPPORT ────────────────────────────────────────────────────────────
    # Helical gears may need support; keep it fast and easy to remove.
    TYPE_SUPPORT: {
        "speed_mm_s":  60,
        "nozzle_temp":  265,
        "fan":          180,  # 71% — cool support for easy removal
        "flow_ratio": 0.95,
        "accel":      4000,
        "comment":    "M2 support: fast, high fan for clean removal",
    },
}


# ---------------------------------------------------------------------------
# First-layer special handling
# Applied regardless of feature type on layer 0 (and optionally layer 1).
# ---------------------------------------------------------------------------

FIRST_LAYER = {
    "speed_mm_s":  10,    # mm/s
    "nozzle_temp":  280,  # °C — maximum adhesion
    "fan":          0,    # off
    "flow_ratio": 1.05,   # over-extrude for max contact area
    "bed_temp":    105,   # °C
    "accel":       500,
    "comment":     "M2 first layer: maximum adhesion",
}

FIRST_LAYER_COUNT = 2   # apply first-layer settings to this many layers from bottom


# ---------------------------------------------------------------------------
# Layer height recommendation
# ---------------------------------------------------------------------------

# M2 gear: tooth pitch = 2mm, addendum = 2mm.
# Recommended layer height: <= module/10 = 0.2mm. Ideal = 0.15mm.
RECOMMENDED_LAYER_HEIGHT_MM = 0.15
MINIMUM_LAYER_HEIGHT_MM     = 0.10


# ---------------------------------------------------------------------------
# Rule engine interface
# ---------------------------------------------------------------------------

def get_override(move_type: str, layer: int, profile: object) -> dict | None:
    """
    Return a dict of parameter overrides for the given move_type and layer.
    Returns None if no override applies (use base profile defaults).

    Args:
        move_type: string from GcodeTools block.meta.get('type'), e.g. "OUTER_WALL"
        layer:     integer layer index (0-based)
        profile:   the loaded profile module (asa_gf_04mm)

    Returns:
        dict with keys: speed_mm_s, nozzle_temp, fan, flow_ratio, accel, comment
        or None if no override
    """
    # First-layer override takes absolute priority
    if layer < FIRST_LAYER_COUNT:
        return FIRST_LAYER

    # Feature-type override
    if move_type in OVERRIDES:
        return OVERRIDES[move_type]

    return None


def describe() -> str:
    return (
        f"Rule: {RULE_ID} v{RULE_VERSION}\n"
        f"  {RULE_DESCRIPTION}\n"
        f"  Recommended layer height: {RECOMMENDED_LAYER_HEIGHT_MM}mm\n"
        f"  Feature overrides: {list(OVERRIDES.keys())}\n"
    )
