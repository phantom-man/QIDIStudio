"""
agents/parts_catalog/kit_template_builder.py

Assembles KitBundle records and MachineTemplate records from already-harvested parts.

This agent runs AFTER all other harvesters have populated the LanceDB cnc_parts table.
It does NOT do web scraping — it:
  1. Queries LanceDB for the best-available parts per category + tier
  2. Assembles curated known-good KitBundle records
  3. Assembles MachineTemplate records (abstract component requirements for each
     machine type: 3-axis CNC router, benchtop mill, CoreXY, CO2 laser, etc.)
  4. Writes results to Firestore cnc_parts/kits and cnc_parts/templates
  5. Upserts searchable records into LanceDB

Kit tiers produced:
  - hobby:     Entry 3-axis CNC router, hobby CO2 laser, entry CoreXY printer
  - prosumer:  LEAD 1010 CNC, 2.2kW water-cooled, NVUM controller
  - industrial: LinuxCNC Mesa 5i25, DMA860S, SFU2005, HGR25, ATC spindle
  - aerospace:  5-axis mill config, Leadshine servo drives, Hiwin HGR25UP, BT30 ATC

Usage (run AFTER all other harvesters):
    memory_env/Scripts/python.exe agents/parts_catalog/kit_template_builder.py \
        > agents/parts_catalog/_kits_log.txt 2>&1
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("kit_template_builder")

from agents.parts_catalog.store import (
    write_part,
    upsert_lancedb_embedding,
    load_progress,
    save_progress,
    slug,
    _gcs,
)
from agents.parts_catalog.schema import (
    KitBundle,
    MachineTemplate,
    MachineType,
    Tier,
    PartRef,
)
from agents.parts_catalog.search import gemini_search_json

HARVESTER_NAME = "kit_template_builder"


# ── LanceDB query helper ──────────────────────────────────────────────────────


def find_best_parts(
    category: str, tier: str, description_keywords: str, top_k: int = 5
) -> list[dict]:
    """Search the cnc_parts LanceDB table for the best matching parts."""
    try:
        import lancedb
        import os

        lancedb_path = os.environ.get("LANCEDB_PATH", "gs://qidistudio-lancedb/lancedb")
        storage_options = {
            "timeout": "60s",
            "connect_timeout": "30s",
            "max_retries": "5",
        }

        if lancedb_path.startswith(("gs://", "s3://", "az://", "gcs://")):
            db = lancedb.connect(lancedb_path, storage_options=storage_options)
        else:
            from pathlib import Path as _Path

            _Path(lancedb_path).mkdir(parents=True, exist_ok=True)
            db = lancedb.connect(lancedb_path)

        if "cnc_parts" not in db.table_names():
            log.warning(
                "cnc_parts table not found in LanceDB — harvesters may not have run yet"
            )
            return []

        table = db.open_table("cnc_parts")
        query_text = f"{tier} {category} {description_keywords}"

        # Vector search using the embedding
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
        query_vec = model.encode(query_text).tolist()

        results = (
            table.search(query_vec)
            .where(f"category = '{category}'")
            .limit(top_k)
            .to_list()
        )
        return results
    except Exception as e:
        log.warning("LanceDB search failed: %s", e)
        return []


# ── Kit definitions ───────────────────────────────────────────────────────────

KIT_DEFINITIONS = [
    {
        "id": "kit_hobby_3axis_cnc_v1",
        "name": "Hobby 3-Axis CNC Router Starter Kit",
        "machine_type": "cnc_router_3axis",
        "tier": "hobby",
        "description": (
            "Entry-level 3-axis CNC router build. NEMA 23 steppers on X/Y, "
            "NEMA 17 on Z, DM542 drivers, GRBL controller, SFU1605 ball screws, "
            "HGR20 rails, 2.2kW water-cooled spindle, 48V Meanwell PSU. "
            "Work area ~400x400x80mm. Budget ~$600 USD in parts."
        ),
        "tags": ["hobby", "cnc_router", "3axis", "grbl", "beginner"],
        "required_categories": {
            "motors": {"count": 3, "keywords": "NEMA 23 stepper 57HS 2.8A"},
            "drivers": {"count": 3, "keywords": "DM542 stepper driver 50V 4A"},
            "rails": {"count": 6, "keywords": "HGR20 linear guide 400mm 500mm"},
            "lead_screws": {"count": 3, "keywords": "SFU1605 ball screw C7 400mm"},
            "controllers": {"count": 1, "keywords": "GRBL CNC shield V3 USB"},
            "spindles": {"count": 1, "keywords": "2.2kW water cooled ER20 spindle"},
            "power_supplies": {
                "count": 1,
                "keywords": "48V 10A Meanwell switching PSU",
            },
            "couplers": {"count": 3, "keywords": "8mm flexible coupler stepper"},
            "sensors": {"count": 6, "keywords": "mechanical endstop micro switch"},
        },
        "affiliate_bundle_available": False,
        "affiliate_bundle_url": None,
        "affiliate_bundle_discount_percent": None,
    },
    {
        "id": "kit_prosumer_3axis_cnc_v1",
        "name": "Prosumer 3-Axis CNC Mill Router",
        "machine_type": "cnc_router_3axis",
        "tier": "prosumer",
        "description": (
            "Mid-range CNC router. NEMA 23 2.8Nm steppers, DMA860S 80V drivers, "
            "Mesa 7i76E + LinuxCNC, SFU2005 C5 ball screws, HGR25 rails, "
            "2.2kW ATC-ready spindle, 72V PSU. Work area ~600x600x120mm."
        ),
        "tags": ["prosumer", "cnc_router", "3axis", "linuxcnc", "mesa", "dma860s"],
        "required_categories": {
            "motors": {"count": 3, "keywords": "NEMA 23 3Nm high torque stepper"},
            "drivers": {"count": 3, "keywords": "DMA860S 80V 8A stepper driver"},
            "rails": {"count": 6, "keywords": "HGR25 Hiwin linear guide 600mm"},
            "lead_screws": {"count": 3, "keywords": "SFU2005 C5 ball screw 600mm"},
            "controllers": {"count": 1, "keywords": "Mesa 7i76E LinuxCNC Ethernet"},
            "spindles": {"count": 1, "keywords": "2.2kW ER20 water cooled CNC spindle"},
            "power_supplies": {
                "count": 2,
                "keywords": "72V 10A switching PSU + 24V control",
            },
            "couplers": {"count": 3, "keywords": "bellows coupling 12mm precision CNC"},
            "sensors": {"count": 6, "keywords": "inductive proximity M12 NPN endstop"},
        },
        "affiliate_bundle_available": False,
        "affiliate_bundle_url": None,
        "affiliate_bundle_discount_percent": None,
    },
    {
        "id": "kit_hobby_co2_laser_v1",
        "name": "Hobby 60W CO2 Laser Cutter",
        "machine_type": "co2_laser",
        "tier": "hobby",
        "description": (
            "60W CO2 laser cutter build. NEMA 23 on X/Y, DM542 drivers, "
            "Ruida DSP controller, MGN15 rails, belt drive Z, 60W PSU, "
            "water pump for tube cooling. Work area ~600x400mm."
        ),
        "tags": ["hobby", "co2_laser", "ruida", "2axis", "cutting", "engraving"],
        "required_categories": {
            "motors": {"count": 2, "keywords": "NEMA 23 57HS 2A stepper laser"},
            "drivers": {"count": 2, "keywords": "DM542 stepper driver"},
            "rails": {"count": 4, "keywords": "MGN15 linear guide 600mm"},
            "controllers": {
                "count": 1,
                "keywords": "Ruida RDC6445 DSP laser controller",
            },
            "spindles": {"count": 1, "keywords": "60W CO2 laser tube"},
            "power_supplies": {"count": 1, "keywords": "MYJG 60W CO2 laser PSU"},
            "sensors": {"count": 4, "keywords": "optical endstop laser CNC"},
        },
        "affiliate_bundle_available": False,
        "affiliate_bundle_url": None,
        "affiliate_bundle_discount_percent": None,
    },
    {
        "id": "kit_industrial_3axis_mill_v1",
        "name": "Industrial 3-Axis CNC Knee Mill Conversion",
        "machine_type": "benchtop_mill",
        "tier": "industrial",
        "description": (
            "Industrial-grade 3-axis CNC conversion. NEMA 34 4.5Nm steppers, "
            "DMA860S at 80V, Mesa 5i25 + 7i76 LinuxCNC FPGA, SFU2505 C3 ball screws, "
            "HGR35 rails or box ways, 3.7kW ATC BT30 spindle, "
            "dual PSU 80V+24V, Renishaw-style toolsetter, spindle encoder."
        ),
        "tags": ["industrial", "cnc_mill", "3axis", "linuxcnc", "mesa", "atc", "bt30"],
        "required_categories": {
            "motors": {"count": 3, "keywords": "NEMA 34 4.5Nm stepper 86HS industrial"},
            "drivers": {
                "count": 3,
                "keywords": "DMA860S 80V high current stepper driver",
            },
            "rails": {"count": 4, "keywords": "HGR35 Hiwin linear guide 800mm"},
            "lead_screws": {
                "count": 3,
                "keywords": "SFU2505 C3 ball screw 800mm precision",
            },
            "controllers": {"count": 2, "keywords": "Mesa 5i25 7i76 LinuxCNC FPGA PCI"},
            "spindles": {"count": 1, "keywords": "3.7kW BT30 ATC water cooled spindle"},
            "power_supplies": {
                "count": 2,
                "keywords": "80V 10A DC switching PSU industrial",
            },
            "couplers": {"count": 3, "keywords": "oldham coupling 14mm precision CNC"},
            "sensors": {
                "count": 8,
                "keywords": "inductive proximity M12 M18 CNC endstop",
            },
        },
        "affiliate_bundle_available": False,
        "affiliate_bundle_url": None,
        "affiliate_bundle_discount_percent": None,
    },
]


MACHINE_TEMPLATES = [
    {
        "machine_type": "cnc_router_3axis",
        "name": "3-Axis CNC Router / Milling Machine",
        "description": "Standard 3-axis gantry CNC router. X/Y driven by steppers on linear rails + ball screws; Z-axis for tool depth. Spindle for cutting aluminium, wood, PCB.",
        "required_axis_count": 3,
        "required_categories": [
            "motors",
            "drivers",
            "rails",
            "lead_screws",
            "controllers",
            "spindles",
            "power_supplies",
            "couplers",
            "sensors",
            "frames",
        ],
        "typical_tier": "hobby",
        "notes": "Most flexible machine type. MGN/HGR rails, SFU ball screws or ACME T8 for Z.",
    },
    {
        "machine_type": "benchtop_mill",
        "name": "Benchtop CNC Knee Mill",
        "description": "Conversion of manual knee mill or purpose-built. High stiffness, NEMA 34 motors, ball or box ways, appropriate for aluminium/steel.",
        "required_axis_count": 3,
        "required_categories": [
            "motors",
            "drivers",
            "rails",
            "lead_screws",
            "controllers",
            "spindles",
            "power_supplies",
            "couplers",
            "sensors",
        ],
        "typical_tier": "industrial",
        "notes": "Heavy machine. SFU2005+ ball screws, DMA860S drivers, LinuxCNC recommended.",
    },
    {
        "machine_type": "corexy_printer",
        "name": "CoreXY 3D Printer / Laser",
        "description": "CoreXY motion system with belt drive for X/Y, lead screw or belt for Z. Optimised for speed and print quality.",
        "required_axis_count": 3,
        "required_categories": [
            "motors",
            "drivers",
            "rails",
            "controllers",
            "power_supplies",
            "sensors",
            "frames",
        ],
        "typical_tier": "hobby",
        "notes": "TMC2209/5160A drivers, MGN rails, Klipper on Octopus or BTT boards.",
    },
    {
        "machine_type": "cnc_lathe",
        "name": "CNC Lathe",
        "description": "2-axis CNC lathe (Z-carriage, X cross-slide). Spindle encoder for CSS (constant surface speed) and rigid tapping.",
        "required_axis_count": 2,
        "required_categories": [
            "motors",
            "drivers",
            "lead_screws",
            "controllers",
            "power_supplies",
            "couplers",
            "sensors",
        ],
        "typical_tier": "prosumer",
        "notes": "Requires spindle encoder. LinuxCNC strongly recommended.",
    },
    {
        "machine_type": "co2_laser",
        "name": "CO2 Laser Cutter",
        "description": "2-axis gantry laser cutter with CO2 tube. Ruida DSP or GRBL controller. Chiller/water pump required.",
        "required_axis_count": 2,
        "required_categories": [
            "motors",
            "drivers",
            "rails",
            "controllers",
            "spindles",
            "power_supplies",
            "sensors",
        ],
        "typical_tier": "hobby",
        "notes": "CO2 tube = spindle. Ruida controller for commercial-style use; GRBL for LightBurn.",
    },
]


def build_kit(kit_def: dict, all_harvested: bool = True) -> dict | None:
    """Build a KitBundle record, optionally querying LanceDB for real part IDs."""
    doc_id = kit_def["id"]
    parts: list[PartRef] = []

    for cat, spec in kit_def.get("required_categories", {}).items():
        count = spec.get("count", 1)
        keywords = spec.get("keywords", cat)

        if all_harvested:
            results = find_best_parts(cat, kit_def["tier"], keywords, top_k=count)
            for r in results[:count]:
                parts.append(
                    PartRef(
                        category=cat,
                        doc_id=r.get("doc_id", "unknown"),
                        name=r.get("name", "unknown"),
                        quantity=1,
                        notes=keywords,
                    )
                )
        else:
            # Placeholder — no real doc_ids yet
            parts.append(
                PartRef(
                    category=cat,
                    doc_id=f"placeholder_{cat}",
                    name=f"{cat} ({keywords[:40]})",
                    quantity=count,
                    notes=keywords,
                )
            )

    try:
        tier = Tier(kit_def["tier"])
    except ValueError:
        tier = Tier.HOBBY

    try:
        machine_type = MachineType(kit_def["machine_type"])
    except ValueError:
        machine_type = MachineType.CNC_ROUTER_3AXIS

    return KitBundle(
        doc_id=doc_id,
        category="kits",
        name=kit_def["name"],
        brand="NexusMill",
        model=doc_id,
        tier=tier,
        description=kit_def["description"],
        tags=kit_def.get("tags", []),
        machine_type=machine_type,
        parts=parts,
        affiliate_bundle_available=kit_def.get("affiliate_bundle_available", False),
        affiliate_bundle_url=kit_def.get("affiliate_bundle_url"),
        affiliate_bundle_discount_percent=kit_def.get(
            "affiliate_bundle_discount_percent"
        ),
        scraped_at=datetime.now(timezone.utc).isoformat(),
    ).model_dump()


def build_template(tmpl_def: dict) -> dict:
    """Build a MachineTemplate record."""
    doc_id = slug("template", tmpl_def["machine_type"])
    try:
        machine_type = MachineType(tmpl_def["machine_type"])
    except ValueError:
        machine_type = MachineType.CNC_ROUTER_3AXIS

    return MachineTemplate(
        doc_id=doc_id,
        category="templates",
        name=tmpl_def["name"],
        brand="NexusMill",
        model=doc_id,
        tier=Tier.HOBBY,
        description=tmpl_def["description"],
        tags=[tmpl_def["machine_type"]],
        machine_type=machine_type,
        required_axis_count=tmpl_def["required_axis_count"],
        required_categories=tmpl_def["required_categories"],
        typical_tier=tmpl_def.get("typical_tier", "hobby"),
        notes=tmpl_def.get("notes", ""),
        scraped_at=datetime.now(timezone.utc).isoformat(),
    ).model_dump()


def run():
    log.info("=== Kit Template Builder starting ===")
    progress = load_progress(HARVESTER_NAME)
    total = progress.get("total_written", 0)

    # Phase 1: build kits (try LanceDB first, fall back to placeholders)
    log.info("--- Phase 1: Assembling kit bundles ---")
    for kit_def in KIT_DEFINITIONS:
        kit_id = kit_def["id"]
        if kit_id in progress.get("completed_kits", []):
            log.info("Skipping already-built kit: %s", kit_id)
            continue

        log.info("Building kit: %s", kit_def["name"])
        kit_dict = build_kit(kit_def, all_harvested=True)
        if kit_dict:
            write_part(kit_dict)
            upsert_lancedb_embedding(kit_dict)
            total += 1
            log.info(
                "  Kit written: %s — %d parts", kit_id, len(kit_dict.get("parts", []))
            )
        else:
            log.warning("Failed to build kit: %s", kit_id)

        progress.setdefault("completed_kits", []).append(kit_id)
        progress["total_written"] = total
        save_progress(HARVESTER_NAME, progress)
        time.sleep(1)

    # Phase 2: build machine templates
    log.info("--- Phase 2: Assembling machine templates ---")
    for tmpl_def in MACHINE_TEMPLATES:
        tmpl_id = f"template_{tmpl_def['machine_type']}"
        if tmpl_id in progress.get("completed_templates", []):
            log.info("Skipping: %s", tmpl_id)
            continue

        log.info("Building template: %s", tmpl_def["name"])
        tmpl_dict = build_template(tmpl_def)
        write_part(tmpl_dict)
        upsert_lancedb_embedding(tmpl_dict)
        total += 1
        log.info("  Template written: %s", tmpl_id)

        progress.setdefault("completed_templates", []).append(tmpl_id)
        progress["total_written"] = total
        save_progress(HARVESTER_NAME, progress)
        time.sleep(1)

    log.info("=== Kit Template Builder complete — total: %d records ===", total)


if __name__ == "__main__":
    run()
