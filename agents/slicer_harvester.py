"""
agents/slicer_harvester.py — Open-Source Slicer Machine Profile Harvester.

Downloads machine/printer profiles from every major open-source slicer:
  - OrcaSlicer      (SoftFever/OrcaSlicer)
  - BambuStudio     (bambulab/BambuStudio)
  - PrusaSlicer     (prusa3d/PrusaSlicer)
  - SuperSlicer     (supermerill/SuperSlicer)
  - Cura            (Ultimaker/Cura) + fdm_materials
  - ideaMaker       (Raise3D — partial, some profiles are open)
  - Klipper configs (Klipper3d/klipper — printer.cfg examples)
  - Marlin configs  (MarlinFirmware/Marlin — Configuration.h examples)
  - Duet            (Duet3D/RepRapFirmware — machine configs)
  - FluidD/Mainsail (Klipper frontends — no machine profiles, skip)

For each slicer + machine:
  - Downloads raw profile JSON/INI/CFG
  - Extracts communication protocol (USB, Moonraker, Bambu P2P, Duet HTTP, etc.)
  - Notes caveats (auth, port, API version, firmware requirements)

Storage:
  GCS gs://qidistudio-filaments/slicer-profiles/{slicer}/{machine}/{file}
  Firestore: printers/{machine_slug}  — normalized machine records

Progress checkpoint: gs://qidistudio-filaments/_progress/slicer_harvester.json

Usage (background)::

    memory_env/Scripts/python.exe agents/slicer_harvester.py > agents/_slicer_log.txt 2>&1
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[1]
load_dotenv(REPO_ROOT / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("slicer_harvester")

# ── Slicer registry ───────────────────────────────────────────────────────────

SLICERS = [
    {
        "id": "orca_slicer",
        "name": "OrcaSlicer",
        "repo": "SoftFever/OrcaSlicer",
        "profile_paths": [
            "resources/profiles",
        ],
        "profile_extensions": [".json"],
        "protocol": "bambu_p2p_or_moonraker",
        "notes": (
            "OrcaSlicer supports Bambu Lab machines (proprietary P2P protocol, "
            "requires Bambu account auth or local mode patch), Klipper via Moonraker "
            "(HTTP REST + WebSocket), Marlin/Repetier (OctoPrint plugin or serial), "
            "and Prusa Connect. Machine profiles are in resources/profiles/<brand>/*.json. "
            "Each profile has 'machine_start_gcode', 'machine_end_gcode', and "
            "'host_type' field ('bambu'|'klipper'|'octoprint'|'duet'|'repetier')."
        ),
        "comm_protocols": {
            "bambu": {
                "type": "proprietary_p2p",
                "port": 1883,
                "auth": "Bambu account token + serial number",
                "local_mode": "Enable in Bambu printer settings → LAN Only Mode",
                "caveat": "Requires FTDI device authentication token; without local mode, cloud dependency",
            },
            "klipper": {
                "type": "moonraker_http",
                "port": 7125,
                "api": "Moonraker REST + WebSocket",
                "auth": "API key optional (moonraker.conf)",
                "caveat": "printer.cfg must expose required macros; START_PRINT/END_PRINT",
            },
            "octoprint": {
                "type": "octoprint_api",
                "port": 5000,
                "api": "OctoPrint REST API v1",
                "auth": "API key (Settings → API → Global API Key)",
                "caveat": "OctoPrint Plugin 'OrcaSlicer' not required but improves handshake",
            },
        },
    },
    {
        "id": "bambu_studio",
        "name": "BambuStudio",
        "repo": "bambulab/BambuStudio",
        "profile_paths": [
            "resources/profiles",
        ],
        "profile_extensions": [".json"],
        "protocol": "bambu_p2p",
        "notes": (
            "BambuStudio only officially supports Bambu Lab hardware. Uses a proprietary "
            "MQTT-based P2P protocol on port 1883 with device authentication. "
            "Local LAN Mode (no cloud) available on X1/P1/A1 series via printer Network Settings. "
            "Sends sliced 3MF to printer via FTP-like protocol on port 990 + MQTTS. "
            "Auth: access_code (4-digit PIN on printer) + serial number. "
            "No official API — reverse engineered in bambu-go, pybambu libraries."
        ),
        "comm_protocols": {
            "bambu_lan": {
                "type": "mqtt_p2p",
                "port": 1883,
                "ftp_port": 990,
                "auth": "access_code + serial_number",
                "local_mode": "Printer → Settings → Network → LAN Mode",
                "caveat": "X1/P1 need LAN Mode enabled. A1 series: LAN always available. "
                "File upload uses TLS FTP to /cache/ directory.",
            },
        },
    },
    {
        "id": "prusa_slicer",
        "name": "PrusaSlicer",
        "repo": "prusa3d/PrusaSlicer",
        "profile_paths": [
            "resources/profiles",
        ],
        "profile_extensions": [".ini", ".json"],
        "protocol": "prusa_connect_or_octoprint",
        "notes": (
            "PrusaSlicer supports Prusa Connect (cloud), PrusaLink (local HTTP API on MK4/XL/Mini), "
            "OctoPrint, and serial USB. Machine profiles in resources/profiles/<brand>/<printer>.ini. "
            "PrusaLink API: HTTP on port 80, digest auth, /api/v1/ endpoints. "
            "G-code flavors: Marlin, RepRap, Sailfish, Mach3, Machinekit, Smoothie. "
            "Physical printer dialog: 'PrusaConnect', 'PrusaLink (local)', 'OctoPrint', 'AnyPrint'."
        ),
        "comm_protocols": {
            "prusaconnect": {
                "type": "http_cloud",
                "api": "https://connect.prusa3d.com/",
                "auth": "Prusa account OAuth token",
            },
            "prusalink": {
                "type": "http_local",
                "port": 80,
                "api": "/api/v1/",
                "auth": "HTTP Digest auth — username 'maker', password from printer screen",
                "caveat": "Only MK4, MK3.9, Mini+, XL. MK3S uses different endpoint set.",
            },
            "octoprint": {
                "type": "octoprint_api",
                "port": 5000,
                "auth": "API key",
            },
        },
    },
    {
        "id": "super_slicer",
        "name": "SuperSlicer",
        "repo": "supermerill/SuperSlicer",
        "profile_paths": [
            "resources/profiles",
        ],
        "profile_extensions": [".ini", ".json"],
        "protocol": "octoprint_or_serial",
        "notes": (
            "SuperSlicer is a PrusaSlicer fork with additional features. "
            "Same communication protocols as PrusaSlicer. "
            "Notable: has full pressure advance tuning built in, "
            "more advanced cooling control, seam painting, and elephant foot compensation. "
            "Profiles are cross-compatible with PrusaSlicer 2.x."
        ),
        "comm_protocols": {
            "octoprint": {"type": "octoprint_api", "port": 5000, "auth": "API key"},
            "klipper": {
                "type": "moonraker_http",
                "port": 7125,
                "auth": "optional API key",
            },
        },
    },
    {
        "id": "cura",
        "name": "Ultimaker Cura",
        "repo": "Ultimaker/Cura",
        "profile_paths": [
            "resources/definitions",
            "resources/extruders",
        ],
        "profile_extensions": [".def.json", ".json"],
        "protocol": "ultimaker_api_or_octoprint",
        "notes": (
            "Cura uses .def.json machine definitions in resources/definitions/. "
            "Inheritance chain: fdmprinter.def.json → brand_base → specific_model. "
            "Key fields: machine_start_gcode, machine_end_gcode, machine_gcode_flavor "
            "('Griffin'|'RepRap (Marlin/Sprinter)'|'RepRap (Volumetric)'|'Ultigcode'|'Marlin (Volumetric)'|'Repetier'). "
            "Communication: Ultimaker API (port 80, digest auth), OctoPrint, Repetier, Duet, "
            "or direct file export. "
            "Cura Connect: network printing to Ultimaker printers. "
            "Plugin: 'OctoPrint Connection', 'Duet Connection' extensions for non-UM printers."
        ),
        "comm_protocols": {
            "ultimaker_api": {
                "type": "http_local",
                "port": 80,
                "api": "Ultimaker API 1.0",
                "auth": "HTTP Digest — credentials shown on printer screen first connection",
            },
            "octoprint": {
                "type": "octoprint_api",
                "port": 5000,
                "auth": "API key",
                "plugin": "OctoPrint Connection plugin in Cura marketplace",
            },
            "duet": {
                "type": "duet_http",
                "port": 80,
                "api": "RepRapFirmware HTTP API",
                "auth": "HTTP password optional",
                "plugin": "Duet For Cura plugin",
            },
        },
    },
    {
        "id": "klipper",
        "name": "Klipper3D",
        "repo": "Klipper3d/klipper",
        "profile_paths": [
            "config",
        ],
        "profile_extensions": [".cfg"],
        "protocol": "moonraker",
        "notes": (
            "Klipper is firmware, not a slicer. But config/ contains example printer.cfg for "
            "many machines. Klipper communicates with the host (Raspberry Pi / SBC) via serial/USB. "
            "Slicer communicates with Klipper through Moonraker (REST + WebSocket on port 7125). "
            "Key Moonraker API endpoints: POST /printer/gcode/script, POST /server/files/upload, "
            "GET /printer/info, GET /printer/objects/query. "
            "Authentication: API key (optional, moonraker.conf cors_domains). "
            "Caveats: Machine-specific macros (START_PRINT, END_PRINT) must be defined in printer.cfg. "
            "Requires INPUT_SHAPER calibration for high-speed printing. "
            "EXCLUDE_OBJECT requires 'label_objects = True' in moonraker.conf."
        ),
        "comm_protocols": {
            "moonraker": {
                "type": "http_websocket",
                "port": 7125,
                "api_http": "GET/POST http://<ip>:7125/",
                "api_ws": "ws://<ip>:7125/websocket",
                "auth": "API key optional — set in moonraker.conf api_key field",
                "file_upload": "POST /server/files/upload (multipart/form-data)",
                "print_start": "POST /printer/print/start?filename=<name>",
                "gcode_exec": "POST /printer/gcode/script  body: {script: 'G28'}",
                "caveat": "CORS must be configured; API key recommended for remote access",
            },
        },
    },
    {
        "id": "marlin",
        "name": "Marlin Firmware",
        "repo": "MarlinFirmware/Marlin",
        "profile_paths": [
            "Marlin/src/config/examples",
        ],
        "profile_extensions": [".h"],
        "protocol": "serial_usb_or_serial_tcp",
        "notes": (
            "Marlin is firmware. Example configs in Marlin/src/config/examples/<brand>/<model>/. "
            "Communication: serial USB (typically /dev/ttyUSB0 at 250000 baud) or "
            "serial-over-TCP via ESP3D/Duet WiFi bridge. "
            "Slicers connect via OctoPrint (most common), Repetier-Server, or direct serial plugin. "
            "Key Marlin caveats: "
            "EEPROM stores calibration values (M500/M501/M502); "
            "Thermal runaway protection must be enabled (safety); "
            "Linear Advance requires M900 support compiled in; "
            "S_CURVE_ACCELERATION smooths high-speed moves; "
            "EMERGENCY_PARSER allows real-time M112 abort."
        ),
        "comm_protocols": {
            "serial": {
                "type": "serial",
                "baud": 250000,
                "interface": "USB CDC / CH340 / FTDI",
                "caveat": "Must match BAUDRATE in Configuration.h",
            },
            "octoprint": {
                "type": "octoprint_api",
                "port": 5000,
                "auth": "API key",
            },
        },
    },
    {
        "id": "reprap_firmware",
        "name": "RepRapFirmware (Duet)",
        "repo": "Duet3D/RepRapFirmware",
        "profile_paths": [
            "src",
        ],
        "profile_extensions": [".json", ".g"],
        "protocol": "duet_http",
        "notes": (
            "RepRapFirmware runs on Duet boards. Configured via G-code macros in /sys/. "
            "HTTP API at port 80; WebSocket at /rr_connect. "
            "Duet Web Control (DWC) is the frontend. "
            "File upload: POST to /rr_upload; print: GET /rr_gcode?gcode=M32%20<file>. "
            "Slicer support: PrusaSlicer, Cura (plugin), Simplify3D all support Duet HTTP API. "
            "Caveats: authentication via password= GET param (not production-safe); "
            "tool definitions live in config.g; must define T0, T1 tools."
        ),
        "comm_protocols": {
            "duet_http": {
                "type": "http_websocket",
                "port": 80,
                "api_base": "/rr_",
                "auth": "password GET param (set in config.g M552 or HTTP password)",
                "file_upload": "POST /rr_upload?name=0:/gcodes/<file>",
                "status": "GET /rr_status?type=1",
                "caveat": "DSF (Duet Software Framework) has newer JSON API at /machine/",
            },
        },
    },
    {
        "id": "fluidd_config",
        "name": "Fluidd + Mainsail (Klipper configs)",
        "repo": "FluiddUI/fluidd-config",
        "profile_paths": [
            "client.cfg",
        ],
        "profile_extensions": [".cfg"],
        "protocol": "moonraker",
        "notes": (
            "Fluidd and Mainsail are Klipper web frontends. They don't have machine profiles "
            "themselves. The fluidd-config / mainsail-config repos provide base macros "
            "(PAUSE, RESUME, CANCEL_PRINT, LOAD_FILAMENT, UNLOAD_FILAMENT) that slicers "
            "expect to find. Include via [include fluidd.cfg] in printer.cfg. "
            "Uses same Moonraker API as Klipper."
        ),
        "comm_protocols": {
            "moonraker": {"type": "http_websocket", "port": 7125},
        },
    },
]

# ── GitHub API helpers ────────────────────────────────────────────────────────

GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GH_HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GH_TOKEN:
    GH_HEADERS["Authorization"] = f"token {GH_TOKEN}"


def gh_get(url: str) -> Any:
    """GitHub API GET with rate-limit handling."""
    try:
        resp = requests.get(url, headers=GH_HEADERS, timeout=30)
        if resp.status_code == 403:
            reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(1, reset - time.time() + 5)
            log.warning(f"GitHub rate limit hit — sleeping {wait:.0f}s")
            time.sleep(wait)
            resp = requests.get(url, headers=GH_HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.warning(f"GitHub API error {url}: {e}")
        return None


def list_repo_files(repo: str, path: str, extensions: list[str]) -> list[dict]:
    """Recursively list all files in a repo path matching extensions."""
    files = []
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    items = gh_get(url)
    if not isinstance(items, list):
        return files

    for item in items:
        if item.get("type") == "dir":
            sub = list_repo_files(repo, item["path"], extensions)
            files.extend(sub)
            time.sleep(0.1)
        elif item.get("type") == "file":
            name = item.get("name", "")
            if any(name.endswith(ext) for ext in extensions):
                files.append(
                    {
                        "name": name,
                        "path": item["path"],
                        "download_url": item.get("download_url", ""),
                        "size": item.get("size", 0),
                    }
                )
    return files


def download_file(url: str) -> str | None:
    """Download raw file content."""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        log.warning(f"Download failed {url}: {e}")
        return None


# ── GCS helpers ───────────────────────────────────────────────────────────────


def _get_bucket():
    from google.cloud import storage

    client = storage.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])
    bucket = client.bucket("qidistudio-filaments")
    try:
        bucket.reload()
    except Exception:
        bucket = client.create_bucket("qidistudio-filaments", location="us-central1")
        log.info("Created GCS bucket qidistudio-filaments")
    return bucket


CHECKPOINT_KEY = "_progress/slicer_harvester.json"


def load_checkpoint(bucket) -> dict:
    try:
        return json.loads(bucket.blob(CHECKPOINT_KEY).download_as_text())
    except Exception:
        return {
            "completed_slicers": [],
            "started_at": datetime.now(timezone.utc).isoformat(),
        }


def save_checkpoint(bucket, state: dict):
    try:
        bucket.blob(CHECKPOINT_KEY).upload_from_string(
            json.dumps(state, indent=2), content_type="application/json"
        )
    except Exception as e:
        log.warning(f"Checkpoint save failed: {e}")


def write_profile_to_gcs(bucket, slicer_id: str, file_path: str, content: str):
    key = f"slicer-profiles/{slicer_id}/{file_path}"
    try:
        bucket.blob(key).upload_from_string(content, content_type="text/plain")
    except Exception as e:
        log.warning(f"GCS write failed {key}: {e}")


def write_slicer_meta_to_gcs(bucket, slicer: dict, file_count: int):
    key = f"slicer-profiles/{slicer['id']}/_meta.json"
    meta = {
        "id": slicer["id"],
        "name": slicer["name"],
        "repo": slicer["repo"],
        "protocol": slicer["protocol"],
        "notes": slicer["notes"],
        "comm_protocols": slicer.get("comm_protocols", {}),
        "profile_count": file_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        bucket.blob(key).upload_from_string(
            json.dumps(meta, indent=2), content_type="application/json"
        )
    except Exception as e:
        log.warning(f"Meta write failed: {e}")


def write_slicer_to_firestore(slicer: dict, file_count: int):
    """Write slicer comm protocol info to Firestore."""
    try:
        from google.cloud import firestore

        db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])
        doc = {
            "id": slicer["id"],
            "name": slicer["name"],
            "repo": slicer["repo"],
            "protocol": slicer["protocol"],
            "notes": slicer["notes"],
            "comm_protocols": slicer.get("comm_protocols", {}),
            "profile_count": file_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        db.collection("slicers").document(slicer["id"]).set(doc)
        log.info(f"  [Firestore] slicers/{slicer['id']} written")
    except Exception as e:
        log.error(f"  [Firestore] slicer write failed: {e}")


# ── Additional machine comm research via Tavily ───────────────────────────────


def research_machine_comms(slicer_id: str) -> str:
    """Use Tavily to discover additional machines this slicer supports."""
    try:
        from tavily import TavilyClient

        tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

        slicer_name = next(s["name"] for s in SLICERS if s["id"] == slicer_id)
        results = tavily.search(
            f"{slicer_name} supported printers communication protocol API list complete 2024",
            max_results=8,
            search_depth="basic",
        )
        snippets = [r.get("content", "")[:400] for r in results.get("results", [])]
        return "\n".join(snippets)
    except Exception as e:
        log.warning(f"Tavily research failed for {slicer_id}: {e}")
        return ""


# ── Main pipeline ─────────────────────────────────────────────────────────────


def run():
    log.info("=" * 60)
    log.info("SLICER HARVESTER — starting")
    log.info("=" * 60)

    bucket = _get_bucket()
    state = load_checkpoint(bucket)
    completed = set(state.get("completed_slicers", []))

    # Write master index of all slicers + protocols to GCS
    index = [
        {
            "id": s["id"],
            "name": s["name"],
            "repo": s["repo"],
            "protocol": s["protocol"],
            "comm_protocols": s.get("comm_protocols", {}),
        }
        for s in SLICERS
    ]
    bucket.blob("slicer-profiles/_index.json").upload_from_string(
        json.dumps(index, indent=2), content_type="application/json"
    )
    log.info(f"Index written: {len(SLICERS)} slicers")

    for slicer in SLICERS:
        sid = slicer["id"]
        if sid in completed:
            log.info(f"  [SKIP] {slicer['name']} (already done)")
            continue

        log.info(f"\n  ── {slicer['name']} ({slicer['repo']}) ──")

        try:
            # Write meta + comm protocols
            write_slicer_to_firestore(slicer, 0)
            write_slicer_meta_to_gcs(bucket, slicer, 0)

            # Collect profile files from GitHub
            total_files = 0
            for profile_path in slicer["profile_paths"]:
                log.info(f"    Listing {profile_path}/ ...")
                try:
                    files = list_repo_files(
                        slicer["repo"],
                        profile_path,
                        slicer["profile_extensions"],
                    )
                    log.info(f"    Found {len(files)} profile files")

                    # Download profiles (cap at 500 per slicer to avoid overload)
                    for file in files[:500]:
                        if file.get("size", 0) > 500_000:
                            log.info(f"    [SKIP large] {file['name']}")
                            continue
                        content = download_file(file["download_url"])
                        if content:
                            write_profile_to_gcs(bucket, sid, file["path"], content)
                            total_files += 1
                        time.sleep(0.05)  # gentle rate limiting

                except Exception as e:
                    log.error(f"    Error listing {profile_path}: {e}")

            # Update meta with real file count
            write_slicer_meta_to_gcs(bucket, slicer, total_files)
            write_slicer_to_firestore(slicer, total_files)

            # Bonus: web research for additional supported machines
            log.info(f"    Researching additional supported machines via web...")
            extra_info = research_machine_comms(sid)
            if extra_info:
                bucket.blob(
                    f"slicer-profiles/{sid}/_web_research.txt"
                ).upload_from_string(extra_info, content_type="text/plain")

            completed.add(sid)
            state["completed_slicers"] = list(completed)
            save_checkpoint(bucket, state)
            log.info(f"    {slicer['name']}: {total_files} files harvested ✓")

        except Exception as e:
            log.error(f"  Error on {slicer['name']}: {e}")
            traceback.print_exc()

    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    save_checkpoint(bucket, state)

    log.info("\n" + "=" * 60)
    log.info(f"SLICER HARVESTER COMPLETE — {len(completed)} slicers harvested")
    log.info("Data at: gs://qidistudio-filaments/slicer-profiles/")
    log.info("=" * 60)


if __name__ == "__main__":
    run()
