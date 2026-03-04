"""
agents/parts_catalog/spindle_harvester.py

Discovers and catalogs spindle units for CNC machines.

Covers:
  - Air-cooled spindles: ER11 (0.5–0.8kW), ER16 (1.5kW), ER20 (2.2kW)
  - Water-cooled spindles: ER11–ER32, 0.5–7.5kW, 18k–24k RPM
  - ATC spindles: BT30, ISO30, HSK-A63 — 6k–24k RPM, 3.7–7.5kW
  - Trim routers: Makita RT0701C, Dewalt DWP611, Carbide Compact Router
  - Manual mill spindles: R8 taper, MT2/MT3/MT4, 500W–3kW
  - High-speed spindles: 60k–100k RPM PCB engraving, dental milling
  - VFD-coupled: 2.2kW 3-phase water-cooled with VFD as paired bundle

Key specs: power kW, max RPM, collet type, cooling type, runout TIR mm,
           spindle nose, motor poles, operating voltage, VFD compatibility

Usage:
    memory_env/Scripts/python.exe agents/parts_catalog/spindle_harvester.py \
        > agents/parts_catalog/_spindle_log.txt 2>&1
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

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
log = logging.getLogger("spindle_harvester")

from agents.parts_catalog.search import search_and_extract_json
from agents.parts_catalog.store import (
    write_part,
    download_image,
    upsert_lancedb_embedding,
    load_progress,
    save_progress,
    slug,
)
from agents.parts_catalog.schema import Spindle, Tier

HARVESTER_NAME = "spindle_harvester"
CATEGORY = "spindles"

DISCOVERY_QUERIES = [
    "CNC air-cooled spindle 0.5kW 0.8kW 1.5kW ER11 ER16 specifications: power kW, max RPM, voltage, collet type, TIR runout mm, weight, dimensions, price",
    "water-cooled CNC spindle 1.5kW 2.2kW 3.5kW 4.5kW ER20 ER25 specifications: RPM range, operating voltage 3-phase, collet size, cooling water flow rate, TIR runout, weight, price",
    "CNC spindle 2.2kW water cooled ER20 80mm diameter specifications full: RPM 0-24000, phases 3, frequency 0-400Hz, VFD compatibility, runout 0.01mm, weight",
    "ATC automatic tool change spindle BT30 ISO30 HSK specifications: power kW, RPM range, air pressure bar, draw bar force, tool change time, cooling type, price",
    "Makita RT0701C Dewalt DWP611 Carbide3D compact router spindle specifications: RPM range, collet sizes, power W, dimensions, weight, noise dB",
    "R8 taper mill spindle manual milling machine specifications: taper, drawbar thread, RPM, motor power, head casting",
    "high speed spindle 60000 RPM 100000 RPM PCB engraving dental milling specifications: collet ER8 ER11, power, air bearing vs ball bearing, runout",
    "ISO20 ISO30 BT40 spindle toolholder specifications: taper dimensions, pull stud type, gauge length, tool holder types",
    "spindle VFD combo kit 2.2kW water cooled 220V specifications complete system: spindle + VFD + water pump + hose + ER collet set, price",
    "LinuxCNC 5-axis trunnion spindle head swivel A-axis B-axis specifications CNC 5-axis conversion",
]

EXTRACTION_SCHEMA = """
Return a JSON array. Each object (null if unknown):
{
  "brand": "string",
  "model": "string",
  "spindle_type": "string (air_cooled|water_cooled|atc|trim_router|mill_head|high_speed)",
  "power_kw": number,
  "voltage_v": number,
  "phases": number,
  "frequency_hz_min": number,
  "frequency_hz_max": number,
  "rpm_min": number,
  "rpm_max": number,
  "collet_type": "string (ER8|ER11|ER16|ER20|ER25|ER32|R8|BT30|ISO30|HSK)",
  "max_collet_diameter_mm": number,
  "tir_runout_mm": number,
  "cooling_type": "string (air|water|none)",
  "water_flow_lpm": number,
  "bearing_type": "string (angular_contact|ceramic|air)",
  "bearing_count": number,
  "atc": boolean,
  "atc_tool_change_time_s": number,
  "atc_air_pressure_bar": number,
  "body_diameter_mm": number,
  "body_length_mm": number,
  "weight_kg": number,
  "noise_db": number,
  "tier": "hobby|prosumer|industrial|aerospace",
  "description": "string",
  "datasheet_url": "string",
  "image_url": "string",
  "purchase_urls": [{"supplier": "string", "url": "string", "price_usd": "string"}],
  "tags": ["string"]
}
"""


def process_spindle_record(raw: dict) -> Spindle | None:
    try:
        doc_id = slug(
            CATEGORY, raw.get("brand", "unknown"), raw.get("model", "unknown")
        )
        try:
            tier = Tier(raw.get("tier", "hobby"))
        except ValueError:
            tier = Tier.HOBBY
        spindle = Spindle(
            doc_id=doc_id,
            category=CATEGORY,
            name=f"{raw.get('brand', '')} {raw.get('model', '')}".strip(),
            brand=raw.get("brand", ""),
            model=raw.get("model", ""),
            tier=tier,
            description=raw.get("description", ""),
            datasheet_url=raw.get("datasheet_url", ""),
            image_url=raw.get("image_url", ""),
            purchase_urls=raw.get("purchase_urls", []),
            tags=raw.get("tags", []),
            spindle_type=raw.get("spindle_type", "water_cooled"),
            power_kw=raw.get("power_kw"),
            voltage_v=raw.get("voltage_v"),
            phases=raw.get("phases"),
            frequency_hz_min=raw.get("frequency_hz_min"),
            frequency_hz_max=raw.get("frequency_hz_max"),
            rpm_min=raw.get("rpm_min"),
            rpm_max=raw.get("rpm_max"),
            collet_type=raw.get("collet_type"),
            max_collet_diameter_mm=raw.get("max_collet_diameter_mm"),
            tir_runout_mm=raw.get("tir_runout_mm"),
            cooling_type=raw.get("cooling_type"),
            water_flow_lpm=raw.get("water_flow_lpm"),
            bearing_type=raw.get("bearing_type"),
            bearing_count=raw.get("bearing_count"),
            atc=raw.get("atc", False),
            atc_tool_change_time_s=raw.get("atc_tool_change_time_s"),
            atc_air_pressure_bar=raw.get("atc_air_pressure_bar"),
            body_diameter_mm=raw.get("body_diameter_mm"),
            body_length_mm=raw.get("body_length_mm"),
            weight_kg=raw.get("weight_kg"),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )
        return spindle
    except Exception as e:
        log.warning("Failed to build Spindle from %s: %s", raw.get("model", "?"), e)
        return None


def run():
    log.info("=== Spindle Harvester starting ===")
    progress = load_progress(HARVESTER_NAME)
    completed = set(progress.get("completed_queries", []))
    total = progress.get("total_written", 0)

    for query in DISCOVERY_QUERIES:
        if query in completed:
            log.info("Skipping: %.80s...", query)
            continue
        log.info("Searching: %.100s...", query)
        raw_list = search_and_extract_json(
            query=query, extraction_instruction=EXTRACTION_SCHEMA
        )
        if not raw_list:
            completed.add(query)
            save_progress(
                HARVESTER_NAME,
                {"completed_queries": list(completed), "total_written": total},
            )
            time.sleep(2)
            continue
        if isinstance(raw_list, dict):
            raw_list = [raw_list]
        written = 0
        for raw in raw_list:
            if not isinstance(raw, dict):
                continue
            spindle = process_spindle_record(raw)
            if spindle is None:
                continue
            part_dict = spindle.model_dump()
            if spindle.image_url and not spindle.image_gcs:
                part_dict["image_gcs"] = download_image(
                    spindle.image_url, CATEGORY, spindle.doc_id
                )
            write_part(part_dict)
            upsert_lancedb_embedding(part_dict)
            written += 1
            total += 1
            log.info(
                "  Written: %s — %skW %sRPM max, collet: %s",
                spindle.name,
                spindle.power_kw,
                spindle.rpm_max,
                spindle.collet_type,
            )
        log.info("Query done — %d written (total: %d)", written, total)
        completed.add(query)
        save_progress(
            HARVESTER_NAME,
            {"completed_queries": list(completed), "total_written": total},
        )
        time.sleep(3)

    log.info("=== Spindle Harvester complete — total: %d ===", total)


if __name__ == "__main__":
    run()
