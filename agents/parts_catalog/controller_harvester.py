"""
agents/parts_catalog/controller_harvester.py

Discovers and catalogs CNC motion controllers and motion control boards.

Covers:
  - GRBL boards: Arduino Uno/Nano clones, Woodpecker 2-axis, CNC Shield V3,
    xPRO V5, BlackBox Motion Controller, GRBL-32 (STM32/ESP32-based)
  - Mach3/Mach4 parallel port + USB: NVUM, NVUM2, UC100, UC300ETH, CSMIO/IP-M,
    CSMIO/IP-A (Mach3 recommended), UC400ETH
  - LinuxCNC Mesa cards: 5i25, 5i24, 7i76, 7i76E, 7i77, 7i92, 7i96
  - Klipper boards: BTT Octopus Pro, BTT Manta M8P, SKR 3,
    Spider v2, Fly Super8 Pro, Fysetc Spider
  - Smoothieboard, Duet 3 6HC, Remora (LinuxCNC over SPI)
  - Industrial: Beckhoff TwinCAT, FANUC/Siemens (for reference)

Key specs: axes supported, step/dir outputs, encoder inputs, spindle control
           (0-10V/PWM/relay), I/O count, communication (USB/Ethernet/parallel),
           microcontroller, supported firmware/software

Usage:
    memory_env/Scripts/python.exe agents/parts_catalog/controller_harvester.py \
        > agents/parts_catalog/_controller_log.txt 2>&1
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
log = logging.getLogger("controller_harvester")

from agents.parts_catalog.search import search_and_extract_json
from agents.parts_catalog.store import (
    write_part,
    download_image,
    upsert_lancedb_embedding,
    load_progress,
    save_progress,
    slug,
)
from agents.parts_catalog.schema import Controller, Tier

HARVESTER_NAME = "controller_harvester"
CATEGORY = "controllers"

DISCOVERY_QUERIES = [
    "GRBL CNC controller board Arduino Uno CNC shield V3 xPRO V5 specifications: axes, step/dir outputs, I/O count, spindle PWM, communication USB, firmware version",
    "Makerbase MKS GRBL + STM32 ESP32 GRBL CNC motion controller board specifications: axes, max step rate, encoder support, Ethernet/WiFi",
    "Mach3 USB CNC motion controller NVUM NVUM2 specifications: axes, step rate kHz, I/O count, spindle 0-10V, encoder input, operating system",
    "Mach4 CNC controller UC300ETH UC400ETH CSMIO/IP-M specifications: axes, I/O, encoder feedback, Ethernet vs USB, realtime kernel requirement",
    "Mesa 5i25 5i24 7i76 7i76E 7i92 7i96 LinuxCNC FPGA motion controller specifications: FPGA chip, axes, step/dir outputs, encoder inputs, I/O count, I/O voltage, connection type",
    "BTT Octopus Pro BTT Manta M8P Klipper 3D printer / CNC controller board specifications: axes (stepper sockets), MCU, TMC driver support, input voltage, output current, USB/Ethernet",
    "Duet 3 6HC Duet 3 Mini specifications: axes, motor driver integrated/external, encoder support, expansion, Ethernet/USB/WiFi, RepRapFirmware",
    "Smoothieboard 5X CNC controller specifications: axes, integrated drivers, max current, SD card, Ethernet, community",
    "Remora LinuxCNC external step generator SPI interface Raspberry Pi specifications compatibility boards",
    "Ruida RDC6445 RDC6442 DSP laser CNC controller specifications: axes, PWM spindle control, I/O, display, G-code compatibility",
    "FluidNC ESP32 CNC controller DLC32 GRBL_ESP32 WiFi specifications axes IO spindle",
]

EXTRACTION_SCHEMA = """
Return a JSON array. Each object (null if unknown):
{
  "brand": "string",
  "model": "string",
  "firmware": "string (GRBL|Mach3|Mach4|LinuxCNC|Klipper|RRF|Smoothie|FluidNC|Marlin|proprietary)",
  "mcu": "string (e.g. ATmega328|STM32F4|ESP32|FPGA|Cortex-M7)",
  "axes": number,
  "max_step_rate_khz": number,
  "step_dir_outputs": number,
  "encoder_inputs": number,
  "digital_inputs": number,
  "digital_outputs": number,
  "analog_inputs": number,
  "spindle_control": "string (PWM|0-10V|relay|DAC)",
  "spindle_pwm_hz": number,
  "communication": ["string (USB|Ethernet|WiFi|parallel|SPI|CAN)"],
  "realtime_required": boolean,
  "driver_sockets": number,
  "integrated_drivers": boolean,
  "max_driver_current_a": number,
  "input_voltage_v": number,
  "dimensions_mm": "string",
  "tier": "hobby|prosumer|industrial|aerospace",
  "description": "string",
  "datasheet_url": "string",
  "image_url": "string",
  "purchase_urls": [{"supplier": "string", "url": "string", "price_usd": "string"}],
  "tags": ["string"]
}
"""


def process_controller_record(raw: dict) -> Controller | None:
    try:
        doc_id = slug(
            CATEGORY, raw.get("brand", "unknown"), raw.get("model", "unknown")
        )
        try:
            tier = Tier(raw.get("tier", "hobby"))
        except ValueError:
            tier = Tier.HOBBY
        ctrl = Controller(
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
            firmware=raw.get("firmware"),
            mcu=raw.get("mcu"),
            axes=raw.get("axes"),
            max_step_rate_khz=raw.get("max_step_rate_khz"),
            step_dir_outputs=raw.get("step_dir_outputs"),
            encoder_inputs=raw.get("encoder_inputs"),
            digital_inputs=raw.get("digital_inputs"),
            digital_outputs=raw.get("digital_outputs"),
            analog_inputs=raw.get("analog_inputs"),
            spindle_control=raw.get("spindle_control"),
            spindle_pwm_hz=raw.get("spindle_pwm_hz"),
            communication=raw.get("communication", []),
            realtime_required=raw.get("realtime_required", False),
            driver_sockets=raw.get("driver_sockets"),
            integrated_drivers=raw.get("integrated_drivers", False),
            max_driver_current_a=raw.get("max_driver_current_a"),
            input_voltage_v=raw.get("input_voltage_v"),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )
        return ctrl
    except Exception as e:
        log.warning("Failed to build Controller from %s: %s", raw.get("model", "?"), e)
        return None


def run():
    log.info("=== Controller Harvester starting ===")
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
            ctrl = process_controller_record(raw)
            if ctrl is None:
                continue
            part_dict = ctrl.model_dump()
            if ctrl.image_url and not ctrl.image_gcs:
                part_dict["image_gcs"] = download_image(
                    ctrl.image_url, CATEGORY, ctrl.doc_id
                )
            write_part(part_dict)
            upsert_lancedb_embedding(part_dict)
            written += 1
            total += 1
            log.info(
                "  Written: %s — firmware: %s, axes: %s, step rate: %s kHz",
                ctrl.name,
                ctrl.firmware,
                ctrl.axes,
                ctrl.max_step_rate_khz,
            )
        log.info("Query done — %d written (total: %d)", written, total)
        completed.add(query)
        save_progress(
            HARVESTER_NAME,
            {"completed_queries": list(completed), "total_written": total},
        )
        time.sleep(3)

    log.info("=== Controller Harvester complete — total: %d ===", total)


if __name__ == "__main__":
    run()
