"""
agents/parts_catalog/rail_harvester.py

Discovers and catalogs linear motion rail/guide systems for CNC machines.

Covers:
  - MGN series (miniature): MGN7, MGN9, MGN12, MGN15, MGN21 — standard and H blocks
  - HGR series (high-load): HGR15, HGR20, HGR25, HGR30, HGR35, HGR45, HGR55
  - SBR series (supported round rail): SBR10, SBR12, SBR16, SBR20, SBR25, SBR30
  - V-slot aluminium extrusion profiles (OpenBuilds): 2020, 2040, 4040, 4080
  - Circular rails / Thomson-style
  - Hiwin, PMI, THK, INA, CPC branded (aerospace grades)
  - Precut lengths, carriages, end stops

Key specs: rail series, width/height mm, carriage block type, load rating N,
           accuracy class, preload class, rail lengths, brand, price per mm

Usage:
    memory_env/Scripts/python.exe agents/parts_catalog/rail_harvester.py \
        > agents/parts_catalog/_rail_log.txt 2>&1
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
log = logging.getLogger("rail_harvester")

from agents.parts_catalog.search import search_and_extract_json
from agents.parts_catalog.store import (
    write_part,
    download_image,
    upsert_lancedb_embedding,
    load_progress,
    save_progress,
    slug,
)
from agents.parts_catalog.schema import Rail, RailType, Tier

HARVESTER_NAME = "rail_harvester"
CATEGORY = "rails"

DISCOVERY_QUERIES = [
    "MGN7 MGN9 MGN12 MGN15 MGN21 linear guide rail specifications: rail width mm, rail height mm, block type (standard/H), static load rating N, dynamic load rating N, accuracy class (C/H/P), available lengths mm, price per 500mm",
    "Hiwin HGR15 HGR20 HGR25 HGR30 HGR35 linear guide rail full specification table: dimensions mm, block options (HGH/HGW flange/square), load ratings, accuracy grade, preload",
    "SBR10 SBR12 SBR16 SBR20 SBR25 SBR30 supported round rail linear motion specifications: shaft diameter mm, load rating N, carriage type (SBR/SAF/SCE), available lengths mm, price",
    "OpenBuilds V-slot 2020 2040 4040 4080 aluminium extrusion profile specifications: width, height, slot size, weight per meter, anodized finish options, T-nut compatibility M5, load rating per span",
    "THK HSR SSR linear guide specifications precision grade accuracy class load ratings dimensions",
    "INA KUSE KUSF linear guide rail specifications dimensions load ratings accuracy class",
    "PMI MSA MSB linear guideway specifications comparison with Hiwin load ratings dimensions",
    "SBR supported round rail shaft chrome plated 8mm 10mm 12mm 16mm 20mm supported linear rail specifications load ratings",
    "miniature linear guide rail 3mm 4mm 5mm 6mm 7mm specifications for small CNC laser engravers",
    "Hiwin MGN rail carriage block types SSE SSS SSC accuracy grade C H P specifications comparison table",
]

EXTRACTION_SCHEMA = """
Return a JSON array. Each object (null if unknown):
{
  "brand": "string",
  "model": "string",
  "rail_type": "string (mgn_miniature|hgr_standard|sbr_supported_round|v_slot_extrusion|circular_shaft|dovetail|box_way)",
  "rail_series": "string (e.g. MGN12, HGR25, SBR20)",
  "rail_width_mm": number,
  "rail_height_mm": number,
  "shaft_diameter_mm": number,
  "block_model": "string",
  "block_type": "string (standard|H|flange|square)",
  "static_load_rating_n": number,
  "dynamic_load_rating_n": number,
  "static_moment_rating_nm": number,
  "accuracy_class": "string (C|H|P|SP|UP)",
  "preload_class": "string (Z0|ZA|ZB|ZC)",
  "max_speed_m_s": number,
  "available_lengths_mm": [number],
  "price_per_500mm_usd": number,
  "tier": "hobby|prosumer|industrial|aerospace",
  "description": "string",
  "datasheet_url": "string",
  "image_url": "string",
  "purchase_urls": [{"supplier": "string", "url": "string", "price_usd": "string"}],
  "tags": ["string"]
}
"""


def process_rail_record(raw: dict) -> Rail | None:
    try:
        doc_id = slug(
            CATEGORY, raw.get("brand", "unknown"), raw.get("model", "unknown")
        )
        rail_type_str = raw.get("rail_type", "mgn_miniature")
        try:
            rail_type = RailType(rail_type_str)
        except ValueError:
            rail_type = RailType.MGN_MINIATURE

        try:
            tier = Tier(raw.get("tier", "hobby"))
        except ValueError:
            tier = Tier.HOBBY

        rail = Rail(
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
            rail_type=rail_type,
            rail_series=raw.get("rail_series"),
            rail_width_mm=raw.get("rail_width_mm"),
            rail_height_mm=raw.get("rail_height_mm"),
            shaft_diameter_mm=raw.get("shaft_diameter_mm"),
            block_model=raw.get("block_model"),
            block_type=raw.get("block_type"),
            static_load_rating_n=raw.get("static_load_rating_n"),
            dynamic_load_rating_n=raw.get("dynamic_load_rating_n"),
            static_moment_rating_nm=raw.get("static_moment_rating_nm"),
            accuracy_class=raw.get("accuracy_class"),
            preload_class=raw.get("preload_class"),
            max_speed_m_s=raw.get("max_speed_m_s"),
            available_lengths_mm=raw.get("available_lengths_mm", []),
            price_per_500mm_usd=raw.get("price_per_500mm_usd"),
            scraped_at=datetime.now(timezone.utc).isoformat(),
        )
        return rail
    except Exception as e:
        log.warning("Failed to build Rail from %s: %s", raw.get("model", "?"), e)
        return None


def run():
    log.info("=== Rail Harvester starting ===")
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
            rail = process_rail_record(raw)
            if rail is None:
                continue
            part_dict = rail.model_dump()
            if rail.image_url and not rail.image_gcs:
                part_dict["image_gcs"] = download_image(
                    rail.image_url, CATEGORY, rail.doc_id
                )
            write_part(part_dict)
            upsert_lancedb_embedding(part_dict)
            written += 1
            total += 1
            log.info(
                "  Written: %s — %s, load: %sN dynamic",
                rail.name,
                rail.rail_series,
                rail.dynamic_load_rating_n,
            )
        log.info("Query done — %d written (total: %d)", written, total)
        completed.add(query)
        save_progress(
            HARVESTER_NAME,
            {"completed_queries": list(completed), "total_written": total},
        )
        time.sleep(3)

    log.info("=== Rail Harvester complete — total: %d ===", total)


if __name__ == "__main__":
    run()
