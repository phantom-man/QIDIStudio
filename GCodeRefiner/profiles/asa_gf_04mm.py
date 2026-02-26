"""
ASA-GF + 0.4mm Hardened Steel Nozzle — Filament & Nozzle Profile
Qidi Q2 2025, Siraya Tech Fibreheart ASA-GF

This profile defines the BASE parameter envelope for this filament+nozzle combo.
Rule files (rules/*.py) OVERRIDE these values per feature type.

All temperatures in °C. All speeds in mm/s. Fan 0–255 (255 = 100%).
"""


# ---------------------------------------------------------------------------
# Nozzle / hardware identity
# ---------------------------------------------------------------------------

NOZZLE_DIAMETER_MM = 0.4
NOZZLE_TYPE = "hardened_steel"
# Hardened steel runs ~10°C colder than brass at same power setting.
# Compensate by running +5-10°C vs brass-nozzle ASA recommendations.
NOZZLE_TEMP_OFFSET = 8  # +8°C over brass-nozzle reference values

# ---------------------------------------------------------------------------
# Filament identity
# ---------------------------------------------------------------------------

FILAMENT_NAME = "Siraya Tech Fibreheart ASA-GF"
FILAMENT_TYPE = "ASA-GF"
FILAMENT_DIAMETER_MM = 1.75
# Glass fiber content increases viscosity and reduces flow at high speed.
# Compensate with slightly higher base temperature and lower top speed.
FIBER_CONTENT_PERCENT = 20  # approximate

# ---------------------------------------------------------------------------
# Base temperature envelope
# ---------------------------------------------------------------------------

# Nominal temps for this filament+nozzle combo
NOZZLE_TEMP_NOMINAL      = 270  # °C — standard ASA-GF printing temp
NOZZLE_TEMP_FIRST_LAYER  = 280  # °C — maximum adhesion on first layer
NOZZLE_TEMP_MIN          = 260  # °C — lower bound (will under-extrude below this)
NOZZLE_TEMP_MAX          = 285  # °C — upper bound (risk of degradation above this)

BED_TEMP_NOMINAL         = 100  # °C — standard ASA-GF bed temp
BED_TEMP_FIRST_LAYER     = 105  # °C — slightly higher for first layer adhesion

CHAMBER_TEMP             =  65  # °C — required to prevent ASA warping

# ---------------------------------------------------------------------------
# Base speed envelope (mm/s)
# ---------------------------------------------------------------------------

SPEED_OUTER_WALL         = 40   # mm/s — outer perimeter nominal
SPEED_INNER_WALL         = 60   # mm/s — inner perimeters
SPEED_SOLID_INFILL       = 80   # mm/s — solid (top/bottom) infill
SPEED_SPARSE_INFILL      = 120  # mm/s — sparse infill (gyroid, cubic, etc.)
SPEED_BRIDGE             = 25   # mm/s — bridge moves (need cooling + flow control)
SPEED_FIRST_LAYER        = 20   # mm/s — first layer
SPEED_TRAVEL             = 200  # mm/s — non-extrusion travel

# ---------------------------------------------------------------------------
# Base fan envelope (0-255)
# ---------------------------------------------------------------------------

# ASA warps with aggressive cooling. Keep fan off or minimal for most features.
# Only bridges and top surfaces need active cooling.
FAN_OUTER_WALL           = 0    # off — maximize layer fusion
FAN_INNER_WALL           = 0    # off
FAN_SOLID_INFILL         = 50   # 20% — light cooling for flat surfaces
FAN_SPARSE_INFILL        = 80   # 31% — ok for infill
FAN_BRIDGE               = 255  # 100% — bridges always need max cooling
FAN_FIRST_LAYERS         = 0    # off — critical: first 5 layers must bond hard

CLOSE_FAN_FIRST_N_LAYERS = 5    # keep fan off for this many layers from bottom

# ---------------------------------------------------------------------------
# Flow ratio envelope
# ---------------------------------------------------------------------------

# ASA-GF benefits from slight over-extrusion on structural features.
# Under-extrusion on infill is acceptable (it's interior).
FLOW_OUTER_WALL          = 1.02  # slight over-extrude for wall integrity
FLOW_INNER_WALL          = 1.00
FLOW_SOLID_INFILL        = 1.00
FLOW_SPARSE_INFILL       = 0.98  # slight under OK — interior, not visible
FLOW_BRIDGE              = 0.90  # under-extrude bridges to reduce sag
FLOW_FIRST_LAYER         = 1.05  # over-extrude first layer for max contact

# ---------------------------------------------------------------------------
# Layer geometry
# ---------------------------------------------------------------------------

LAYER_HEIGHT_NOMINAL     = 0.20  # mm — standard
LAYER_HEIGHT_FINE        = 0.15  # mm — recommended for mechanical parts
LAYER_HEIGHT_ULTRA_FINE  = 0.10  # mm — small features (threads, fine teeth)
LINE_WIDTH               = 0.45  # mm — 112% of nozzle diameter

# ---------------------------------------------------------------------------
# Acceleration / jerk (Klipper INPUT_SHAPER units)
# ---------------------------------------------------------------------------

ACCEL_PERIMETER          = 1500  # mm/s² — lower accel on walls = better geometry
ACCEL_INFILL             = 5000  # mm/s² — fast infill ok
ACCEL_TRAVEL             = 8000  # mm/s²

# ---------------------------------------------------------------------------
# Retraction
# ---------------------------------------------------------------------------

RETRACT_LENGTH_MM        = 0.8   # mm — short retract (direct drive assumed)
RETRACT_SPEED_MM_S       = 45    # mm/s

# ---------------------------------------------------------------------------
# Profile metadata
# ---------------------------------------------------------------------------

PROFILE_ID               = "asa_gf_04mm"
PROFILE_VERSION          = "1.0.0"
PROFILE_DESCRIPTION      = "ASA-GF + 0.4mm hardened steel nozzle, Qidi Q2 2025"
