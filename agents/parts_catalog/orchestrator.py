"""
agents/parts_catalog/orchestrator.py

Runs the full NexusMill parts catalog harvester fleet in sequence,
with per-harvester progress tracking and clean logging.

Harvesters run order:
  1. motor_harvester       — foundational (torque curve physics depends on this)
  2. driver_harvester      — depends on motor knowledge for compatibility context
  3. power_supply_harvester
  4. rail_harvester
  5. lead_screw_harvester
  6. spindle_harvester
  7. controller_harvester
  8. frame_harvester
  9. coupler_harvester
  10. sensor_harvester
  11. kit_template_builder  — runs LAST (queries LanceDB for real parts)

Usage:
    memory_env/Scripts/python.exe agents/parts_catalog/orchestrator.py \
        > agents/parts_catalog/_orchestrator_log.txt 2>&1

    # Run a single harvester only:
    memory_env/Scripts/python.exe agents/parts_catalog/orchestrator.py motors

    # List available harvesters:
    memory_env/Scripts/python.exe agents/parts_catalog/orchestrator.py --list
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

LOG_FILE = REPO_ROOT / "agents" / "parts_catalog" / "_orchestrator_log.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
    ],
)
log = logging.getLogger("orchestrator")

# ── Harvester registry ────────────────────────────────────────────────────────

HARVESTERS = [
    {
        "key": "motors",
        "label": "Motor Harvester",
        "module": "agents.parts_catalog.motor_harvester",
        "fn": "run",
    },
    {
        "key": "drivers",
        "label": "Driver Harvester",
        "module": "agents.parts_catalog.driver_harvester",
        "fn": "run",
    },
    {
        "key": "power_supplies",
        "label": "Power Supply Harvester",
        "module": "agents.parts_catalog.power_supply_harvester",
        "fn": "run",
    },
    {
        "key": "rails",
        "label": "Rail Harvester",
        "module": "agents.parts_catalog.rail_harvester",
        "fn": "run",
    },
    {
        "key": "lead_screws",
        "label": "Lead Screw Harvester",
        "module": "agents.parts_catalog.lead_screw_harvester",
        "fn": "run",
    },
    {
        "key": "spindles",
        "label": "Spindle Harvester",
        "module": "agents.parts_catalog.spindle_harvester",
        "fn": "run",
    },
    {
        "key": "controllers",
        "label": "Controller Harvester",
        "module": "agents.parts_catalog.controller_harvester",
        "fn": "run",
    },
    {
        "key": "frames",
        "label": "Frame Harvester",
        "module": "agents.parts_catalog.frame_harvester",
        "fn": "run",
    },
    {
        "key": "couplers",
        "label": "Coupler Harvester",
        "module": "agents.parts_catalog.coupler_harvester",
        "fn": "run",
    },
    {
        "key": "sensors",
        "label": "Sensor Harvester",
        "module": "agents.parts_catalog.sensor_harvester",
        "fn": "run",
    },
    {
        "key": "kits",
        "label": "Kit & Template Builder",
        "module": "agents.parts_catalog.kit_template_builder",
        "fn": "run",
    },
]

HARVESTER_KEYS = [h["key"] for h in HARVESTERS]


def run_all(only_keys: list[str] | None = None):
    start_total = time.time()
    log.info("=" * 60)
    log.info("NexusMill Parts Catalog Orchestrator")
    log.info(
        "Started at: %s UTC", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    )
    log.info("=" * 60)

    targets = [h for h in HARVESTERS if only_keys is None or h["key"] in only_keys]

    if not targets:
        log.error("No matching harvesters found for keys: %s", only_keys)
        return

    for i, harvester in enumerate(targets, 1):
        log.info("")
        log.info("─" * 50)
        log.info("[%d/%d] Starting: %s", i, len(targets), harvester["label"])
        log.info("─" * 50)

        start = time.time()
        try:
            import importlib

            module = importlib.import_module(harvester["module"])
            fn = getattr(module, harvester["fn"])
            fn()
            elapsed = time.time() - start
            log.info(
                "[%d/%d] DONE: %s — %.1fs", i, len(targets), harvester["label"], elapsed
            )
        except Exception as e:
            elapsed = time.time() - start
            log.error(
                "[%d/%d] FAILED: %s — %s (%.1fs)",
                i,
                len(targets),
                harvester["label"],
                e,
                elapsed,
                exc_info=True,
            )
            log.error("Continuing to next harvester...")

        # Brief pause between harvesters to respect API rate limits
        if i < len(targets):
            log.info("Pausing 10s before next harvester...")
            time.sleep(10)

    total_elapsed = time.time() - start_total
    log.info("")
    log.info("=" * 60)
    log.info(
        "Orchestrator complete — total time: %.1fs (%.1f min)",
        total_elapsed,
        total_elapsed / 60,
    )
    log.info("=" * 60)


def main():
    args = sys.argv[1:]

    if "--list" in args:
        print("\nAvailable harvesters:")
        for h in HARVESTERS:
            print(f"  {h['key']:<20}  {h['label']}")
        print()
        return

    if args:
        # Run specific harvesters by key
        unknown = [a for a in args if a not in HARVESTER_KEYS]
        if unknown:
            print(f"Unknown harvester keys: {unknown}")
            print(f"Available: {HARVESTER_KEYS}")
            sys.exit(1)
        run_all(only_keys=args)
    else:
        # Run full fleet
        run_all()


if __name__ == "__main__":
    main()
