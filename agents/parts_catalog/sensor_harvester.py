"""
agents/parts_catalog/sensor_harvester.py

Discovers and catalogs sensors and endstop/probing hardware for CNC machines.

Covers:
  - Mechanical endstops: micro switches SPDT (Omron D2F-L, generic SS variety)
  - Optical endstops: slotted optical sensor boards
  - Inductive proximity probes: NPN/PNP, 3-wire, M8/M12/M18 diameter,
    sensing range 1–10mm, 6–36V supply  
  - Capacitive proximity probes: M12/M18
  - BL-Touch / 3D touch / CR Touch variants — Z-probe for auto-levelling
  - Tool length sensors: touch-off plate, toolsetter Renishaw-style
  - Spindle encoder: differential quadrature, for rigid tapping / CSS
  - Hall effect + magnetic encoder strip kits  
  - Accelerometer-based resonance/vibration sensors (ADXL345 boards)

Key specs: sensing range mm, output type NPN/PNP/hall, supply voltage,
           switching frequency Hz, housing material, IP rating

Usage:
    memory_env/Scripts/python.exe agents/parts_catalog/sensor_harvester.py \
        > agents/parts_catalog/_sensor_log.txt 2>&1
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
log = logging.getLogger("sensor_harvester")

from agents.parts_catalog.search import search_and_extract_json
from agents.parts_catalog.store import (
    write_part,
    download_image,
    upsert_lancedb_embedding,
    load_progress,
    save_progress,
    slug,
)
from agents.parts_catalog.schema import Tier

HARVESTER_NAME = "sensor_harvester"
CATEGORY = "sensors"

DISCOVERY_QUERIES = [
    "CNC endstop micro switch SPDT Omron D2F-L specifications: actuation force, travel, contact rating, dimensions, mounting holes, price per unit",
    "inductive proximity sensor M8 M12 M18 NPN PNP specifications: sensing range mm, supply voltage, output type, switching frequency Hz, IP rating, NC/NO, price",
    "optical endstop slot sensor CNC 3D printer specifications: slot width, output voltage, cable length, supply 5V 12V, dimensions",
    "BL-Touch 3D Touch CR Touch auto bed leveling probe specifications: accuracy mm, repeatability, supply voltage, signal type, compatibility GRBL Klipper Marlin",
    "CNC Z-probe touch plate tool length setter specifications: thickness mm, accuracy, cable type, material, Mach3/GRBL compatibility",
    "Renishaw-style toolsetter automatic tool length sensor CNC specifications: measuring range mm, contact force, repeatability, IP rating, interface",
    "spindle encoder incremental quadrature CNC lathe milling specifications: PPR (pulses per revolution), output differential/single-ended, supply voltage, max RPM, housing type",
    "ADXL345 accelerometer board vibration sensor CNC resonance measurement specifications: range ±g, resolution bits, interface SPI/I2C, Klipper input shaper compatibility",
    "magnetic linear encoder scale strip CNC glass scale specifications: resolution µm, accuracy, supply voltage, output type (TTL/differential), reading head dimensions",
    "inductive probe 36V NPN NC M12 LJ12A3-4-Z/BX specifications and alternatives for CNC steel detection",
]

EXTRACTION_SCHEMA = """
Return a JSON array. Each object (null if unknown):
{
  "brand": "string",
  "model": "string",
  "sensor_type": "string (mechanical_endstop|optical_endstop|inductive_proximity|capacitive_proximity|bl_touch|z_probe_plate|toolsetter|spindle_encoder|linear_encoder|accelerometer|hall_effect)",
  "sensing_range_mm": number,
  "output_type": "string (NPN|PNP|NPN_PNP|hall|analog|digital_5v|differential)",
  "switch_state": "string (NO|NC|changeover)",
  "supply_voltage_min_v": number,
  "supply_voltage_max_v": number,
  "output_voltage_v": number,
  "switching_frequency_hz": number,
  "ip_rating": "string",
  "housing_material": "string",
  "housing_diameter_mm": number,
  "mounting_type": "string (M8|M12|M18|PCB|panel|flange)",
  "accuracy_mm": number,
  "repeatability_mm": number,
  "encoder_ppr": number,
  "encoder_differential": boolean,
  "max_rpm": number,
  "connector_type": "string",
  "cable_length_m": number,
  "tier": "hobby|prosumer|industrial|aerospace",
  "description": "string",
  "datasheet_url": "string",
  "image_url": "string",
  "purchase_urls": [{"supplier": "string", "url": "string", "price_usd": "string"}],
  "tags": ["string"]
}
"""


def run():
    log.info("=== Sensor Harvester starting ===")
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
            try:
                doc_id = slug(
                    CATEGORY, raw.get("brand", "unknown"), raw.get("model", "unknown")
                )
                try:
                    tier = Tier(raw.get("tier", "hobby"))
                except ValueError:
                    tier = Tier.HOBBY
                part_dict = {
                    "doc_id": doc_id,
                    "category": CATEGORY,
                    "name": f"{raw.get('brand', '')} {raw.get('model', '')}".strip(),
                    "brand": raw.get("brand", ""),
                    "model": raw.get("model", ""),
                    "tier": str(tier),
                    "description": raw.get("description", ""),
                    "datasheet_url": raw.get("datasheet_url", ""),
                    "image_url": raw.get("image_url", ""),
                    "image_gcs": None,
                    "purchase_urls": raw.get("purchase_urls", []),
                    "affiliate_tags": {},
                    "tags": raw.get("tags", []),
                    "sensor_type": raw.get("sensor_type"),
                    "sensing_range_mm": raw.get("sensing_range_mm"),
                    "output_type": raw.get("output_type"),
                    "switch_state": raw.get("switch_state"),
                    "supply_voltage_min_v": raw.get("supply_voltage_min_v"),
                    "supply_voltage_max_v": raw.get("supply_voltage_max_v"),
                    "switching_frequency_hz": raw.get("switching_frequency_hz"),
                    "ip_rating": raw.get("ip_rating"),
                    "housing_diameter_mm": raw.get("housing_diameter_mm"),
                    "mounting_type": raw.get("mounting_type"),
                    "accuracy_mm": raw.get("accuracy_mm"),
                    "repeatability_mm": raw.get("repeatability_mm"),
                    "encoder_ppr": raw.get("encoder_ppr"),
                    "max_rpm": raw.get("max_rpm"),
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "source_urls": [],
                }
                if raw.get("image_url"):
                    gcs = download_image(raw["image_url"], CATEGORY, doc_id)
                    if gcs:
                        part_dict["image_gcs"] = gcs
                write_part(part_dict)
                upsert_lancedb_embedding(part_dict)
                written += 1
                total += 1
                log.info(
                    "  Written: %s — type: %s range: %smm acc: %smm",
                    part_dict["name"],
                    raw.get("sensor_type"),
                    raw.get("sensing_range_mm"),
                    raw.get("accuracy_mm"),
                )
            except Exception as e:
                log.warning("Error processing sensor: %s", e)
        log.info("Query done — %d written (total: %d)", written, total)
        completed.add(query)
        save_progress(
            HARVESTER_NAME,
            {"completed_queries": list(completed), "total_written": total},
        )
        time.sleep(3)

    log.info("=== Sensor Harvester complete — total: %d ===", total)


if __name__ == "__main__":
    run()
