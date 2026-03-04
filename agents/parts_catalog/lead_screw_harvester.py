"""
agents/parts_catalog/lead_screw_harvester.py

Discovers and catalogs lead screws and ball screws for CNC machines.

Covers:
  - ACME lead screws: TR8×1, TR8×2, TR8×4, TR8×8, TR10, TR12, TR16, TR20
    (Trapezoidal thread, single/multi-start, metric)
  - Ball screws: SFU1204, SFU1605, SFU2005, SFU2020, SFU2505, SFU3205, SFU4005
    (C3/C5/C7/C10 accuracy grades, single/double nut)
  - End bearing support units: BK/BF (fixed/floating), FK/FF (aluminum),
    EK/EF (angular contact)
  - Anti-backlash nuts: POM, brass, T8 ACME anti-backlash spring
  - 8mm × 300/400/500/600/800mm standard lengths + custom

Key specs: lead mm, diameter mm, length mm, accuracy class, C3/C5/C7/C10,
           ball size mm, dynamic load C kN, static load C0 kN, price per m

Usage:
    memory_env/Scripts/python.exe agents/parts_catalog/lead_screw_harvester.py \
        > agents/parts_catalog/_leadscrew_log.txt 2>&1
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
log = logging.getLogger("leadscrew_harvester")

from agents.parts_catalog.search import search_and_extract_json
from agents.parts_catalog.store import (
    write_part,
    download_image,
    upsert_lancedb_embedding,
    load_progress,
    save_progress,
    slug,
)
from agents.parts_catalog.schema import LeadScrew, ScrewType, Tier

HARVESTER_NAME = "lead_screw_harvester"
CATEGORY = "lead_screws"

DISCOVERY_QUERIES = [
    "T8 ACME lead screw TR8x2 TR8x4 TR8x8 specifications: diameter 8mm, pitch mm, lead mm, length options 300-1000mm, material, anti-backlash nut types, price",
    "TR10 TR12 TR16 TR20 ACME trapezoidal lead screw specifications: diameter, pitch, lead, length, efficiency, material stainless or C45 steel, anti-backlash nut options",
    "SFU1204 SFU1605 ball screw full specifications: diameter mm, lead mm, accuracy grade C3/C5/C7/C10, ball size mm, dynamic load rating C kN, static C0 kN, standard lengths, price per 500mm",
    "SFU2005 SFU2020 SFU2505 ball screw specifications accuracy grades dynamic load static load nut dimensions end machining options",
    "SFU3205 SFU4005 heavy duty ball screw specifications for large CNC mill CNC router dynamic load kN dimensions",
    "BK BF FK FF EK EF ball screw end support bearing unit specifications: bore diameter, type (fixed/floating), bearing type, dimensions, load rating, material",
    "ball screw nut SFU1605 double nut single nut specifications: preload class (C3/C5), nut OD, nut length, flange dimensions, ball size",
    "ACME anti-backlash nut T8 T10 T12 specifications: material POM brass, spring preload, radial play, flange dimensions, compatibility",
    "custom length ball screw machining end treatment BK BF support end machining options C3 C5 accuracy grinding",
    "SBR linear rail with lead screw combo set CNC router kit specifications bundle price",
]

EXTRACTION_SCHEMA = """
Return a JSON array. Each object (null if unknown):
{
  "brand": "string",
  "model": "string",
  "screw_type": "string (acme_tr|ball_sfu|ball_custom|rack_gear|belt_drive)",
  "diameter_mm": number,
  "pitch_mm": number,
  "lead_mm": number,
  "starts": number,
  "accuracy_class": "string (C3|C5|C7|C10)",
  "ball_size_mm": number,
  "dynamic_load_kn": number,
  "static_load_kn": number,
  "efficiency_percent": number,
  "standard_lengths_mm": [number],
  "max_length_mm": number,
  "nut_type": "string (single|double|anti-backlash)",
  "nut_material": "string (steel|aluminum|pom|brass)",
  "end_support_unit": "string (BK|BF|FK|FF|EK|EF)",
  "material": "string (C45|stainless|chrome_steel)",
  "tier": "hobby|prosumer|industrial|aerospace",
  "description": "string",
  "datasheet_url": "string",
  "image_url": "string",
  "purchase_urls": [{"supplier": "string", "url": "string", "price_usd": "string"}],
  "tags": ["string"]
}
"""


def process_screw_record(raw: dict) -> LeadScrew | None:
    try:
        doc_id = slug(
            CATEGORY, raw.get("brand", "unknown"), raw.get("model", "unknown")
        )
        screw_type_str = raw.get("screw_type", "acme_tr")
        try:
            screw_type = ScrewType(screw_type_str)
        except ValueError:
            screw_type = ScrewType.ACME_TR

        try:
            tier = Tier(raw.get("tier", "hobby"))
        except ValueError:
            tier = Tier.HOBBY

        screw = LeadScrew(
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
            screw_type=screw_type,
            diameter_mm=raw.get("diameter_mm"),
            pitch_mm=raw.get("pitch_mm"),
            lead_mm=raw.get("lead_mm"),
            starts=raw.get("starts", 1),
            accuracy_class=raw.get("accuracy_class"),
            ball_size_mm=raw.get("ball_size_mm"),
            dynamic_load_kn=raw.get("dynamic_load_kn"),
            static_load_kn=raw.get("static_load_kn"),
            efficiency_percent=raw.get("efficiency_percent"),
            standard_lengths_mm=raw.get("standard_lengths_mm", []),
            max_length_mm=raw.get("max_length_mm"),
            nut_type=raw.get("nut_type"),
            nut_material=raw.get("nut_material"),
            end_support_unit=raw.get("end_support_unit"),
            material=raw.get("material"),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )
        return screw
    except Exception as e:
        log.warning("Failed to build LeadScrew from %s: %s", raw.get("model", "?"), e)
        return None


def run():
    log.info("=== Lead Screw Harvester starting ===")
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
            screw = process_screw_record(raw)
            if screw is None:
                continue
            part_dict = screw.model_dump()
            if screw.image_url and not screw.image_gcs:
                part_dict["image_gcs"] = download_image(
                    screw.image_url, CATEGORY, screw.doc_id
                )
            write_part(part_dict)
            upsert_lancedb_embedding(part_dict)
            written += 1
            total += 1
            log.info(
                "  Written: %s — dia: %smm lead: %smm class: %s",
                screw.name,
                screw.diameter_mm,
                screw.lead_mm,
                screw.accuracy_class,
            )
        log.info("Query done — %d written (total: %d)", written, total)
        completed.add(query)
        save_progress(
            HARVESTER_NAME,
            {"completed_queries": list(completed), "total_written": total},
        )
        time.sleep(3)

    log.info("=== Lead Screw Harvester complete — total: %d ===", total)


if __name__ == "__main__":
    run()
