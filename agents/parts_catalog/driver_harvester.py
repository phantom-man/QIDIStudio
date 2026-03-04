"""
agents/parts_catalog/driver_harvester.py

Discovers and catalogs stepper motor drivers and servo drives.

Covers:
  - Entry-level: A4988, DRV8825 (Pololu-style modules)
  - Mid-range: TB6600, TB6560, DM542, DM556, DM860H
  - High-current: DMA860S, AM882, DMA860H
  - Trinamic: TMC2208, TMC2209, TMC2130, TMC2226, TMC5160, TMC5161
  - Closed-loop: Leadshine CL57, EM806; JMC iHSS/iSS series
  - AC servo drives: Leadshine ES-D508/1008; Kinco; Delta ASDA

Key specs: input voltage range, max current, microstep table,
           logic input (step/dir vs UART vs SPI), protection features

Usage:
    memory_env/Scripts/python.exe agents/parts_catalog/driver_harvester.py \
        > agents/parts_catalog/_driver_log.txt 2>&1
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
log = logging.getLogger("driver_harvester")

from agents.parts_catalog.search import gemini_search_json, search_and_extract_json
from agents.parts_catalog.store import (
    write_part,
    download_image,
    upsert_lancedb_embedding,
    load_progress,
    save_progress,
    slug,
)
from agents.parts_catalog.schema import Driver, DriverType, Tier

HARVESTER_NAME = "driver_harvester"
CATEGORY = "drivers"

DISCOVERY_QUERIES = [
    "Pololu A4988 DRV8825 stepper driver specifications: input voltage, max current, microstep divisors, logic voltage, package type, price",
    "TB6600 TB6560 stepper motor driver specifications: input voltage range, max current A, microstep settings, step/dir interface, protection features, price USD",
    "DM542 DM556 DM860H Leadshine stepper driver full specifications: voltage range, peak current, microstep table, dimensions, price",
    "DMA860S AM882 DMA860H high voltage stepper driver specifications voltage up to 80V current range microstep table encoder input features",
    "Trinamic TMC2208 TMC2209 TMC2130 TMC2226 TMC5160 stepper driver IC specifications: motor voltage, RMS current, microstepping, interface (UART/SPI), StealthChop SpreadCycle features",
    "Leadshine closed loop stepper driver CL57 EM806 specifications: motor current, encoder input PPR, supply voltage, fault output, communication",
    "JMC iHSS57 iHSS86 integrated closed-loop stepper driver specifications matching motor series, input voltage, control interface",
    "Leadshine ES-D508 ES-D1008 AC servo drive specifications: motor wattage, supply voltage, encoder type, communication (RS232 ModBus), I/O count",
    "Delta ASDA-A2 Kinco AC servo drive specifications: power rating, supply voltage, encoder resolution, bus interface, alarm codes",
    "Gecko G201X G203V G251 stepper driver specifications input voltage current microstepping morphing",
]

EXTRACTION_SCHEMA = """
Return a JSON array of driver objects. Each must have (null if unknown):
{
  "brand": "string",
  "model": "string",
  "driver_type": "stepper_module|stepper_din|servo_closed_loop_stepper|servo_ac_brushless",
  "input_voltage_min_v": number,
  "input_voltage_max_v": number,
  "peak_current_a": number,
  "rms_current_a": number,
  "microstep_divisors": [integer],
  "logic_voltage_v": number,
  "control_interface": "string (step/dir, UART, SPI, RS232, ModBus, EtherCAT)",
  "encoder_input": boolean,
  "max_encoder_ppr": number,
  "has_stealthchop": boolean,
  "has_spreadcycle": boolean,
  "over_current_protection": boolean,
  "over_temp_protection": boolean,
  "short_circuit_protection": boolean,
  "dimensions_mm": "string LxWxH",
  "weight_kg": number,
  "tier": "hobby|prosumer|industrial|aerospace",
  "description": "string",
  "datasheet_url": "string",
  "image_url": "string",
  "purchase_urls": [{"supplier": "string", "url": "string", "price_usd": "string"}],
  "tags": ["string"]
}
"""


def process_driver_record(raw: dict) -> Driver | None:
    try:
        doc_id = slug(
            CATEGORY, raw.get("brand", "unknown"), raw.get("model", "unknown")
        )
        driver_type_str = raw.get("driver_type", "stepper_din")
        try:
            driver_type = DriverType(driver_type_str)
        except ValueError:
            driver_type = DriverType.STEPPER_DIN

        try:
            tier = Tier(raw.get("tier", "hobby"))
        except ValueError:
            tier = Tier.HOBBY

        driver = Driver(
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
            driver_type=driver_type,
            input_voltage_min_v=raw.get("input_voltage_min_v"),
            input_voltage_max_v=raw.get("input_voltage_max_v"),
            peak_current_a=raw.get("peak_current_a"),
            rms_current_a=raw.get("rms_current_a"),
            microstep_divisors=raw.get("microstep_divisors", []),
            logic_voltage_v=raw.get("logic_voltage_v"),
            control_interface=raw.get("control_interface", "step/dir"),
            encoder_input=raw.get("encoder_input", False),
            max_encoder_ppr=raw.get("max_encoder_ppr"),
            has_stealthchop=raw.get("has_stealthchop", False),
            has_spreadcycle=raw.get("has_spreadcycle", False),
            over_current_protection=raw.get("over_current_protection", False),
            over_temp_protection=raw.get("over_temp_protection", False),
            short_circuit_protection=raw.get("short_circuit_protection", False),
            dimensions_mm=raw.get("dimensions_mm"),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )
        return driver
    except Exception as e:
        log.warning(
            "Failed to build Driver from raw: %s — %s", raw.get("model", "?"), e
        )
        return None


def run():
    log.info("=== Driver Harvester starting ===")
    progress = load_progress(HARVESTER_NAME)
    completed_queries = set(progress.get("completed_queries", []))
    total_written = progress.get("total_written", 0)

    for query in DISCOVERY_QUERIES:
        if query in completed_queries:
            log.info("Skipping: %.80s...", query)
            continue

        log.info("Searching: %.100s...", query)
        raw_list = search_and_extract_json(
            query=query, extraction_instruction=EXTRACTION_SCHEMA
        )

        if not raw_list:
            log.warning("No results for: %.80s", query)
            completed_queries.add(query)
            save_progress(
                HARVESTER_NAME,
                {
                    "completed_queries": list(completed_queries),
                    "total_written": total_written,
                },
            )
            time.sleep(2)
            continue

        if isinstance(raw_list, dict):
            raw_list = [raw_list]

        written = 0
        for raw in raw_list:
            if not isinstance(raw, dict):
                continue
            driver = process_driver_record(raw)
            if driver is None:
                continue
            part_dict = driver.model_dump()
            if driver.image_url and not driver.image_gcs:
                part_dict["image_gcs"] = download_image(
                    driver.image_url, CATEGORY, driver.doc_id
                )
            write_part(part_dict)
            upsert_lancedb_embedding(part_dict)
            written += 1
            total_written += 1
            log.info(
                "  Written: %s — %sV max, %sA peak, microsteps: %s",
                driver.name,
                driver.input_voltage_max_v,
                driver.peak_current_a,
                driver.microstep_divisors,
            )

        log.info("Query done — %d written (total: %d)", written, total_written)
        completed_queries.add(query)
        save_progress(
            HARVESTER_NAME,
            {
                "completed_queries": list(completed_queries),
                "total_written": total_written,
            },
        )
        time.sleep(3)

    log.info("=== Driver Harvester complete — total: %d ===", total_written)


if __name__ == "__main__":
    run()
