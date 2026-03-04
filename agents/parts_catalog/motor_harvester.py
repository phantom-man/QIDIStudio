"""
agents/parts_catalog/motor_harvester.py

Discovers and catalogs stepper motors and servo motors for CNC machines.

Covers:
  - NEMA 8, 11, 14, 17, 23, 24, 34, 42 hybrid stepper motors (1.8° and 0.9° step)
  - Closed-loop steppers / StepServos (integrated encoder + servo driver)
  - AC servo motors (for high-end mills / lathes)
  - Key specs: holding torque, phase current, inductance, rotor inertia, torque curves

Suppliers targeted:
  Stepperonline, OMC (RATTMMOTOR), Automation Technology (ACT), Lin Engineering,
  Nanotec, Leadshine, JMC Motor, Oriental Motor, Kinco, Applied Motion Products

Usage:
    memory_env/Scripts/python.exe agents/parts_catalog/motor_harvester.py \
        > agents/parts_catalog/_motor_log.txt 2>&1
"""

from __future__ import annotations

import json
import logging
import os
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
log = logging.getLogger("motor_harvester")

from agents.parts_catalog.search import (
    gemini_search_json,
    search_and_extract_json,
    gemini_search,
)
from agents.parts_catalog.store import (
    write_part,
    download_image,
    upsert_lancedb_embedding,
    load_progress,
    save_progress,
    slug,
)
from agents.parts_catalog.schema import Motor, MotorType, Tier, TorqueCurvePoint

HARVESTER_NAME = "motor_harvester"
CATEGORY = "motors"

# ── Discovery queries ─────────────────────────────────────────────────────────

DISCOVERY_QUERIES = [
    {
        "query": "complete list of NEMA 17 stepper motors with full specifications table: holding torque, current, inductance, rotor inertia, weight, body length, from Stepperonline, OMC, RATTMMOTOR, Lin Engineering",
        "nema": 17,
        "frame_mm": 42.3,
    },
    {
        "query": "complete list of NEMA 23 stepper motors with full spec table: holding torque Nm, rated current A, inductance mH, rotor inertia gcm2, body length mm — all variants from Stepperonline and Automation Technology",
        "nema": 23,
        "frame_mm": 56.4,
    },
    {
        "query": "complete list of NEMA 34 stepper motors all variants specifications: holding torque, current, inductance, body length, weight — high torque CNC mill versions from Stepperonline, OMC, ACT Motor",
        "nema": 34,
        "frame_mm": 86.3,
    },
    {
        "query": "NEMA 11 and NEMA 14 stepper motor specifications all variants holding torque rated current inductance body length",
        "nema": 11,
        "frame_mm": 28.2,
    },
    {
        "query": "NEMA 42 high torque stepper motor specifications industrial CNC large format",
        "nema": 42,
        "frame_mm": 110.0,
    },
    {
        "query": "closed loop stepper motor StepServo iHSS57 iHSS86 JMC ClearPath specifications: holding torque, encoder PPR, power supply voltage, communication interface",
        "nema": None,
        "frame_mm": None,
    },
    {
        "query": "0.9 degree step angle stepper motors NEMA 17 NEMA 23 high resolution specifications current torque inductance",
        "nema": 17,
        "frame_mm": 42.3,
    },
]

EXTRACTION_SCHEMA = """
Return a JSON array of motor objects. Each object must have these fields (use null if unknown):
{
  "brand": "string",
  "model": "string",
  "nema_size": number,
  "frame_mm": number,
  "body_length_mm": number,
  "step_angle_deg": number,
  "steps_per_rev": number,
  "rated_current_a": number,
  "phase_resistance_ohm": number,
  "phase_inductance_mh": number,
  "holding_torque_nm": number,
  "detent_torque_nm": number,
  "rotor_inertia_gcm2": number,
  "weight_kg": number,
  "shaft_diameter_mm": number,
  "shaft_length_mm": number,
  "wiring": "string (4-wire/6-wire/8-wire)",
  "has_encoder": boolean,
  "encoder_ppr": number,
  "motor_type": "stepper_hybrid|servo_closed_loop_stepper|servo_brushless",
  "tier": "hobby|prosumer|industrial|aerospace",
  "description": "string",
  "datasheet_url": "string",
  "image_url": "string",
  "purchase_urls": [{"supplier": "string", "url": "string", "price_usd": "string"}],
  "tags": ["string"]
}
"""


def process_motor_record(raw: dict) -> Motor | None:
    """Normalise a raw scraped dict into a Motor model."""
    try:
        doc_id = slug(
            CATEGORY,
            raw.get("brand", "unknown"),
            raw.get("model", "unknown"),
        )
        motor_type_str = raw.get("motor_type", "stepper_hybrid")
        try:
            motor_type = MotorType(motor_type_str)
        except ValueError:
            motor_type = MotorType.STEPPER_HYBRID

        tier_str = raw.get("tier", "hobby")
        try:
            tier = Tier(tier_str)
        except ValueError:
            tier = Tier.HOBBY

        motor = Motor(
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
            motor_type=motor_type,
            nema_size=raw.get("nema_size"),
            frame_mm=raw.get("frame_mm"),
            body_length_mm=raw.get("body_length_mm"),
            step_angle_deg=raw.get("step_angle_deg", 1.8),
            steps_per_rev=raw.get("steps_per_rev", 200),
            rated_current_a=raw.get("rated_current_a"),
            phase_resistance_ohm=raw.get("phase_resistance_ohm"),
            phase_inductance_mh=raw.get("phase_inductance_mh"),
            holding_torque_nm=raw.get("holding_torque_nm"),
            detent_torque_nm=raw.get("detent_torque_nm"),
            rotor_inertia_gcm2=raw.get("rotor_inertia_gcm2"),
            weight_kg=raw.get("weight_kg"),
            shaft_diameter_mm=raw.get("shaft_diameter_mm"),
            shaft_length_mm=raw.get("shaft_length_mm"),
            wiring=raw.get("wiring", "4-wire"),
            has_encoder=raw.get("has_encoder", False),
            encoder_ppr=raw.get("encoder_ppr"),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )
        return motor
    except Exception as e:
        log.warning(
            "Failed to build Motor from raw record %s: %s", raw.get("model", "?"), e
        )
        return None


def run():
    log.info("=== Motor Harvester starting ===")
    progress = load_progress(HARVESTER_NAME)
    completed_queries = set(progress.get("completed_queries", []))
    total_written = progress.get("total_written", 0)

    for query_obj in DISCOVERY_QUERIES:
        query = query_obj["query"]
        if query in completed_queries:
            log.info("Skipping already-done query: %.80s...", query)
            continue

        log.info("Searching: %.100s...", query)
        raw_list = search_and_extract_json(
            query=query,
            extraction_instruction=(
                "extract all motor products found with their complete specifications. "
                + EXTRACTION_SCHEMA
            ),
        )

        if not raw_list:
            log.warning("No results for query: %.80s", query)
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
            motor = process_motor_record(raw)
            if motor is None:
                continue

            part_dict = motor.model_dump()

            # Download image if available
            if motor.image_url and not motor.image_gcs:
                gcs_path = download_image(motor.image_url, CATEGORY, motor.doc_id)
                part_dict["image_gcs"] = gcs_path

            write_part(part_dict)
            upsert_lancedb_embedding(part_dict)
            written += 1
            total_written += 1
            log.info(
                "  Written: %s (%s) — torque: %s Nm",
                motor.name,
                motor.doc_id,
                motor.holding_torque_nm,
            )

        log.info(
            "Query complete — %d motors written (total: %d)", written, total_written
        )
        completed_queries.add(query)
        save_progress(
            HARVESTER_NAME,
            {
                "completed_queries": list(completed_queries),
                "total_written": total_written,
            },
        )
        time.sleep(3)  # polite rate limiting

    # Phase 2: torque curve enrichment for high-value motors
    log.info("=== Phase 2: Torque curve enrichment ===")
    torque_targets = [
        "NEMA 23 57HS stepper motor torque curve RPM vs Nm data table all supply voltages 24V 48V",
        "NEMA 34 86HS stepper motor torque speed curve data 48V 72V 80V supply",
        "closed loop StepServo iHSS57 torque speed curve encoder feedback vs open loop",
    ]
    for query in torque_targets:
        log.info("Torque curve search: %.80s...", query)
        result = gemini_search(query)
        if result:
            # Store as raw research note in GCS for later structured enrichment
            from agents.parts_catalog.store import _gcs

            try:
                bucket = _gcs()
                note_name = (
                    f"research_notes/torque_curves/{slug('note', query[:50])}.txt"
                )
                bucket.blob(note_name).upload_from_string(
                    result, content_type="text/plain"
                )
                log.info("Torque curve note stored: %s", note_name)
            except Exception as e:
                log.warning("Could not store torque curve note: %s", e)
        time.sleep(2)

    log.info("=== Motor Harvester complete — total written: %d ===", total_written)


if __name__ == "__main__":
    run()
