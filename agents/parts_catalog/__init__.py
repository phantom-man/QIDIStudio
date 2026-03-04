"""
agents/parts_catalog — NexusMill Parts Catalog harvester fleet.

Modules:
  schema.py              — Pydantic models for all part categories
  store.py               — Firestore + GCS + LanceDB storage helpers
  search.py              — Gemini-native search/extract utilities (no Tavily)
  motor_harvester.py     — NEMA stepper + servo motor catalog
  driver_harvester.py    — Stepper + servo drive catalog
  power_supply_harvester.py — DC PSU + VFD + laser PSU catalog
  rail_harvester.py      — Linear guide catalog (MGN/HGR/SBR/V-slot)
  lead_screw_harvester.py — Lead screw + ball screw catalog
  spindle_harvester.py   — Spindle unit catalog
  controller_harvester.py — CNC motion controller catalog
  frame_harvester.py     — Frame + extrusion profile catalog
  coupler_harvester.py   — Shaft couplers + bearing supports
  sensor_harvester.py    — Endstops + probes + encoders
  kit_template_builder.py — Kit bundles + machine templates
  orchestrator.py        — Runs full fleet in sequence

Quick start:
    memory_env/Scripts/python.exe agents/parts_catalog/orchestrator.py
    memory_env/Scripts/python.exe agents/parts_catalog/orchestrator.py motors drivers
    memory_env/Scripts/python.exe agents/parts_catalog/orchestrator.py --list
"""

__version__ = "0.1.0"
