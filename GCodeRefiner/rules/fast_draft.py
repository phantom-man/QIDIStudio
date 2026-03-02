"""
Fast Draft / Geometry Verification Use-Case Rules
==================================================

Purpose: Print as fast as mechanically possible.  Applies to fit-check prints,
geometry validation, throw-away prototypes, first-attempt assemblies where you
just need to know if the dimensions and interfaces are correct before committing
to a full-quality print.

Key concerns:
  - Time-to-print is the only metric
  - Quality doesn't matter; function (dimensional check) does
  - Z dimensions must be correct (don't sacrifice layer height)
  - The print just needs to hold together long enough to test

Strategy:
  - All features run at maximum profile speed or above
  - Accel pushed to printer's max (or above nominal for draft)
  - Fan at full everywhere — rapid cooling = faster travel between layers
  - Slight under-extrusion on infill (won't be seen; saves time on retraction recovery)
  - Support at maximum speed — you're removing them anyway

RULE_ID       = "fast_draft"
RULE_VERSION  = "1.0.0"
"""

from __future__ import annotations
from typing import Optional

RULE_ID = "fast_draft"
RULE_DESCRIPTION = (
    "Fast draft / geometry verification — maximum speed, quality secondary"
)
RULE_VERSION = "1.0.0"

TYPE_OUTER_WALL = "OUTER_WALL"
TYPE_INNER_WALL = "INNER_WALL"
TYPE_SPARSE_INFILL = "SPARSE_INFILL"
TYPE_SOLID_INFILL = "SOLID_INFILL"
TYPE_BRIDGE = "BRIDGE"
TYPE_SUPPORT = "SUPPORT"
TYPE_SKIRT = "SKIRT_BRIM"

# Speed multiplier applied on top of profile speeds
# 1.5 = 150% of profile speed
SPEED_MULTIPLIER = 1.5


OVERRIDES = {
    # ── OUTER WALL ─────────────────────────────────────────────────────────
    # Still the most important for dimensional accuracy (fit-checks need OD/ID).
    # Run faster than normal but not as reckless as infill.
    TYPE_OUTER_WALL: {
        "speed_mm_s": None,  # 120% of profile speed (dynamic)
        "fan": 255,  # full fan — rapid cooling = faster travel
        "flow_ratio": 1.00,
        "accel": None,  # dynamic: profile max
        "comment": "fast_draft outer: 120% speed, max fan",
    },
    # ── INNER WALLS ────────────────────────────────────────────────────────
    TYPE_INNER_WALL: {
        "speed_mm_s": None,  # 150% of profile speed
        "fan": 255,
        "flow_ratio": 1.00,
        "comment": "fast_draft inner: 150% speed",
    },
    # ── SOLID INFILL ───────────────────────────────────────────────────────
    TYPE_SOLID_INFILL: {
        "speed_mm_s": None,  # 150% of profile speed
        "fan": 255,
        "flow_ratio": 1.00,
        "comment": "fast_draft solid infill: max speed",
    },
    # ── SPARSE INFILL ──────────────────────────────────────────────────────
    # This is where you save the most time on draft prints.
    # Run as fast as the profile allows and under-extrude slightly.
    TYPE_SPARSE_INFILL: {
        "speed_mm_s": None,  # 200% — push to mechanical limit
        "fan": 255,
        "flow_ratio": 0.95,  # under-extrude infill slightly = faster recovery
        "comment": "fast_draft infill: double speed",
    },
    # ── BRIDGE ─────────────────────────────────────────────────────────────
    # Bridges can sag on draft prints — acceptable.  Still use fan.
    TYPE_BRIDGE: {
        "speed_mm_s": None,  # 120% of profile bridge speed
        "fan": 255,
        "flow_ratio": 0.95,
        "comment": "fast_draft bridge: fast + max fan",
    },
    # ── SUPPORT ────────────────────────────────────────────────────────────
    TYPE_SUPPORT: {
        "speed_mm_s": None,  # 200%
        "fan": 255,
        "flow_ratio": 0.85,  # minimal material — just enough to support
        "comment": "fast_draft support: maximum speed, minimal material",
    },
    # ── SKIRT/BRIM ─────────────────────────────────────────────────────────
    TYPE_SKIRT: {
        "speed_mm_s": None,  # 120% of profile
        "fan": 0,  # don't chill first layer
        "flow_ratio": 1.02,
        "comment": "fast_draft skirt: fast, no fan",
    },
}


def get_override(feature_type: str, layer: int, profile) -> Optional[dict]:
    base = OVERRIDES.get(feature_type)
    if base is None:
        return None

    result = dict(base)

    # Dynamic speed: multiply profile speed
    if result.get("speed_mm_s") is None:
        profile_speed = _profile_speed(feature_type, profile)
        if profile_speed:
            mult = {
                TYPE_OUTER_WALL: 1.20,
                TYPE_INNER_WALL: 1.50,
                TYPE_SOLID_INFILL: 1.50,
                TYPE_SPARSE_INFILL: 2.00,
                TYPE_BRIDGE: 1.20,
                TYPE_SUPPORT: 2.00,
                TYPE_SKIRT: 1.20,
            }.get(feature_type, 1.5)
            # Respect the printer's absolute max from profile
            travel_speed = getattr(profile, "SPEED_TRAVEL", 300)
            result["speed_mm_s"] = min(
                round(profile_speed * mult),
                int(travel_speed * 0.85),  # never exceed 85% of travel speed
            )

    # Dynamic accel: push to profile max
    if result.get("accel") is None:
        # Use the profile's own accel if it exposes one, otherwise use 8000 as draft max
        result["accel"] = getattr(profile, "ACCEL_MAX", 8000)

    # Don't change temp for draft prints — just run at nominal
    result.setdefault("nozzle_temp", getattr(profile, "NOZZLE_TEMP_NOMINAL", None))

    # First N layers: fan off regardless
    if layer <= getattr(profile, "CLOSE_FAN_FIRST_N_LAYERS", 2):
        result["fan"] = 0

    return result


def _profile_speed(feature_type: str, profile) -> Optional[float]:
    attr = {
        TYPE_OUTER_WALL: "SPEED_OUTER_WALL",
        TYPE_INNER_WALL: "SPEED_INNER_WALL",
        TYPE_SOLID_INFILL: "SPEED_SOLID_INFILL",
        TYPE_SPARSE_INFILL: "SPEED_SPARSE_INFILL",
        TYPE_BRIDGE: "SPEED_BRIDGE",
        TYPE_SUPPORT: "SPEED_INNER_WALL",
        TYPE_SKIRT: "SPEED_OUTER_WALL",
    }.get(feature_type)
    return getattr(profile, attr, None) if attr else None


def describe() -> str:
    return (
        f"Rule: {RULE_ID} v{RULE_VERSION}\n"
        f"Description: {RULE_DESCRIPTION}\n"
        "Strategy: outer wall at 120%, inner/infill/support at 150-200% of profile speeds.\n"
        "          Max fan everywhere, accel pushed to profile max (or 8000mm/s²).\n"
        "          Under-extrude infill and support — they're invisible and removable.\n"
        "NOT recommended for production prints — dimensional accuracy will degrade at high speed."
    )
