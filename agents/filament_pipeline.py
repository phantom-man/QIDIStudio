"""
agents/filament_pipeline.py — Background Filament Database Research Pipeline.

Discovers all major filament brands + every material they make, then extracts
full print-settings information for each. Persists everything to:

  Firestore  : brands/{brand_id}/materials/{material_id}  (structured, queryable)
  GCS        : gs://qidistudio-filaments/raw/{brand}/{material}.json  (full scraped dump)
  BigQuery   : qidistudio_research.raw_filament_scrapes  (append-only audit trail)
  Cloud SQL  : filament_manufacturers + filaments  (structured, validated)
  LanceDB    : qidistudio_filaments table  (semantic search over descriptions)

Progress checkpoint: gs://qidistudio-filaments/_progress/filament_pipeline.json
  → Allows safe resume if the run is interrupted.

Usage (background)::

    memory_env/Scripts/python.exe agents/filament_pipeline.py > agents/_filament_log.txt 2>&1
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import traceback
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[1]
load_dotenv(REPO_ROOT / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("filament_pipeline")

# ── Lazy imports (heavy deps — only load once env is set) ─────────────────────


def _import_tavily():
    from tavily import TavilyClient  # type: ignore

    return TavilyClient(api_key=os.environ["TAVILY_API_KEY"])


def _import_gemini():
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0.1,
    )


def _import_firestore():
    from google.cloud import firestore  # type: ignore

    return firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])


def _import_gcs():
    from google.cloud import storage  # type: ignore

    client = storage.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])
    bucket = client.bucket("qidistudio-filaments")
    # Create bucket if it doesn't exist
    try:
        bucket.reload()
    except Exception:
        bucket = client.create_bucket(
            "qidistudio-filaments",
            location="us-central1",
        )
        log.info("Created GCS bucket qidistudio-filaments")
    return client, bucket


# ── Brand seed list ───────────────────────────────────────────────────────────
# Starting set — the researcher will also discover additional brands via web search.

SEED_BRANDS = [
    "Bambu Lab",
    "Prusament (Prusa Research)",
    "eSUN",
    "Polymaker",
    "Hatchbox",
    "Overture",
    "Sunlu",
    "3DFuel",
    "Colorfabb",
    "Fillamentum",
    "FormFutura",
    "iSANMATE",
    "Matterhackers",
    "Protopasta",
    "Siraya Tech",
    "PolyLite",
    "Raise3D",
    "Ultimaker (UltiMaker)",
    "BASF Forward AM",
    "Fiberlogy",
    "Devil Design",
    "NovaMaker",
    "Eryone",
    "Elegoo",
    "Creality",
    "Kingroon",
    "Amolen",
    "Duramic 3D",
    "IEMAI",
    "Reprapper",
    "Ankermake",
    "Flashforge",
    "BV3D",
    "3DJAKE",
    "Das Filament",
    "Real Filament",
    "Extrudr",
    "Verbatim",
    "Spectrum",
    "GreenGate3D",
    "Taulman3D",
    "Nylon X (Markforged)",
    "PolyMax",
    "ColorFabb PA",
    "Ninjaflex (NinjaTek)",
    "TPU-87A",
    "Sainsmart",
    "PETG CF",
]

# ── Settings schema (what we want for every material) ────────────────────────

SETTINGS_SCHEMA = {
    "nozzle_temp_min": None,
    "nozzle_temp_max": None,
    "nozzle_temp_recommended": None,
    "bed_temp_min": None,
    "bed_temp_max": None,
    "bed_temp_recommended": None,
    "bed_temp_pei": None,
    "bed_temp_glass": None,
    "bed_temp_garolite": None,
    "chamber_temp_min": None,
    "chamber_temp_max": None,
    "chamber_temp_recommended": None,
    "print_speed_min": None,
    "print_speed_max": None,
    "print_speed_recommended": None,
    "cooling_fan_min": None,
    "cooling_fan_max": None,
    "cooling_fan_recommended": None,
    "requires_enclosure": None,
    "requires_dry_storage": None,
    "drying_temp": None,
    "drying_time_hours": None,
    "retraction_distance_bowden": None,
    "retraction_distance_direct": None,
    "retraction_speed": None,
    "flow_rate": None,
    "line_width_multiplier": None,
    "layer_height_min": None,
    "layer_height_max": None,
    "supports_soluble_interface": None,
    "chemical_resistance": None,
    "uv_resistance": None,
    "food_safe": None,
    "flexible": None,
    "shrinkage_percent": None,
    "density_g_cm3": None,
    "tensile_strength_mpa": None,
    "impact_strength_kj_m2": None,
    "heat_deflection_temp_c": None,
    "glass_transition_temp_c": None,
    "moisture_absorption_percent": None,
    "bed_adhesion_notes": None,
    "common_challenges": None,
    "post_processing_notes": None,
    "typical_use_cases": None,
    "incompatible_with": None,
    "works_well_with": None,  # multi-material combos
}

# ── Utility ───────────────────────────────────────────────────────────────────


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "_", text).strip("_")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── GCS checkpoint helpers ────────────────────────────────────────────────────

CHECKPOINT_KEY = "_progress/filament_pipeline.json"


def load_checkpoint(bucket) -> dict:
    try:
        blob = bucket.blob(CHECKPOINT_KEY)
        data = json.loads(blob.download_as_text())
        log.info(
            f"Resuming from checkpoint: {len(data.get('completed_brands', []))} brands done"
        )
        return data
    except Exception:
        return {
            "completed_brands": [],
            "discovered_brands": [],
            "started_at": now_iso(),
        }


def save_checkpoint(bucket, state: dict):
    try:
        blob = bucket.blob(CHECKPOINT_KEY)
        blob.upload_from_string(
            json.dumps(state, indent=2), content_type="application/json"
        )
    except Exception as e:
        log.warning(f"Checkpoint save failed: {e}")


# ── AI extraction helpers ─────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are an expert 3D printing materials scientist. 

Given the following search results about a filament material, extract ALL available print settings into a structured JSON object.

Brand: {brand}
Material: {material}
Material type: {material_type}

Search results:
{search_results}

Return ONLY a JSON object with these exact keys (use null for unknown values):
- nozzle_temp_min, nozzle_temp_max, nozzle_temp_recommended (integers, Celsius)  
- bed_temp_min, bed_temp_max, bed_temp_recommended (integers, Celsius)
- bed_temp_pei, bed_temp_glass, bed_temp_garolite (integers, Celsius — null if unknown)
- chamber_temp_min, chamber_temp_max, chamber_temp_recommended (integers, Celsius — null if no chamber needed)
- print_speed_min, print_speed_max, print_speed_recommended (integers, mm/s)
- cooling_fan_min, cooling_fan_max, cooling_fan_recommended (integers, 0-100 percent)
- requires_enclosure (boolean)
- requires_dry_storage (boolean)
- drying_temp (integer, Celsius)
- drying_time_hours (number)
- retraction_distance_bowden, retraction_distance_direct (number, mm)
- retraction_speed (integer, mm/s)
- flow_rate (number, 0.8-1.2 typical)
- layer_height_min, layer_height_max (number, mm)
- shrinkage_percent (number)
- density_g_cm3 (number)
- tensile_strength_mpa (number)
- heat_deflection_temp_c (number)
- glass_transition_temp_c (number)
- moisture_absorption_percent (number)
- food_safe (boolean)
- flexible (boolean)
- uv_resistance (string: "poor"/"fair"/"good"/"excellent" or null)
- chemical_resistance (string: "poor"/"fair"/"good"/"excellent" or null)
- bed_adhesion_notes (string — brief)
- common_challenges (string — brief)
- post_processing_notes (string — brief)
- typical_use_cases (list of strings)
- incompatible_with (list of material types)
- works_well_with (list of material types — for multi-material)

IMPORTANT: Return ONLY the JSON object, no markdown, no explanation.
"""

BRAND_DISCOVERY_PROMPT = """You are an expert in 3D printing filament manufacturers.

Based on your knowledge and the search results below, list ALL filament brands/manufacturers 
you can identify. Include both major international brands AND specialty/regional brands.

Search results:
{search_results}

Return ONLY a JSON array of brand names (strings), like:
["Brand A", "Brand B", "Brand C"]

Include the brands already known to me: {known_brands}

Return ALL brands you can identify. Be comprehensive.
"""

MATERIAL_DISCOVERY_PROMPT = """You are an expert in 3D printing filaments.

List ALL filament products/materials made by: {brand}

Search results about this brand:
{search_results}

Return ONLY a JSON array of objects, each with:
- "name": product name (string)
- "material_type": base material (string): PLA, PETG, ABS, ASA, TPU, PC, PA/Nylon, PVA, HIPS, PP, PEI/PEEK/PEKK, CF composites, GF composites, Wood fills, Metal fills, Flex, etc.
- "description": one sentence description (string)
- "diameter_options": list of available diameters in mm (list of floats)
- "url": product page URL if found in search results (string or null)

Return ONLY the JSON array.
"""

AMAZON_BRAND_DISCOVERY_PROMPT = """You are an expert in 3D printing filament brands that sell on Amazon.

Below are search results from queries about best-rated filament brands on Amazon USA.

Search results:
{search_results}

Identify all filament manufacturers / brands mentioned in the results that:
1. Sell 3D printing filament on Amazon USA
2. Have an average customer rating of at least 3.5 stars (when mentioned)
3. Are legitimate filament manufacturers (not re-sellers of unknown origin)

For each brand, if rating is mentioned extract it; otherwise assume it qualifies.
Return ONLY a JSON array of objects:
[
  {{"brand": "Brand Name", "amazon_rating": 4.6, "amazon_asin_or_url": "...", "product_example": "..."}},
  ...
]

If no rating is specifically mentioned for a brand, include it with amazon_rating: null.
Return AT LEAST 20 entries. Be comprehensive — include every brand you can find.
Return ONLY the JSON array.
"""


def extract_json(text: str) -> Any:
    """Extract JSON from LLM response (handles markdown code blocks)."""
    text = text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array or object within the text
        for pat in (r"\[.*\]", r"\{.*\}"):
            m = re.search(pat, text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except Exception:
                    pass
    return None


# ── Core research functions ───────────────────────────────────────────────────


def discover_brands(tavily, llm, seed_brands: list[str]) -> list[str]:
    """Web search + LLM to discover all filament brands."""
    log.info("Discovering filament brands via web search...")

    queries = [
        "complete list all 3D printing filament brands manufacturers 2024 2025",
        "best 3D printing filament companies brands reviews comparison",
        "specialty 3D printing filament manufacturers engineering materials",
        "budget 3D printing filament brands Amazon marketplace",
        "European 3D printing filament brands manufacturers",
        "carbon fiber PEEK nylon 3D printing filament manufacturers",
    ]

    all_results = []
    for q in queries:
        try:
            results = tavily.search(q, max_results=10, search_depth="basic")
            for r in results.get("results", []):
                all_results.append(
                    f"URL: {r.get('url','')}\nTitle: {r.get('title','')}\nContent: {r.get('content','')[:500]}"
                )
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Search failed for '{q}': {e}")

    combined = "\n\n---\n\n".join(all_results[:20])
    known = json.dumps(seed_brands[:20])

    response = llm.invoke(
        BRAND_DISCOVERY_PROMPT.format(search_results=combined, known_brands=known)
    )
    discovered = extract_json(response.content)

    if isinstance(discovered, list):
        all_brands = list(
            set(seed_brands + [b for b in discovered if isinstance(b, str)])
        )
        log.info(f"Total brands to research: {len(all_brands)}")
        return all_brands
    return seed_brands


def amazon_discover_brands(tavily, llm, min_rating: float = 3.5) -> list[str]:
    """
    Supplement SEED_BRANDS with filament brands found on Amazon that have
    >= min_rating average customer rating.

    Uses Tavily to fetch Amazon search results / review roundups, then uses the
    LLM to extract brand names.  Returns a deduplicated list of brand name strings.
    """
    log.info("Amazon brand discovery — searching for highly-rated filament brands...")

    queries = [
        "best rated 3D printer filament brands Amazon USA site:amazon.com OR site:rtings.com OR site:all3dp.com 4 stars",
        "top 3D printing filament Amazon best sellers customer rating 2024 2025",
        "amazon 3D printing filament brand comparison reviews highest rated",
        "buy 3D printing filament Amazon top brands PLA PETG ABS reviews",
        "best 3D printing filament value quality Amazon customer reviews 2025",
    ]

    all_results: list[str] = []
    for q in queries:
        try:
            results = tavily.search(q, max_results=10, search_depth="advanced")
            for r in results.get("results", []):
                snippet = (
                    f"URL: {r.get('url', '')}\n"
                    f"Title: {r.get('title', '')}\n"
                    f"Content: {r.get('content', '')[:800]}"
                )
                all_results.append(snippet)
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Amazon search failed for '{q[:50]}': {e}")

    if not all_results:
        log.warning("Amazon discovery: no search results — skipping")
        return []

    combined = "\n\n---\n\n".join(all_results[:25])
    response = llm.invoke(AMAZON_BRAND_DISCOVERY_PROMPT.format(search_results=combined))
    discovered = extract_json(response.content)

    brand_names: list[str] = []
    if isinstance(discovered, list):
        for entry in discovered:
            if isinstance(entry, dict):
                brand = entry.get("brand")
                rating = entry.get("amazon_rating")
                # Include if rating unknown or meets threshold
                if brand and (rating is None or rating >= min_rating):
                    brand_names.append(brand)
            elif isinstance(entry, str):
                brand_names.append(entry)

    log.info(f"Amazon discovery: found {len(brand_names)} brands meeting >= {min_rating}★")
    return brand_names


def discover_materials(tavily, llm, brand: str) -> list[dict]:
    """Discover all filament products for a given brand."""
    queries = [
        f"{brand} filament complete product line all materials types",
        f"{brand} 3D printing filament catalog specifications",
        f"site:{brand.lower().replace(' ', '')}.com filament",
    ]

    all_results = []
    for q in queries[:2]:
        try:
            results = tavily.search(q, max_results=8, search_depth="basic")
            for r in results.get("results", []):
                all_results.append(
                    f"URL: {r.get('url','')}\nTitle: {r.get('title','')}\nContent: {r.get('content','')[:600]}"
                )
            time.sleep(0.3)
        except Exception as e:
            log.warning(f"  Material search failed for '{q}': {e}")

    if not all_results:
        return []

    combined = "\n\n---\n\n".join(all_results[:12])
    response = llm.invoke(
        MATERIAL_DISCOVERY_PROMPT.format(brand=brand, search_results=combined)
    )
    materials = extract_json(response.content)
    if isinstance(materials, list):
        return [m for m in materials if isinstance(m, dict) and "name" in m]
    return []


def research_material_settings(tavily, llm, brand: str, material: dict) -> dict:
    """Research print settings for a specific material."""
    mat_name = material.get("name", "")
    mat_type = material.get("material_type", "")

    queries = [
        f"{brand} {mat_name} print settings temperature speed cooling",
        f"{brand} {mat_name} optimal slicer settings profile",
        f"{mat_type} filament print settings temperature bed speed 2024",
    ]

    all_results = []
    for q in queries[:2]:
        try:
            results = tavily.search(q, max_results=8, search_depth="advanced")
            for r in results.get("results", []):
                all_results.append(
                    f"URL: {r.get('url','')}\nTitle: {r.get('title','')}\nContent: {r.get('content','')[:800]}"
                )
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"    Settings search failed: {e}")

    if not all_results:
        return {}

    combined = "\n\n---\n\n".join(all_results[:10])
    response = llm.invoke(
        EXTRACTION_PROMPT.format(
            brand=brand,
            material=mat_name,
            material_type=mat_type,
            search_results=combined,
        )
    )
    settings = extract_json(response.content)
    if isinstance(settings, dict):
        return settings
    return {}


# ── Firestore writer ──────────────────────────────────────────────────────────


def write_to_firestore(db, brand: str, brand_slug: str, material: dict, settings: dict):
    """Write brand + material + settings to Firestore."""
    try:
        brand_ref = db.collection("filaments").document(brand_slug)
        brand_ref.set(
            {
                "name": brand,
                "slug": brand_slug,
                "updated_at": now_iso(),
            },
            merge=True,
        )

        mat_slug = slugify(material.get("name", "unknown"))
        mat_ref = brand_ref.collection("materials").document(mat_slug)
        mat_ref.set(
            {
                **material,
                "brand": brand,
                "brand_slug": brand_slug,
                "settings": settings,
                "updated_at": now_iso(),
            }
        )
        log.info(f"    [Firestore] {brand_slug}/{mat_slug} written")
    except Exception as e:
        log.error(f"    [Firestore] write failed: {e}")


# ── GCS raw dump writer ───────────────────────────────────────────────────────


def write_to_gcs(
    bucket, brand_slug: str, material: dict, settings: dict, raw_data: dict
):
    """Write raw data dump to GCS."""
    try:
        mat_slug = slugify(material.get("name", "unknown"))
        key = f"raw/{brand_slug}/{mat_slug}.json"
        payload = {
            "material": material,
            "settings": settings,
            "raw": raw_data,
            "updated_at": now_iso(),
        }
        bucket.blob(key).upload_from_string(
            json.dumps(payload, indent=2), content_type="application/json"
        )
    except Exception as e:
        log.warning(f"    [GCS] write failed: {e}")


# ── BigQuery writer ───────────────────────────────────────────────────────────


def write_to_bigquery(brand: str, brand_slug: str, material: dict, settings: dict, run_id: str):
    """Append raw filament scrape record to BigQuery (fire-and-forget, non-fatal)."""
    import asyncio

    async def _write():
        try:
            from services.db.bigquery_client import BigQueryClient
            bq = BigQueryClient()
            scrape = {
                "manufacturer_name": brand,
                "manufacturer_slug": brand_slug,
                "product_name": material.get("name", ""),
                "product_slug": slugify(material.get("name", "unknown")),
                "category": material.get("material_type"),
                "source_url": material.get("url"),
                "source_type": "web",
                "raw_data": {**material, **settings},
                "normalized_data": settings,
                "confidence": 0.7,
            }
            await bq.write_filament_scrape(scrape, run_id=run_id)
        except Exception as e:
            log.warning(f"    [BigQuery] write failed (non-fatal): {e}")

    try:
        asyncio.run(_write())
    except Exception as e:
        log.warning(f"    [BigQuery] async error (non-fatal): {e}")


# ── Cloud SQL writer ──────────────────────────────────────────────────────────


def write_to_cloud_sql(brand: str, brand_slug: str, material: dict, settings: dict):
    """Upsert filament manufacturer + filament into Cloud SQL (non-fatal)."""
    import asyncio

    async def _upsert():
        try:
            from services.db.cloud_sql import get_session, upsert_filament, upsert_manufacturer
            from services.db.models import FilamentCategory

            # Normalise category to enum value
            raw_cat = (material.get("material_type") or "PLA").upper().replace(" ", "_")
            # Best-effort mapping
            cat_map = {
                "PA_NYLON": "PA", "NYLON": "PA", "CF": "PLA_CF",
                "GF": "PLA_CF", "FLEXIBLE": "FLEX", "SILK_PLA": "SILK",
                "MATTE_PLA": "MATTE",
            }
            cat = cat_map.get(raw_cat, raw_cat)
            try:
                FilamentCategory(cat)
            except ValueError:
                cat = "OTHER"

            async with get_session() as session:
                mfr_data = {
                    "slug": brand_slug,
                    "name": brand,
                    "data_tier": "free",
                    "research_status": "draft",
                }
                mfr = await upsert_manufacturer(session, mfr_data)

                filament_data = {
                    "manufacturer_id": mfr.id,
                    "slug": slugify(material.get("name", "unknown")),
                    "product_name": material.get("name", ""),
                    "category": cat,
                    "diameter_mm": (material.get("diameter_options") or [1.75])[0],
                    "source_url": material.get("url"),
                    "nozzle_temp_min_c": settings.get("nozzle_temp_min"),
                    "nozzle_temp_max_c": settings.get("nozzle_temp_max"),
                    "nozzle_temp_rec_c": settings.get("nozzle_temp_recommended"),
                    "bed_temp_min_c": settings.get("bed_temp_min"),
                    "bed_temp_max_c": settings.get("bed_temp_max"),
                    "bed_temp_rec_c": settings.get("bed_temp_recommended"),
                    "bed_temp_pei_c": settings.get("bed_temp_pei"),
                    "bed_temp_glass_c": settings.get("bed_temp_glass"),
                    "bed_temp_garolite_c": settings.get("bed_temp_garolite"),
                    "chamber_temp_min_c": settings.get("chamber_temp_min"),
                    "chamber_temp_max_c": settings.get("chamber_temp_max"),
                    "chamber_temp_rec_c": settings.get("chamber_temp_recommended"),
                    "print_speed_min_mms": settings.get("print_speed_min"),
                    "print_speed_max_mms": settings.get("print_speed_max"),
                    "print_speed_rec_mms": settings.get("print_speed_recommended"),
                    "cooling_fan_min_pct": settings.get("cooling_fan_min"),
                    "cooling_fan_max_pct": settings.get("cooling_fan_max"),
                    "cooling_fan_rec_pct": settings.get("cooling_fan_recommended"),
                    "retraction_bowden_mm": settings.get("retraction_distance_bowden"),
                    "retraction_direct_mm": settings.get("retraction_distance_direct"),
                    "retraction_speed_mms": settings.get("retraction_speed"),
                    "flow_rate_pct": (settings.get("flow_rate") or 1.0) * 100,
                    "requires_enclosure": settings.get("requires_enclosure"),
                    "requires_dry_box": settings.get("requires_dry_storage"),
                    "drying_temp_c": settings.get("drying_temp"),
                    "drying_time_hours": settings.get("drying_time_hours"),
                    "food_safe": settings.get("food_safe"),
                    "flexible": settings.get("flexible"),
                    "uv_resistant": settings.get("uv_resistance") in ("good", "excellent"),
                    "density_g_cm3": settings.get("density_g_cm3"),
                    "tensile_strength_mpa": settings.get("tensile_strength_mpa"),
                    "glass_transition_temp_c": settings.get("glass_transition_temp_c"),
                    "heat_deflection_temp_c": settings.get("heat_deflection_temp_c"),
                    "moisture_absorption_pct": settings.get("moisture_absorption_percent"),
                    "shrinkage_pct": settings.get("shrinkage_percent"),
                    "bed_adhesion_notes": settings.get("bed_adhesion_notes"),
                    "common_challenges": settings.get("common_challenges"),
                    "post_processing_notes": settings.get("post_processing_notes"),
                    "typical_use_cases": ", ".join(settings.get("typical_use_cases") or []) or None,
                    "incompatible_with": settings.get("incompatible_with") or [],
                    "data_tier": "free",
                    "research_status": "draft",
                }
                await upsert_filament(session, filament_data)
            log.info(f"    [Cloud SQL] {brand_slug}/{slugify(material.get('name',''))} upserted")
        except Exception as e:
            log.warning(f"    [Cloud SQL] upsert failed (non-fatal): {e}")

    try:
        asyncio.run(_upsert())
    except Exception as e:
        log.warning(f"    [Cloud SQL] async error (non-fatal): {e}")


# ── Main pipeline ─────────────────────────────────────────────────────────────


def run():
    log.info("=" * 60)
    log.info("FILAMENT PIPELINE — starting")
    log.info("=" * 60)

    tavily = _import_tavily()
    llm = _import_gemini()
    db = _import_firestore()
    _, bucket = _import_gcs()

    import uuid as _uuid
    pipeline_run_id = str(_uuid.uuid4())
    log.info(f"Pipeline run ID: {pipeline_run_id}")

    # Load checkpoint
    state = load_checkpoint(bucket)
    completed_brands = set(state.get("completed_brands", []))

    # Phase 1: Brand discovery
    if not state.get("discovered_brands"):
        brands_web = discover_brands(tavily, llm, SEED_BRANDS)
        brands_amazon = amazon_discover_brands(tavily, llm, min_rating=3.5)
        brands = list(set(brands_web + brands_amazon))
        state["discovered_brands"] = brands
        save_checkpoint(bucket, state)
    else:
        brands = state["discovered_brands"]

    log.info(
        f"Total brands: {len(brands)}  |  Already completed: {len(completed_brands)}"
    )

    # Phase 2: Per-brand material + settings research
    for brand in brands:
        brand_slug = slugify(brand)

        if brand_slug in completed_brands:
            log.info(f"  [SKIP] {brand} (already done)")
            continue

        log.info(f"\n  ── {brand} ──")
        try:
            materials = discover_materials(tavily, llm, brand)
            log.info(f"    Found {len(materials)} materials")

            for material in materials:
                mat_name = material.get("name", "?")
                log.info(f"    Researching: {mat_name}")
                try:
                    settings = research_material_settings(tavily, llm, brand, material)
                    write_to_firestore(db, brand, brand_slug, material, settings)
                    write_to_gcs(
                        bucket, brand_slug, material, settings, {"search_done": True}
                    )
                    write_to_bigquery(brand, brand_slug, material, settings, pipeline_run_id)
                    write_to_cloud_sql(brand, brand_slug, material, settings)
                except Exception as e:
                    log.error(f"    Error on {mat_name}: {e}")
                    traceback.print_exc()
                time.sleep(1)

            completed_brands.add(brand_slug)
            state["completed_brands"] = list(completed_brands)
            save_checkpoint(bucket, state)

        except Exception as e:
            log.error(f"  Error on brand {brand}: {e}")
            traceback.print_exc()

    state["finished_at"] = now_iso()
    save_checkpoint(bucket, state)
    log.info("\n" + "=" * 60)
    log.info(f"FILAMENT PIPELINE COMPLETE — {len(completed_brands)} brands processed")
    log.info("=" * 60)


if __name__ == "__main__":
    run()
