"""
Anycubic PLA-HS + CHT Diamond 0.4mm — Filament & Nozzle Profile
Qidi Q2 2025

Primary use-cases: small gears, watertight vessels, fine-detail, fast-draft.
AMEO material ID  : anycubic_pla_hs
AMEO nozzle ID    : cht_diamond_04

The CHT multi-channel melt path gives ~1.5× volumetric throughput vs brass 0.4mm.
Speed ceiling at 0.2mm layer: 250 mm/s (V_max 21 mm³/s).

All temperatures in °C. All speeds in mm/s. Fan 0–255 (255 = 100%).
"""

# ---------------------------------------------------------------------------
# Nozzle / hardware identity
# ---------------------------------------------------------------------------

NOZZLE_DIAMETER_MM = 0.4
NOZZLE_TYPE = "cht"  # multi-channel, diamond tip
NOZZLE_K_FACTOR = 1.5  # AMEO thermal multiplier vs brass baseline
NOZZLE_PA_BASE = 0.025  # CHT lower PA vs stock brass (shorter melt zone)

# CHT runs marginally cooler than brass at the same volumetric rate because
# the multi-channel path distributes heat more evenly.
NOZZLE_TEMP_OFFSET = 0  # no correction needed over standard PLA-HS temps

# ---------------------------------------------------------------------------
# Filament identity
# ---------------------------------------------------------------------------

FILAMENT_NAME = "Anycubic High Speed PLA"
FILAMENT_TYPE = "pla"
FILAMENT_VARIANT = "hs"
FILAMENT_DIAMETER_MM = 1.75
MFI = 14.0  # melt flow index at 210°C / 2.16kg
MU_FACTOR = MFI / 10.0  # AMEO viscosity multiplier = 1.4

# ---------------------------------------------------------------------------
# Base temperature envelope
# ---------------------------------------------------------------------------

NOZZLE_TEMP_NOMINAL = 230  # °C — standard PLA-HS with CHT
NOZZLE_TEMP_FIRST_LAYER = 235  # °C — slightly warmer for adhesion
NOZZLE_TEMP_MIN = 200  # °C — absolute lower bound
NOZZLE_TEMP_MAX = 270  # °C — upper bound; discoloration risk above 260

BED_TEMP_NOMINAL = 55  # °C
BED_TEMP_FIRST_LAYER = 60  # °C — ensures first-layer stick on PEI/textured
BED_TEMP_MIN = 25  # °C — unheated bed works for short prints

CHAMBER_TEMP = 0  # no enclosure needed for PLA

# ---------------------------------------------------------------------------
# Base speed envelope (mm/s)
# CHT ceiling: 250 mm/s outer wall at 0.2mm layer.
# These are conservative base values; rule files scale them per use-case.
# ---------------------------------------------------------------------------

SPEED_OUTER_WALL = 150  # mm/s — ~60% of CHT ceiling (quality headroom)
SPEED_INNER_WALL = 200  # mm/s
SPEED_SOLID_INFILL = 200  # mm/s
SPEED_SPARSE_INFILL = 250  # mm/s — CHT max throughput
SPEED_BRIDGE = 60  # mm/s — bridging needs cooling, not speed
SPEED_FIRST_LAYER = 50  # mm/s
SPEED_TRAVEL = 300  # mm/s — Qidi Q2 input-shaper capable

# Maximum physical velocity (used by fast_draft.py rule as cap)
SPEED_TRAVEL_MAX = 300  # mm/s

# ---------------------------------------------------------------------------
# Acceleration (mm/s²)
# ---------------------------------------------------------------------------

ACCEL_PERIMETER = 5000
ACCEL_INFILL = 10000
ACCEL_TRAVEL = 15000
ACCEL_MAX = 15000  # used by fast_draft.py as ceiling

# ---------------------------------------------------------------------------
# Fan envelope (0–255)
# ---------------------------------------------------------------------------

FAN_OUTER_WALL = 255  # full cooling — PLA-HS benefits from max fan
FAN_INNER_WALL = 200
FAN_SOLID_INFILL = 200
FAN_SPARSE_INFILL = 150
FAN_BRIDGE = 255  # always max on bridges
FAN_FIRST_LAYERS = 0  # off for first layer adhesion

CLOSE_FAN_FIRST_N_LAYERS = 1  # only first layer; PLA-HS cools fast

# ---------------------------------------------------------------------------
# Flow ratios
# ---------------------------------------------------------------------------

FLOW_OUTER_WALL = 1.00  # CHT slightly over-melts — no over-extrude needed
FLOW_INNER_WALL = 1.00
FLOW_SOLID_INFILL = 1.00
FLOW_SPARSE_INFILL = 0.98
FLOW_BRIDGE = 0.92  # under-extrude bridges — reduces droop
FLOW_FIRST_LAYER = 1.02

# ---------------------------------------------------------------------------
# Layer geometry
# ---------------------------------------------------------------------------

LAYER_HEIGHT_NOMINAL = 0.20  # mm
LAYER_HEIGHT_FINE = 0.10  # mm — gears, threads, emboss
LAYER_HEIGHT_SPEED_RUN = 0.28  # mm — fast draft ceiling
LINE_WIDTH = 0.42  # mm — 105% of 0.4mm nozzle

# ---------------------------------------------------------------------------
# Retraction (direct-drive assumed)
# ---------------------------------------------------------------------------

RETRACT_LENGTH_MM = 0.5  # mm — CHT shorter retract (reduced melt zone depth)
RETRACT_SPEED_MM_S = 45  # mm/s

# ---------------------------------------------------------------------------
# Pressure advance tuning
# ---------------------------------------------------------------------------

PA_BASE = NOZZLE_PA_BASE  # 0.025
# PA tuning range for CHT + PLA-HS on Qidi Q2:
PA_TUNE_MIN = 0.018
PA_TUNE_MAX = 0.035

# ---------------------------------------------------------------------------
# Volumetric limits
# ---------------------------------------------------------------------------

VOLUMETRIC_MAX_MM3S = 21.0  # mm³/s at 0.2mm layer, 0.42mm line, 250mm/s
VOLUMETRIC_BASE_MM3S = 16.0  # material limit from datasheet (PLA-HS)
# Effective ceiling is min(hardware, material): 16.0 mm³/s at PLA-HS datasheet peak

# ---------------------------------------------------------------------------
# Profile metadata
# ---------------------------------------------------------------------------

PROFILE_ID = "pla_hs_cht_04mm"
PROFILE_VERSION = "1.0.0"
PROFILE_DESCRIPTION = "Anycubic PLA-HS + CHT Diamond 0.4mm, Qidi Q2 2025"
AMEO_NOZZLE_ID = "cht_diamond_04"
AMEO_MATERIAL_ID = "anycubic_pla_hs"
