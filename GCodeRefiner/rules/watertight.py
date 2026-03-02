"""
Watertight / Fluid-Tight Container Use-Case Rules
==================================================

Purpose: Maximize perimeter fusion to eliminate any micro-gaps that would
allow water or air to penetrate.  Applies to tanks, enclosures, waterproof
housings, soap dishes, planters, liquid vessels, pressure-test parts.

Key concerns:
  - Perimeter-to-perimeter bonding (outer wall must press hard into inner wall)
  - Top/bottom surface must be truly solid (no pinhole voids)
  - Seam placement: always on inner/hidden face — seam = weakest point
  - Bridge quality: vessel bottoms must cure flat, not sag

Strategy:
  - Slight over-extrusion (+2-3%) on every perimeter pass
  - Slower outer walls to eliminate gaps between adjacent passes
  - Higher temp on perimeters for better melt fusion
  - 100% fan on bridges to prevent sagging (vessel floor)
  - Infill speed left mostly unconstrained (interior, not load-bearing here)

Import convention: must expose get_override(feature_type, layer, profile) -> dict | None

RULE_ID       = "watertight"
RULE_VERSION  = "1.0.0"
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..refiner import BlockContext

RULE_ID = "watertight"
RULE_DESCRIPTION = "Watertight / fluid-tight vessel — perimeter fusion, no micro-gaps"
RULE_VERSION = "1.0.0"

# Move type constants (canonical — normalized by refiner)
TYPE_OUTER_WALL = "OUTER_WALL"
TYPE_INNER_WALL = "INNER_WALL"
TYPE_SPARSE_INFILL = "SPARSE_INFILL"
TYPE_SOLID_INFILL = "SOLID_INFILL"
TYPE_BRIDGE = "BRIDGE"
TYPE_SUPPORT = "SUPPORT"
TYPE_SKIRT = "SKIRT_BRIM"


# ---------------------------------------------------------------------------
# Per-feature overrides
# Any key absent from a dict falls through to profile default.
# ---------------------------------------------------------------------------

OVERRIDES = {
    # ── OUTER WALL ─────────────────────────────────────────────────────────
    # This is the critical pass.  Slow it right down and push a little extra
    # material — gives the bead time and volume to fully bond to adjacent walls.
    TYPE_OUTER_WALL: {
        "speed_mm_s": None,  # set dynamically below (50% of profile speed)
        "nozzle_temp": None,  # set dynamically: profile nominal + 3°C
        "fan": None,  # set dynamically: keep profile fan but reduce 30%
        "flow_ratio": 1.03,  # +3% — fills micro-gaps between passes
        "accel": 800,  # low accel = steady, wobble-free outer wall
        "comment": "watertight outer wall: slow + slight over-extrude + warm",
    },
    # ── INNER WALLS ────────────────────────────────────────────────────────
    # Perimeter count must be high (set in slicer; this just manages flow).
    # Inner walls fuse to outer — over-extrude them too.
    TYPE_INNER_WALL: {
        "speed_mm_s": None,  # 70% of profile speed
        "nozzle_temp": None,  # profile nominal + 2°C
        "flow_ratio": 1.02,  # +2%
        "accel": 1500,
        "comment": "watertight inner wall: moderate slow + over-extrude",
    },
    # ── SOLID INFILL (top/bottom) ──────────────────────────────────────────
    # The vessel floor and top cap must be truly solid.  Slow and over-extrude.
    TYPE_SOLID_INFILL: {
        "speed_mm_s": None,  # 60% of profile speed
        "flow_ratio": 1.02,
        "accel": 1200,
        "comment": "watertight solid infill: slow + dense",
    },
    # ── SPARSE INFILL ──────────────────────────────────────────────────────
    # Interior infill is sealed inside — speed is fine, but don't let fan
    # change dramatically between infill and walls.
    TYPE_SPARSE_INFILL: {
        "speed_mm_s": None,  # use profile speed
        "flow_ratio": 1.00,
        "comment": "watertight sparse infill: nominal",
    },
    # ── BRIDGE ─────────────────────────────────────────────────────────────
    # Vessel bottom is often a bridge at print start.  Max cooling + slow = flat.
    TYPE_BRIDGE: {
        "speed_mm_s": 20,
        "fan": 255,  # 100% — essential for bridge flatness
        "flow_ratio": 0.95,  # slight under-extrude to prevent droop
        "accel": 500,
        "comment": "watertight bridge: max fan + slow + under-extrude",
    },
    # ── SUPPORT ────────────────────────────────────────────────────────────
    # Supports are removed — speed them up.
    TYPE_SUPPORT: {
        "speed_mm_s": None,  # fast (profile handles)
        "flow_ratio": 0.95,  # slight under-extrude = easier removal
        "comment": "watertight support: easy-remove under-extrude",
    },
}


# ---------------------------------------------------------------------------
# get_override — public interface called by refiner.py
# ---------------------------------------------------------------------------


def get_override(feature_type: str, layer: int, profile) -> Optional[dict]:
    """
    Return parameter overrides for the given feature type, or None if this
    rule set has no opinion about it (fall through to profile defaults).

    Dynamic speed/temp values are computed relative to the profile to remain
    printer-agnostic.
    """
    base = OVERRIDES.get(feature_type)
    if base is None:
        return None

    result = dict(base)  # shallow copy so we don't mutate the OVERRIDES table

    # ── Dynamic speed: fraction of profile's baseline for this feature ─────
    if result.get("speed_mm_s") is None:
        profile_speed = _profile_speed(feature_type, profile)
        if profile_speed:
            multiplier = {
                TYPE_OUTER_WALL: 0.50,
                TYPE_INNER_WALL: 0.70,
                TYPE_SOLID_INFILL: 0.60,
                TYPE_SPARSE_INFILL: 1.00,
                TYPE_BRIDGE: None,  # hard-coded above
                TYPE_SUPPORT: 1.20,  # faster than nominal
            }.get(feature_type, 1.0)
            if multiplier:
                result["speed_mm_s"] = max(10, round(profile_speed * multiplier))

    # ── Dynamic temp: offset from profile nominal ───────────────────────────
    if result.get("nozzle_temp") is None:
        nominal = getattr(profile, "NOZZLE_TEMP_NOMINAL", None)
        if nominal:
            offset = {
                TYPE_OUTER_WALL: 3,
                TYPE_INNER_WALL: 2,
            }.get(feature_type, 0)
            result["nozzle_temp"] = min(
                getattr(profile, "NOZZLE_TEMP_MAX", nominal + 20),
                nominal + offset,
            )

    # ── Dynamic fan: fraction of profile's fan for walls ───────────────────
    if result.get("fan") is None:
        profile_fan = _profile_fan(feature_type, profile)
        if profile_fan is not None:
            result["fan"] = max(0, round(profile_fan * 0.70))

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile_speed(feature_type: str, profile) -> Optional[float]:
    """Read the base speed for a feature type from the profile module."""
    attr = {
        TYPE_OUTER_WALL: "SPEED_OUTER_WALL",
        TYPE_INNER_WALL: "SPEED_INNER_WALL",
        TYPE_SOLID_INFILL: "SPEED_SOLID_INFILL",
        TYPE_SPARSE_INFILL: "SPEED_SPARSE_INFILL",
        TYPE_BRIDGE: "SPEED_BRIDGE",
        TYPE_SUPPORT: "SPEED_INNER_WALL",
    }.get(feature_type)
    return getattr(profile, attr, None) if attr else None


def _profile_fan(feature_type: str, profile) -> Optional[int]:
    """Read the base fan setting for a feature type from the profile module."""
    attr = {
        TYPE_OUTER_WALL: "FAN_OUTER_WALL",
        TYPE_INNER_WALL: "FAN_INNER_WALL",
        TYPE_SOLID_INFILL: "FAN_SOLID_INFILL",
    }.get(feature_type)
    return getattr(profile, attr, None) if attr else None


def describe() -> str:
    return (
        f"Rule: {RULE_ID} v{RULE_VERSION}\n"
        f"Description: {RULE_DESCRIPTION}\n"
        "Strategy: over-extrude perimeters, slow outer wall to 50% of profile,\n"
        "          +3°C on outer wall, 100% fan on bridges, slight under-extrude on support.\n"
        "Recommended wall count: ≥4 perimeters, 5+ top/bottom solid layers."
    )
