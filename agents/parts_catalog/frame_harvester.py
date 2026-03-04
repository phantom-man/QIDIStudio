"""
agents/parts_catalog/frame_harvester.py

Discovers and catalogs structural frames and extrusion profiles for CNC machines.

Covers:
  - Aluminium extrusion: 2020, 2040, 2060, 2080, 4040, 4080, 4040 light
    Brands: OpenBuilds, Misumi, 80/20, Motedis, Bosch Rexroth
  - V-slot vs T-slot profiles (OpenBuilds, generic Chinese suppliers)
  - Steel welded frames: cast iron vs welded mild steel for heavy mills
  - Gantry-style router frames: LEAD 1010/1515, WorkBee, Shapeoko, Onefinity
  - Prebuilt frames: LEAD CNC, MakerMade M2, Sphinx, BobsCNC E4
  - Mini mill/lathe bases: LMS 3990, Grizzly G0704 conversion frames
  - Extrusion connectors: corner brackets, L-brackets, T-brackets, drop-in T-nuts

Key specs: profile size mm, slot width mm, weight per meter kg/m,
           moment of inertia, tensile strength, anodizing options

Usage:
    memory_env/Scripts/python.exe agents/parts_catalog/frame_harvester.py \
        > agents/parts_catalog/_frame_log.txt 2>&1
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
log = logging.getLogger("frame_harvester")

from agents.parts_catalog.search import search_and_extract_json
from agents.parts_catalog.store import (
    write_part,
    download_image,
    upsert_lancedb_embedding,
    load_progress,
    save_progress,
    slug,
)
from agents.parts_catalog.schema import Frame, Tier

HARVESTER_NAME = "frame_harvester"
CATEGORY = "frames"

DISCOVERY_QUERIES = [
    "OpenBuilds Misumi aluminium extrusion 2020 2040 2060 4040 4080 specifications: profile size mm, slot width, weight kg/m, tensile strength, moment of inertia, T-nut size, price per meter",
    "V-slot aluminium extrusion 2020 2040 specs: V-groove dimensions, wheel compatibility, load capacity, lengths available, OpenBuilds brand vs generic",
    "80/20 T-slot aluminium extrusion 10 series 15 series specifications comparison with metric 2020 profiles load ratings",
    "Bosch Rexroth aluminium profile 20x20 40x40 45x45 specifications: slot size, weight, moment of inertia, connections, price per meter industrial",
    "LEAD 1010 WorkBee CNC prebuilt aluminium frame kit specifications: work area mm, Z-clearance mm, extrusion sizes, included hardware, price USD",
    "Shapeoko 4 Pro Onefinity Woodworker prebuilt CNC router frame specifications: footprint mm, work area, weight, extrusion/steel construction, accuracy",
    "OpenBuilds C-Beam machine beam specifications: dimensions, static load rating, end plates, gantry plate compatibility",
    "welded steel CNC router frame plans specifications: tube sizes mm wall thickness, weight kg, rigidity vs extrusion comparison",
    "T-nut M5 M6 drop-in sliding T-nut for 2020 4040 extrusion specifications: load rating, pre-assembly vs drop-in, material, price per 100",
    "corner bracket L-bracket 2020 4040 aluminium extrusion frame connector specifications types load ratings",
]

EXTRACTION_SCHEMA = """
Return a JSON array. Each object (null if unknown):
{
  "brand": "string",
  "model": "string",
  "frame_type": "string (extrusion_metric|extrusion_vslot|extrusion_imperial|steel_welded|cast_iron|prebuilt_kit|connector)",
  "profile_width_mm": number,
  "profile_height_mm": number,
  "slot_width_mm": number,
  "weight_per_meter_kg": number,
  "moment_of_inertia_cm4": number,
  "section_modulus_cm3": number,
  "tensile_strength_mpa": number,
  "alloy": "string",
  "anodized": boolean,
  "anodize_color": "string",
  "t_nut_size_m": number,
  "available_lengths_mm": [number],
  "prebuilt_work_area_mm": "string XxYxZ",
  "prebuilt_footprint_mm": "string",
  "prebuilt_weight_kg": number,
  "price_per_meter_usd": number,
  "tier": "hobby|prosumer|industrial|aerospace",
  "description": "string",
  "datasheet_url": "string",
  "image_url": "string",
  "purchase_urls": [{"supplier": "string", "url": "string", "price_usd": "string"}],
  "tags": ["string"]
}
"""


def process_frame_record(raw: dict) -> Frame | None:
    try:
        doc_id = slug(
            CATEGORY, raw.get("brand", "unknown"), raw.get("model", "unknown")
        )
        try:
            tier = Tier(raw.get("tier", "hobby"))
        except ValueError:
            tier = Tier.HOBBY
        frame = Frame(
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
            frame_type=raw.get("frame_type", "extrusion_metric"),
            profile_width_mm=raw.get("profile_width_mm"),
            profile_height_mm=raw.get("profile_height_mm"),
            slot_width_mm=raw.get("slot_width_mm"),
            weight_per_meter_kg=raw.get("weight_per_meter_kg"),
            moment_of_inertia_cm4=raw.get("moment_of_inertia_cm4"),
            section_modulus_cm3=raw.get("section_modulus_cm3"),
            tensile_strength_mpa=raw.get("tensile_strength_mpa"),
            alloy=raw.get("alloy"),
            anodized=raw.get("anodized", True),
            anodize_color=raw.get("anodize_color"),
            t_nut_size_m=raw.get("t_nut_size_m"),
            available_lengths_mm=raw.get("available_lengths_mm", []),
            prebuilt_work_area_mm=raw.get("prebuilt_work_area_mm"),
            prebuilt_footprint_mm=raw.get("prebuilt_footprint_mm"),
            prebuilt_weight_kg=raw.get("prebuilt_weight_kg"),
            price_per_meter_usd=raw.get("price_per_meter_usd"),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )
        return frame
    except Exception as e:
        log.warning("Failed to build Frame from %s: %s", raw.get("model", "?"), e)
        return None


def run():
    log.info("=== Frame Harvester starting ===")
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
            frame = process_frame_record(raw)
            if frame is None:
                continue
            part_dict = frame.model_dump()
            if frame.image_url and not frame.image_gcs:
                part_dict["image_gcs"] = download_image(
                    frame.image_url, CATEGORY, frame.doc_id
                )
            write_part(part_dict)
            upsert_lancedb_embedding(part_dict)
            written += 1
            total += 1
            log.info(
                "  Written: %s — %s x %smm, %s kg/m",
                frame.name,
                frame.profile_width_mm,
                frame.profile_height_mm,
                frame.weight_per_meter_kg,
            )
        log.info("Query done — %d written (total: %d)", written, total)
        completed.add(query)
        save_progress(
            HARVESTER_NAME,
            {"completed_queries": list(completed), "total_written": total},
        )
        time.sleep(3)

    log.info("=== Frame Harvester complete — total: %d ===", total)


if __name__ == "__main__":
    run()
