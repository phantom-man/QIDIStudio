"""
agents/parts_catalog/coupler_harvester.py

Discovers and catalogs shaft couplers, anti-backlash components, and
bearing support hardware for CNC machines.

Covers:
  - Shaft couplers: rigid/jaw (spider)/oldham/bellows/disc/beam (helical)
  - End bearing support: BK/BF fixed+floating sets, FK/FF aluminum, EK/EF
  - Anti-backlash nuts: T8 ACME spring-loaded POM, brass split-nut
  - Motor end plates (NEMA 17/23/34 to linear axis mounting plates)
  - Shaft collars: single/double split set-screw
  - Flexible couplings: stepper to lead screw 5mm→8mm, 6.35mm→8mm, 8mm→8mm

Key specs: bore diameters mm, OD mm, length mm, material, max torque Nm,
           max RPM, angular misalignment tolerance degrees, type

Usage:
    memory_env/Scripts/python.exe agents/parts_catalog/coupler_harvester.py \
        > agents/parts_catalog/_coupler_log.txt 2>&1
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
log = logging.getLogger("coupler_harvester")

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

HARVESTER_NAME = "coupler_harvester"
CATEGORY = "couplers"

DISCOVERY_QUERIES = [
    "flexible shaft coupler CNC stepper motor 5mm 6.35mm 8mm 10mm 12mm bore sizes specifications: types jaw/helical beam/oldham/bellows, OD mm, length mm, max torque Nm, angular misalignment degrees, material, price",
    "rigid shaft coupling 8mm 10mm 12mm specifications: OD mm, length mm, max torque Nm, material alum/steel, set screw vs clamp type",
    "jaw coupling spider coupler insert polyurethane specifications: shore hardness, bore sizes, torque rating, color coding for hardness",
    "BK10 BF10 BK12 BF12 BK15 BF15 BK20 BF20 ball screw end support bearing unit full specifications: bore diameter, bearing type 7000C/7200C, dimensions, load rating",
    "FK10 FF10 FK12 FF12 FK15 FF15 FK20 FF20 aluminum fixed floating support unit specifications: bore diameter, dimensions, price",
    "EK10 EF10 EK12 EF12 EK15 EF15 EK20 EF20 angular contact ball screw support specifications",
    "NEMA 17 NEMA 23 NEMA 34 motor mount plate CNC linear axis specifications: compatibility, hole pattern, material aluminum, dimensions",
    "shaft collar split set screw stepper motor 5mm 8mm 10mm 12mm specifications: OD, width, tightening torque, material",
    "T8 anti-backlash nut specifications: spring loaded, POM vs brass, flange dimensions, thread specification, spring preload force",
    "oldham coupling CNC servo motor specifications: bore sizes, OD, hub material, center disc material, max speed, backlash-free",
]

EXTRACTION_SCHEMA = """
Return a JSON array. Each object (null if unknown):
{
  "brand": "string",
  "model": "string",
  "coupler_type": "string (rigid|jaw_spider|oldham|bellows|beam_helical|disc|end_support_bk|end_support_fk|shaft_collar|motor_mount|anti_backlash_nut)",
  "bore_1_mm": number,
  "bore_2_mm": number,
  "od_mm": number,
  "length_mm": number,
  "max_torque_nm": number,
  "max_rpm": number,
  "angular_misalignment_deg": number,
  "axial_misalignment_mm": number,
  "material": "string",
  "spider_hardness_shore": number,
  "bearing_type": "string",
  "bearing_count": number,
  "supported_shaft_diameter_mm": number,
  "tier": "hobby|prosumer|industrial|aerospace",
  "description": "string",
  "datasheet_url": "string",
  "image_url": "string",
  "purchase_urls": [{"supplier": "string", "url": "string", "price_usd": "string"}],
  "tags": ["string"]
}
"""


def run():
    log.info("=== Coupler Harvester starting ===")
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
                    "coupler_type": raw.get("coupler_type", "rigid"),
                    "bore_1_mm": raw.get("bore_1_mm"),
                    "bore_2_mm": raw.get("bore_2_mm"),
                    "od_mm": raw.get("od_mm"),
                    "length_mm": raw.get("length_mm"),
                    "max_torque_nm": raw.get("max_torque_nm"),
                    "max_rpm": raw.get("max_rpm"),
                    "angular_misalignment_deg": raw.get("angular_misalignment_deg"),
                    "material": raw.get("material"),
                    "bearing_type": raw.get("bearing_type"),
                    "supported_shaft_diameter_mm": raw.get(
                        "supported_shaft_diameter_mm"
                    ),
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
                    "  Written: %s bore: %s/%s mm, torque: %s Nm",
                    part_dict["name"],
                    raw.get("bore_1_mm"),
                    raw.get("bore_2_mm"),
                    raw.get("max_torque_nm"),
                )
            except Exception as e:
                log.warning("Error processing coupler: %s", e)
        log.info("Query done — %d written (total: %d)", written, total)
        completed.add(query)
        save_progress(
            HARVESTER_NAME,
            {"completed_queries": list(completed), "total_written": total},
        )
        time.sleep(3)

    log.info("=== Coupler Harvester complete — total: %d ===", total)


if __name__ == "__main__":
    run()
