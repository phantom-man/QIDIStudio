"""
agents/parts_catalog/power_supply_harvester.py

Discovers and catalogs power supplies for CNC machines.

Covers:
  - DC switching PSUs: Meanwell LRS/RSP/SE series (12/24/36/48/60/72V)
  - High-voltage DC: 48V, 60V, 72V, 80V for high-torque stepper/servo systems
  - VFDs (Variable Frequency Drives): Huanyang HY series, Delta VFD-E/VFD-M,
    Yaskawa V1000, Omron MX2, Hitachi WJ200 — for AC spindle motors
  - HV laser PSUs: MYJG/LPS series for CO2 tubes (40W–150W)
  - 3-phase input industrial PSUs for large mills

Key specs: output voltage/current/wattage, input voltage range, efficiency,
           VFD: output Hz range, torque boost, braking resistor support

Usage:
    memory_env/Scripts/python.exe agents/parts_catalog/power_supply_harvester.py \
        > agents/parts_catalog/_psu_log.txt 2>&1
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
log = logging.getLogger("psu_harvester")

from agents.parts_catalog.search import search_and_extract_json
from agents.parts_catalog.store import (
    write_part,
    download_image,
    upsert_lancedb_embedding,
    load_progress,
    save_progress,
    slug,
)
from agents.parts_catalog.schema import PowerSupply, Tier

HARVESTER_NAME = "power_supply_harvester"
CATEGORY = "power_supplies"

DISCOVERY_QUERIES = [
    "Meanwell LRS-350 LRS-600 switching power supply complete series specifications: output voltage variants, output current, wattage, efficiency, input voltage range, dimensions, price",
    "Meanwell RSP series RSP-500 RSP-750 RSP-1000 high power PSU specifications for CNC industrial use voltage current wattage",
    "48V 10A 20A 30A 50A DC switching power supply CNC stepper motor specifications brands S-480-48 UHP-480-48",
    "72V 80V DC power supply switching mode for stepper motor CNC high voltage specifications current wattage brand alternatives",
    "Huanyang VFD HY series 1.5kW 2.2kW 4kW specifications: input voltage 1ph/3ph, output frequency 0-400Hz, output voltage, carrier frequency, control method (V/f vector), dimensions, price",
    "Delta VFD-E VFD-M VFD-EL Variable Frequency Drive specifications 0.75kW 1.5kW 2.2kW 3.7kW: input/output phases, frequency range, torque boost, braking resistor terminal",
    "Yaskawa V1000 VFD specifications 0.1kW to 7.5kW: 1ph/3ph input, output frequency range, control modes, dimensions, weight",
    "CO2 laser power supply MYJG 40W 60W 80W 100W 130W 150W specifications: HV output kV, tube current mA, control input 0-5V TTL, input voltage, dimensions",
    "CO2 laser PSU LPS-150F LPS-100F LPS-80F specifications for laser tube high voltage current regulation protection",
    "3-phase 380V industrial switching power supply 24V 48V for CNC control panel Phoenixtec Powerware specifications",
]

EXTRACTION_SCHEMA = """
Return a JSON array. Each object (null if unknown):
{
  "brand": "string",
  "model": "string",
  "psu_type": "string (dc_switching|vfd|hv_laser|ac_industrial|battery)",
  "output_voltage_v": number,
  "output_current_a": number,
  "output_power_w": number,
  "input_voltage_range": "string (e.g. 85-264VAC)",
  "input_phases": number,
  "efficiency_percent": number,
  "output_ripple_mv": number,
  "vfd_output_freq_min_hz": number,
  "vfd_output_freq_max_hz": number,
  "vfd_motor_hp": number,
  "vfd_control_modes": ["string"],
  "laser_hv_kv": number,
  "laser_tube_current_ma": number,
  "protection_features": ["string"],
  "dimensions_mm": "string",
  "weight_kg": number,
  "tier": "hobby|prosumer|industrial|aerospace",
  "description": "string",
  "datasheet_url": "string",
  "image_url": "string",
  "purchase_urls": [{"supplier": "string", "url": "string", "price_usd": "string"}],
  "tags": ["string"]
}
"""


def process_psu_record(raw: dict) -> PowerSupply | None:
    try:
        doc_id = slug(
            CATEGORY, raw.get("brand", "unknown"), raw.get("model", "unknown")
        )
        try:
            tier = Tier(raw.get("tier", "hobby"))
        except ValueError:
            tier = Tier.HOBBY

        psu = PowerSupply(
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
            psu_type=raw.get("psu_type", "dc_switching"),
            output_voltage_v=raw.get("output_voltage_v"),
            output_current_a=raw.get("output_current_a"),
            output_power_w=raw.get("output_power_w"),
            input_voltage_range=raw.get("input_voltage_range"),
            input_phases=raw.get("input_phases", 1),
            efficiency_percent=raw.get("efficiency_percent"),
            output_ripple_mv=raw.get("output_ripple_mv"),
            vfd_output_freq_min_hz=raw.get("vfd_output_freq_min_hz"),
            vfd_output_freq_max_hz=raw.get("vfd_output_freq_max_hz"),
            vfd_motor_hp=raw.get("vfd_motor_hp"),
            vfd_control_modes=raw.get("vfd_control_modes", []),
            laser_hv_kv=raw.get("laser_hv_kv"),
            laser_tube_current_ma=raw.get("laser_tube_current_ma"),
            protection_features=raw.get("protection_features", []),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )
        return psu
    except Exception as e:
        log.warning("Failed to build PSU from %s: %s", raw.get("model", "?"), e)
        return None


def run():
    log.info("=== PSU Harvester starting ===")
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
            psu = process_psu_record(raw)
            if psu is None:
                continue
            part_dict = psu.model_dump()
            if psu.image_url and not psu.image_gcs:
                part_dict["image_gcs"] = download_image(
                    psu.image_url, CATEGORY, psu.doc_id
                )
            write_part(part_dict)
            upsert_lancedb_embedding(part_dict)
            written += 1
            total += 1
            log.info(
                "  Written: %s — %sV %sW",
                psu.name,
                psu.output_voltage_v,
                psu.output_power_w,
            )
        log.info("Query done — %d written (total: %d)", written, total)
        completed.add(query)
        save_progress(
            HARVESTER_NAME,
            {"completed_queries": list(completed), "total_written": total},
        )
        time.sleep(3)

    log.info("=== PSU Harvester complete — total: %d ===", total)


if __name__ == "__main__":
    run()
