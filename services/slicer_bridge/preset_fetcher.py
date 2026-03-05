"""
services/slicer_bridge/preset_fetcher.py — Python sidecar for the QIDIStudio slicer.

This script is spawned as a subprocess at slicer startup. It:
  1. Resolves the subscription tier (auth check)
  2. Fetches the appropriate preset bundle from Cloud SQL
  3. Writes the bundle to the local preset cache directory
  4. Signals readiness by writing a .ready file
  5. Exits (not a long-running daemon — one-shot per startup)

The C++ slicer continues to read presets from the local JSON files as before.
No C++ network code changes are required.

Output format mirrors existing resources/profiles/ structure:
  - resources/profiles/cache/{tier}/<manufacturer>/<filament>.json
  - resources/profiles/cache/index.json  (master index the slicer reads)

Usage (called by C++ subprocess at startup):
    python -m services.slicer_bridge.preset_fetcher [--tier free|pro] [--output-dir PATH]

Or from Python:
    from services.slicer_bridge.preset_fetcher import run_sidecar
    asyncio.run(run_sidecar())
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import logging
import os
import pathlib
import sys
import time
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [preset-fetcher] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("preset_fetcher")

# ── Defaults ──────────────────────────────────────────────────────────────────

_WORKSPACE = pathlib.Path(__file__).resolve().parents[3]  # repo root
_CACHE_DIR = _WORKSPACE / "resources" / "profiles" / "cache"
_READY_FILE = _CACHE_DIR / ".ready"
_INDEX_FILE = _CACHE_DIR / "index.json"
_FALLBACK_INDEX = _WORKSPACE / "resources" / "profiles"  # existing bundled profiles

# How old can the cached bundle be before we re-fetch?
_MAX_CACHE_AGE_HOURS = int(os.getenv("PRESET_CACHE_MAX_AGE_HOURS", "6"))


# ── Cache freshness ───────────────────────────────────────────────────────────


def _cache_is_fresh(tier: str) -> bool:
    """True if the cache for this tier was written within the max age window."""
    ts_file = _CACHE_DIR / f".ts_{tier}"
    if not ts_file.exists():
        return False
    try:
        ts = float(ts_file.read_text().strip())
        age_hours = (time.time() - ts) / 3600
        return age_hours < _MAX_CACHE_AGE_HOURS
    except Exception:
        return False


def _mark_cache_fresh(tier: str) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (_CACHE_DIR / f".ts_{tier}").write_text(str(time.time()))


# ── Preset format helpers ─────────────────────────────────────────────────────


def _build_filament_preset(filament: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a Cloud SQL filament row dict → slicer preset JSON format.
    Matches the structure of existing resources/profiles/filaments/*.json.
    """
    name = filament.get("product_name", "Unknown")
    mfr = filament.get("manufacturer_name", "Generic")
    category = filament.get("category", "PLA")

    # Build the preset dict using the slicer's expected keys
    preset: dict[str, Any] = {
        "type": "filament",
        "name": f"{mfr} {name}",
        "from": "system",
        "inherits": category,
        "filament_vendor": mfr,
        "filament_type": category,
        "filament_diameter": [str(filament.get("diameter_mm", "1.75"))],
    }

    # Temperature settings
    if nozzle_rec := filament.get("nozzle_temp_rec_c"):
        preset["nozzle_temperature"] = [str(nozzle_rec)]
    if nozzle_min := filament.get("nozzle_temp_min_c"):
        preset["min_print_temp"] = [str(nozzle_min)]
    if bed_rec := filament.get("bed_temp_rec_c"):
        preset["bed_temperature"] = [str(bed_rec)]
    if bed_pei := filament.get("bed_temp_pei_c"):
        preset["bed_temperature_pei"] = [str(bed_pei)]
    if chamber_rec := filament.get("chamber_temp_rec_c"):
        preset["chamber_temperature"] = [str(chamber_rec)]

    # Speed settings
    if speed := filament.get("print_speed_rec_mms"):
        preset["filament_max_speed"] = [str(speed)]

    # Cooling
    if cooling := filament.get("cooling_fan_rec_pct"):
        preset["cooling_fan_speed"] = [str(cooling)]

    # Retraction (direct drive preferred, fall back to bowden)
    ret = filament.get("retraction_direct_mm") or filament.get("retraction_bowden_mm")
    if ret:
        preset["retraction_length"] = [str(ret)]

    # Flow
    if flow := filament.get("flow_rate_pct"):
        preset["filament_flow_rate"] = [str(flow / 100.0)]

    # Drying
    if dry_temp := filament.get("drying_temp_c"):
        preset["filament_drying_temperature"] = [str(dry_temp)]
    if dry_time := filament.get("drying_time_hours"):
        preset["filament_drying_time"] = [str(dry_time * 60)]  # minutes

    # Pro-tier nozzle overrides
    if pro_nozzle := filament.get("pro_settings_by_nozzle"):
        preset["_pro_nozzle_overrides"] = pro_nozzle  # slicer ignores unknown keys

    return preset


# ── Free tier: load from bundled profiles ─────────────────────────────────────


def _load_free_tier_presets() -> list[dict[str, Any]]:
    """Load the existing bundled filament JSONs (free tier fallback)."""
    presets: list[dict[str, Any]] = []
    filament_dir = _FALLBACK_INDEX
    for json_file in filament_dir.glob("**/*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                presets.extend(data)
            elif isinstance(data, dict):
                presets.append(data)
        except Exception:
            continue
    return presets


# ── Pro tier: fetch from Cloud SQL ────────────────────────────────────────────


async def _fetch_pro_presets() -> list[dict[str, Any]]:
    """Fetch all published pro-tier filament presets from Cloud SQL."""
    try:
        from services.db.cloud_sql import get_session, get_filaments_for_tier
        from services.db.models import DataTier
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select
        from services.db.models import Filament, FilamentManufacturer
    except ImportError as e:
        log.warning(f"Cloud SQL import failed: {e} — falling back to free tier")
        return []

    presets: list[dict[str, Any]] = []
    try:
        async with get_session() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(Filament, FilamentManufacturer.name.label("manufacturer_name"))
                .join(FilamentManufacturer)
                .where(Filament.research_status == "published")
            )
            rows = result.all()

        for row in rows:
            filament = row[0]
            mfr_name = row[1]
            row_dict = {
                c.name: getattr(filament, c.name) for c in filament.__table__.columns
            }
            row_dict["manufacturer_name"] = mfr_name
            presets.append(_build_filament_preset(row_dict))

        log.info(f"Fetched {len(presets)} pro filament presets from Cloud SQL")
    except Exception as e:
        log.warning(f"Cloud SQL fetch failed: {e}")
        return []

    return presets


# ── Write cache ───────────────────────────────────────────────────────────────


def _write_cache(
    presets: list[dict[str, Any]], tier: str, output_dir: pathlib.Path
) -> None:
    """Write the preset bundle to the local cache directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write individual preset files grouped by filament_vendor
    index_entries: list[dict[str, str]] = []
    vendors: dict[str, list[dict[str, Any]]] = {}
    for preset in presets:
        vendor = preset.get("filament_vendor", "Generic")
        vendors.setdefault(vendor, []).append(preset)

    for vendor, vendor_presets in vendors.items():
        vendor_slug = vendor.lower().replace(" ", "_").replace("-", "_")
        vendor_dir = output_dir / vendor_slug
        vendor_dir.mkdir(parents=True, exist_ok=True)

        for preset in vendor_presets:
            preset_name = (
                preset.get("name", "unknown").replace("/", "_").replace("\\", "_")
            )
            preset_file = vendor_dir / f"{preset_name}.json"
            preset_file.write_text(json.dumps(preset, indent=2))
            index_entries.append(
                {
                    "vendor": vendor,
                    "name": preset.get("name", ""),
                    "path": str(preset_file.relative_to(output_dir)),
                    "tier": tier,
                }
            )

    # Write master index
    index = {
        "version": "1.0",
        "tier": tier,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preset_count": len(presets),
        "entries": index_entries,
    }
    (output_dir / "index.json").write_text(json.dumps(index, indent=2))
    log.info(f"Wrote {len(presets)} presets to {output_dir}")


# ── Main ──────────────────────────────────────────────────────────────────────


async def run_sidecar(output_dir: pathlib.Path | None = None) -> int:
    """
    Main sidecar coroutine. Returns exit code (0 = success, 1 = error).

    Steps:
      1. Auth check → resolve tier
      2. Check cache freshness
      3. Fetch presets based on tier
      4. Write to output_dir
      5. Write .ready signal
    """
    from services.auth.subscription import resolve_tier

    out = output_dir or _CACHE_DIR

    # Step 1: Auth
    log.info("Resolving subscription tier...")
    try:
        check = await resolve_tier()
        tier = check.tier
        is_pro = check.is_pro
        log.info(f"Tier: {tier} (source: {check.source}, pro: {is_pro})")
    except Exception as e:
        log.error(f"Auth check failed: {e} — defaulting to free tier")
        tier = "free"
        is_pro = False

    # Step 2: Cache freshness
    if _cache_is_fresh(tier):
        log.info(f"Cache is fresh for tier={tier}, skipping fetch")
        _READY_FILE.write_text("ok")
        return 0

    # Step 3: Fetch
    if is_pro:
        log.info("Fetching pro presets from Cloud SQL...")
        presets = await _fetch_pro_presets()
        if not presets:
            log.warning("Pro fetch returned 0 presets — falling back to free tier")
            tier = "free"
            presets = _load_free_tier_presets()
    else:
        log.info("Loading free tier bundled presets...")
        presets = _load_free_tier_presets()

    if not presets:
        log.error("No presets loaded — cannot write cache")
        return 1

    # Step 4: Write cache
    _write_cache(presets, tier, out)
    _mark_cache_fresh(tier)

    # Step 5: Signal readiness
    _READY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _READY_FILE.write_text("ok")
    log.info(
        f"Preset sidecar complete — {len(presets)} presets cached for tier '{tier}'"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="QIDIStudio preset fetcher sidecar")
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=None,
        help="Override output directory (default: resources/profiles/cache/)",
    )
    parser.add_argument(
        "--tier",
        choices=["free", "trial", "monthly", "yearly", "lifetime"],
        default=None,
        help="Force a specific tier (for testing)",
    )
    args = parser.parse_args()

    if args.tier:
        os.environ["_FORCE_TIER"] = (
            args.tier
        )  # picked up by subscription.resolve_tier()

    exit_code = asyncio.run(run_sidecar(args.output_dir))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
