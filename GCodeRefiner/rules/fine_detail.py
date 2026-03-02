"""
Fine Detail / Miniature Use-Case Rules
=======================================

Purpose: Maximize surface resolution and dimensional accuracy.  Applies to
miniatures, figurines, jewelry masters, embossed/debossed text, tabletop game
terrain, coin-sized mechanical parts, watch bezels, anything where visual
fidelity or sub-0.1mm dimensional accuracy matters more than print time.

Key concerns:
  - Outer wall tracks the toolpath as precisely as possible
  - Motion system must not overshoot at feature transitions
  - Cooling must be aggressive — small cross-sections can sag instantly
  - Retraction must be dialled in to near-zero ooze on fine features
  - Overhangs and bridges are common (undercut detail) — need max fan

Strategy:
  - Outer wall: slowest possible speed (25–30% of profile), max fan, lowest accel
  - Inner walls: significantly slowed but not as much as outer
  - Solid infill: also slow — top surface IS the visible face on miniatures
  - Sparse infill: fast — interior is invisible, spend the time on surface
  - Bridge: max fan, very slow, slight under-extrude stop sagging detail
  - Skirt: nominal (just adhesion)

RULE_ID       = "fine_detail"
RULE_VERSION  = "1.0.0"
"""

from __future__ import annotations
from typing import Optional

RULE_ID = "fine_detail"
RULE_DESCRIPTION = (
    "Fine detail / miniatures — maximum surface resolution, aggressive cooling"
)
RULE_VERSION = "1.0.0"

TYPE_OUTER_WALL = "OUTER_WALL"
TYPE_INNER_WALL = "INNER_WALL"
TYPE_SPARSE_INFILL = "SPARSE_INFILL"
TYPE_SOLID_INFILL = "SOLID_INFILL"
TYPE_BRIDGE = "BRIDGE"
TYPE_SUPPORT = "SUPPORT"
TYPE_SKIRT = "SKIRT_BRIM"


OVERRIDES = {
    # ── OUTER WALL ─────────────────────────────────────────────────────────
    # Slowest permissible speed.  The motion system needs to accurately track
    # involute, curved, and diagonal moves at this resolution.
    # Max fan prevents blobbing and flash on fine features.
    # Low accel means the head doesn't overshoot at feature corners.
    TYPE_OUTER_WALL: {
        "speed_mm_s": None,  # dynamic: 25% of profile outer wall speed
        "fan": 255,  # 100%
        "flow_ratio": 0.99,  # tiny under — prevents blobbing on thin walls
        "accel": 400,  # very low — precision cornering
        "comment": "fine_detail outer: 25% speed, max fan, low accel",
    },
    # ── INNER WALLS ────────────────────────────────────────────────────────
    # Not directly visible but need to be dimensionally correct to support
    # outer wall geometry.  Less critical so faster, still controlled.
    TYPE_INNER_WALL: {
        "speed_mm_s": None,  # 50% of profile speed
        "fan": 200,  # 78%
        "flow_ratio": 1.00,
        "accel": 800,
        "comment": "fine_detail inner: 50% speed, strong fan",
    },
    # ── SOLID INFILL ───────────────────────────────────────────────────────
    # Top surface on miniatures is often the most visible face.  Slow it down.
    TYPE_SOLID_INFILL: {
        "speed_mm_s": None,  # 60% of profile solid infill speed
        "fan": 230,  # 90%
        "flow_ratio": 1.00,
        "accel": 600,
        "comment": "fine_detail solid infill: slow + strong fan",
    },
    # ── SPARSE INFILL ──────────────────────────────────────────────────────
    # Interior — waste time here would be inefficient, the surface is hidden.
    # Use gyroid/cubic infill for uniform mechanical support.
    TYPE_SPARSE_INFILL: {
        "speed_mm_s": None,  # full profile speed — use all of it
        "fan": 200,
        "flow_ratio": 1.00,
        "comment": "fine_detail sparse infill: full speed",
    },
    # ── BRIDGE ─────────────────────────────────────────────────────────────
    # Miniatures have lots of small bridges — faces, weapons, hair, architecture.
    # Must be flat; sag will read as facial distortion or surface error.
    TYPE_BRIDGE: {
        "speed_mm_s": 15,
        "fan": 255,  # max
        "flow_ratio": 0.90,  # under-extrude bridges to prevent droop
        "accel": 400,
        "comment": "fine_detail bridge: max fan, very slow, under-extrude",
    },
    # ── SUPPORT ────────────────────────────────────────────────────────────
    # Supports will be removed.  Speed them up so they don't dominate print time.
    # Keep fan high so they're rigid and break off cleanly.
    TYPE_SUPPORT: {
        "speed_mm_s": None,  # 130% of profile inner wall speed
        "fan": 200,
        "flow_ratio": 0.90,  # lighter — easier removal, lower adhesion
        "comment": "fine_detail support: fast, under-extrude, easy-release",
    },
    # ── SKIRT/BRIM ─────────────────────────────────────────────────────────
    TYPE_SKIRT: {
        "speed_mm_s": 20,
        "fan": 0,  # don't chill the first layer excessively
        "flow_ratio": 1.05,  # brim gets good floor contact
        "comment": "fine_detail skirt/brim: slow, no fan, over-extrude",
    },
}


def get_override(feature_type: str, layer: int, profile) -> Optional[dict]:
    base = OVERRIDES.get(feature_type)
    if base is None:
        return None

    result = dict(base)

    # Dynamic speed
    if result.get("speed_mm_s") is None:
        profile_speed = _profile_speed(feature_type, profile)
        if profile_speed:
            mult = {
                TYPE_OUTER_WALL: 0.25,
                TYPE_INNER_WALL: 0.50,
                TYPE_SOLID_INFILL: 0.60,
                TYPE_SPARSE_INFILL: 1.00,
                TYPE_BRIDGE: None,  # hard-coded
                TYPE_SUPPORT: 1.30,
                TYPE_SKIRT: None,  # hard-coded
            }.get(feature_type, 1.0)
            if mult is not None:
                result["speed_mm_s"] = max(8, round(profile_speed * mult))

    # Don't bump temp for fine detail — high temp = more ooze on thin walls
    result.setdefault("nozzle_temp", getattr(profile, "NOZZLE_TEMP_NOMINAL", None))

    # First few layers: keep fan off to ensure adhesion
    if layer <= getattr(profile, "CLOSE_FAN_FIRST_N_LAYERS", 3):
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
    }.get(feature_type)
    return getattr(profile, attr, None) if attr else None


def describe() -> str:
    return (
        f"Rule: {RULE_ID} v{RULE_VERSION}\n"
        f"Description: {RULE_DESCRIPTION}\n"
        "Strategy: outer wall at 25% of profile speed, max fan on all surfaces,\n"
        "          low accel (400mm/s²), 100% fan on bridges + under-extrude to prevent sag.\n"
        "Recommended: 0.05–0.1mm layer height, 3+ perimeters, gyroid infill."
    )
