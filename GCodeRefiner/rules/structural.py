"""
Structural / Load-Bearing Use-Case Rules
=========================================

Purpose: Maximize inter-layer bond strength and wall-to-wall fusion.  Applies to
load-bearing brackets, camera mounts, shelf supports, clips, hinges, cable
management, mechanical assemblies that need to resist tensile/shear forces.

Key concerns:
  - Inter-layer bond is the weakest axis in FFF (always).
  - Cooling is the enemy of bond strength — rapidly cooled layers don't fuse.
  - Temperature consistency matters more than peak temp — avoid dips between features.
  - Flow continuity: no under-extrusion on perimeters — that creates void stress risers.

Strategy:
  - Reduce part cooling on perimeters significantly (or eliminate for ABS/ASA)
  - Raise temp slightly on outer and inner walls
  - Over-extrude inner walls modestly — fills any void between perimeter passes
  - High flow ratio on solid infill — dense top/bottom cap contributes to strength
  - Infill: use at least 40% density (set in slicer); this rule runs normal speed/temp
  - Bridges: necessary fan but minimal — just enough to keep geometry, not shrink layers

RULE_ID       = "structural"
RULE_VERSION  = "1.0.0"
"""

from __future__ import annotations
from typing import Optional

RULE_ID = "structural"
RULE_DESCRIPTION = "Structural / load-bearing — maximum inter-layer bond strength"
RULE_VERSION = "1.0.0"

TYPE_OUTER_WALL = "OUTER_WALL"
TYPE_INNER_WALL = "INNER_WALL"
TYPE_SPARSE_INFILL = "SPARSE_INFILL"
TYPE_SOLID_INFILL = "SOLID_INFILL"
TYPE_BRIDGE = "BRIDGE"
TYPE_SUPPORT = "SUPPORT"
TYPE_SKIRT = "SKIRT_BRIM"

# Fraction of profile fan to use on structural perimeters
# 0.15 = 15% max — just enough to keep surface quality on PLA; zero for ASA/ABS
PERIMETER_FAN_FRACTION = 0.15


OVERRIDES = {
    # ── OUTER WALL ─────────────────────────────────────────────────────────
    # Primary printing surface but also first perimeter to bond to inner walls.
    # Hotter + slower + minimal fan = best possible fusion.
    TYPE_OUTER_WALL: {
        "speed_mm_s": None,  # 70% of profile speed
        "nozzle_temp": None,  # profile nominal + 5°C (dynamic)
        "fan": None,  # 15% of profile fan (dynamic)
        "flow_ratio": 1.02,  # slight over — no voids between perimeters
        "accel": 1200,
        "comment": "structural outer: slower + hot + low fan",
    },
    # ── INNER WALLS ────────────────────────────────────────────────────────
    TYPE_INNER_WALL: {
        "speed_mm_s": None,  # 80% of profile speed
        "nozzle_temp": None,  # profile nominal + 3°C
        "fan": None,  # 15% of profile fan
        "flow_ratio": 1.02,  # over-extrude: fill perimeter micro-voids
        "accel": 1500,
        "comment": "structural inner: warm + slightly over-extrude",
    },
    # ── SOLID INFILL ───────────────────────────────────────────────────────
    # Top and bottom faces: need to lock together perimeter columns.
    # More flow on top face = stronger tensile shear resistance.
    TYPE_SOLID_INFILL: {
        "speed_mm_s": None,  # 75% of profile solid speed
        "nozzle_temp": None,  # nominal temp
        "fan": None,  # 30% of profile fan — enough for flat faces
        "flow_ratio": 1.03,
        "accel": 1000,
        "comment": "structural solid infill: high flow, light fan",
    },
    # ── SPARSE INFILL ──────────────────────────────────────────────────────
    # Speed is fine here — interior infill just needs to exist.
    # Encourage high infill density in slicer (≥40% gyroid/cubic).
    TYPE_SPARSE_INFILL: {
        "speed_mm_s": None,  # full profile speed
        "fan": None,  # 20% of profile fan
        "flow_ratio": 1.01,
        "comment": "structural sparse infill: nominal",
    },
    # ── BRIDGE ─────────────────────────────────────────────────────────────
    # Don't sacrifice bridge quality for the sake of low-fan rule.
    # A sagging bridge in a structural part = reduced cross-section = failure.
    TYPE_BRIDGE: {
        "speed_mm_s": 25,
        "fan": 180,  # 70% — enough to solidify bridge quickly
        "flow_ratio": 0.95,
        "accel": 600,
        "comment": "structural bridge: 70% fan, controlled speed",
    },
    # ── SUPPORT ────────────────────────────────────────────────────────────
    TYPE_SUPPORT: {
        "speed_mm_s": None,  # 120% of profile speed
        "fan": 100,
        "flow_ratio": 0.92,  # light = easy removal
        "comment": "structural support: fast, easy-release",
    },
}


def get_override(feature_type: str, layer: int, profile) -> Optional[dict]:
    base = OVERRIDES.get(feature_type)
    if base is None:
        return None

    result = dict(base)
    nominal = getattr(profile, "NOZZLE_TEMP_NOMINAL", None)
    temp_max = getattr(profile, "NOZZLE_TEMP_MAX", (nominal or 270) + 20)

    # Dynamic speed
    if result.get("speed_mm_s") is None:
        profile_speed = _profile_speed(feature_type, profile)
        if profile_speed:
            mult = {
                TYPE_OUTER_WALL: 0.70,
                TYPE_INNER_WALL: 0.80,
                TYPE_SOLID_INFILL: 0.75,
                TYPE_SPARSE_INFILL: 1.00,
                TYPE_SUPPORT: 1.20,
            }.get(feature_type, 1.0)
            result["speed_mm_s"] = max(15, round(profile_speed * mult))

    # Dynamic temp
    if result.get("nozzle_temp") is None and nominal:
        offset = {
            TYPE_OUTER_WALL: 5,
            TYPE_INNER_WALL: 3,
            TYPE_SOLID_INFILL: 0,
            TYPE_SPARSE_INFILL: 0,
        }.get(feature_type, 0)
        result["nozzle_temp"] = min(temp_max, nominal + offset)

    # Dynamic fan (structural = minimize cooling on perimeters)
    if result.get("fan") is None:
        profile_fan = _profile_fan(feature_type, profile)
        if profile_fan is not None:
            fraction = {
                TYPE_OUTER_WALL: PERIMETER_FAN_FRACTION,
                TYPE_INNER_WALL: PERIMETER_FAN_FRACTION,
                TYPE_SOLID_INFILL: 0.30,
                TYPE_SPARSE_INFILL: 0.20,
            }.get(feature_type, 0.20)
            result["fan"] = max(0, round(profile_fan * fraction))

    # Always keep fan off for first N layers regardless of override
    if layer <= getattr(profile, "CLOSE_FAN_FIRST_N_LAYERS", 3):
        result["fan"] = 0

    return result


def _profile_speed(feature_type: str, profile) -> Optional[float]:
    attr = {
        TYPE_OUTER_WALL: "SPEED_OUTER_WALL",
        TYPE_INNER_WALL: "SPEED_INNER_WALL",
        TYPE_SOLID_INFILL: "SPEED_SOLID_INFILL",
        TYPE_SPARSE_INFILL: "SPEED_SPARSE_INFILL",
        TYPE_SUPPORT: "SPEED_INNER_WALL",
    }.get(feature_type)
    return getattr(profile, attr, None) if attr else None


def _profile_fan(feature_type: str, profile) -> Optional[int]:
    attr = {
        TYPE_OUTER_WALL: "FAN_OUTER_WALL",
        TYPE_INNER_WALL: "FAN_INNER_WALL",
        TYPE_SOLID_INFILL: "FAN_SOLID_INFILL",
        TYPE_SPARSE_INFILL: "FAN_SPARSE_INFILL",
    }.get(feature_type)
    return getattr(profile, attr, None) if attr else None


def describe() -> str:
    return (
        f"Rule: {RULE_ID} v{RULE_VERSION}\n"
        f"Description: {RULE_DESCRIPTION}\n"
        "Strategy: outer wall at 70% speed, +5°C, fan ≤15% on perimeters.\n"
        "          over-extrude walls 1-3%, full bridge fan to prevent sagging cross-section.\n"
        "Recommended: ≥4 perimeters, ≥40% infill, rectilinear/gyroid pattern."
    )
