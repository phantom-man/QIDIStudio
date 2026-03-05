"""
agents/nozzle_pipeline.py — Comprehensive FDM nozzle repository research pipeline.

Researches every commercially relevant FDM nozzle type and builds a
structured, validated knowledge base stored in:
  - BigQuery: raw_nozzle_research (audit trail)
  - Cloud SQL: nozzle_types + nozzle_filament_settings (validated data)
  - LanceDB: nozzle knowledge (semantic search by the researcher agent)

Nozzle types covered:
  Brass (0.2–1.2mm), Hardened Steel, Stainless Steel, Ruby-tipped,
  Tungsten Carbide, Copper, Nickel-plated brass, Titanium,
  CHT bi-metal (high-flow), Nozzle X (E3D), Volcano (high-flow),
  Silicon Carbide, Plated copper (Bambu), MK8 variants, V6 variants,
  Mosquito/Dragon/Rapido (hotend-matched), and more.

Usage:
    python -m agents.nozzle_pipeline             # research all nozzle types
    python -m agents.nozzle_pipeline --slug brass-0.4  # single nozzle
    python -m agents.nozzle_pipeline --dry-run   # print plan, no writes
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from langsmith import traceable

from agents.research_evaluator import ResearchEvaluator
from schemas.research_data import (
    NozzleResearchData,
    ResearchFinding,
    ResearchReport,
    ResearchRun,
    ResearchSource,
)

load_dotenv()
log = logging.getLogger(__name__)

_LANGSMITH_PROJECT = os.getenv("LANGCHAIN_PROJECT", "qidistudio-manufacturing")

# ── Master nozzle seed list ───────────────────────────────────────────────────
# Each entry: (slug, display_name, material, diameter_mm, priority)
SEED_NOZZLES: list[tuple[str, str, str, float, str]] = [
    # Brass — the baseline everything is measured against
    ("brass-0.2", "Brass 0.2mm", "brass", 0.2, "high"),
    ("brass-0.25", "Brass 0.25mm", "brass", 0.25, "medium"),
    ("brass-0.3", "Brass 0.3mm", "brass", 0.3, "high"),
    ("brass-0.4", "Brass 0.4mm", "brass", 0.4, "critical"),   # the reference nozzle
    ("brass-0.5", "Brass 0.5mm", "brass", 0.5, "high"),
    ("brass-0.6", "Brass 0.6mm", "brass", 0.6, "medium"),
    ("brass-0.8", "Brass 0.8mm", "brass", 0.8, "medium"),
    ("brass-1.0", "Brass 1.0mm", "brass", 1.0, "low"),
    ("brass-1.2", "Brass 1.2mm", "brass", 1.2, "low"),

    # Hardened Steel — abrasive filaments (CF, GF, metal fills)
    ("hardened-steel-0.2", "Hardened Steel 0.2mm", "hardened_steel", 0.2, "medium"),
    ("hardened-steel-0.4", "Hardened Steel 0.4mm", "hardened_steel", 0.4, "critical"),
    ("hardened-steel-0.6", "Hardened Steel 0.6mm", "hardened_steel", 0.6, "high"),
    ("hardened-steel-0.8", "Hardened Steel 0.8mm", "hardened_steel", 0.8, "medium"),
    ("hardened-steel-1.0", "Hardened Steel 1.0mm", "hardened_steel", 1.0, "low"),

    # Stainless Steel — food-safe applications
    ("stainless-steel-0.4", "Stainless Steel 0.4mm", "stainless_steel", 0.4, "high"),
    ("stainless-steel-0.6", "Stainless Steel 0.6mm", "stainless_steel", 0.6, "medium"),

    # Ruby-tipped — premium abrasion resistance, excellent thermal
    ("ruby-0.25", "Ruby 0.25mm", "ruby", 0.25, "medium"),
    ("ruby-0.4", "Ruby 0.4mm", "ruby", 0.4, "critical"),
    ("ruby-0.6", "Ruby 0.6mm", "ruby", 0.6, "medium"),

    # Tungsten Carbide — extreme abrasion resistance
    ("tungsten-carbide-0.4", "Tungsten Carbide 0.4mm", "tungsten_carbide", 0.4, "high"),
    ("tungsten-carbide-0.6", "Tungsten Carbide 0.6mm", "tungsten_carbide", 0.6, "medium"),

    # Copper — ultra-high thermal conductivity for high-speed printing
    ("copper-0.4", "Copper 0.4mm", "copper", 0.4, "medium"),
    ("copper-0.6", "Copper 0.6mm", "copper", 0.6, "medium"),

    # Nickel-plated brass — reduced filament sticking
    ("plated-brass-0.4", "Nickel-Plated Brass 0.4mm", "plated_brass", 0.4, "medium"),
    ("plated-brass-0.6", "Nickel-Plated Brass 0.6mm", "plated_brass", 0.6, "low"),

    # Plated copper — Bambu Lab style (high-flow high-temp)
    ("plated-copper-0.4", "Hardened Plated Copper 0.4mm", "plated_copper", 0.4, "high"),
    ("plated-copper-0.6", "Hardened Plated Copper 0.6mm", "plated_copper", 0.6, "medium"),
    ("plated-copper-0.8", "Hardened Plated Copper 0.8mm", "plated_copper", 0.8, "medium"),

    # Silicon Carbide — experimental, extreme hardness
    ("silicon-carbide-0.4", "Silicon Carbide 0.4mm", "silicon_carbide", 0.4, "low"),

    # Aluminium — rapid prototyping, cheap
    ("aluminum-0.4", "Aluminum 0.4mm", "aluminum", 0.4, "low"),
]

# Research query template per nozzle type
_RESEARCH_QUERY_TEMPLATE = """
Research the {name} nozzle for FDM 3D printing.
Collect ALL of the following information from authoritative sources
(manufacturer pages, E3D wiki, Prusa docs, Reprap wiki, academic papers, community wikis):

1. MATERIAL & CONSTRUCTION:
   - Exact material composition and hardness rating (HRC)
   - Thermal conductivity (W/m·K)
   - Max operating temperature (°C)
   - Coating if any (plating type, thickness)

2. ABRASION RESISTANCE:
   - Rating: low | medium | high | extreme
   - Which filament categories WILL DAMAGE this nozzle (abrasive = CF, GF, metal fills)
   - Estimated lifespan by filament type

3. PRINT SETTING DELTAS vs. brass 0.4mm baseline:
   - Nozzle temperature offset (°C) — positive = hotter than brass
   - Flow rate multiplier (1.0 = same as brass)
   - Retraction adjustment (mm change from brass)
   - Print speed multiplier
   - Pressure advance change
   - First layer notes
   - Cooling fan differences

4. PER-FILAMENT-CATEGORY OVERRIDES:
   For each filament type this nozzle handles (PLA, PETG, ABS, ASA, PA, PA-CF, PC,
   TPU, PEEK, PEI, metal-fill, wood-fill, CF composite):
   - Nozzle temperature offset vs. recommended (not vs. brass)
   - Flow rate adjustment
   - Retraction adjustment
   - Any special notes

5. COMPATIBILITY:
   - Which filament types WORK BEST with this nozzle?
   - Which will DESTROY it (list explicitly)?
   - Any known issues (e.g., poor adhesion to certain materials)?

6. PRACTICAL INFO:
   - Typical retail price range (USD)
   - Common brands/manufacturers
   - Best use cases (speed printing, engineering, food-contact, etc)
   - Maintenance requirements, cleaning methods
   - Thread type (M6, MK8, V6 etc.) — NOT needed for settings, but useful metadata

Cite sources explicitly for every temperature and speed value.
Format: structured JSON matching NozzleResearchData schema.
"""


# ── Gemini extraction chain ───────────────────────────────────────────────────

def _get_extractor() -> Any:
    """Return a ChatGoogleGenerativeAI instance for extraction."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model=os.getenv("NOZZLE_RESEARCH_MODEL", "gemini-2.5-flash"),
        temperature=0.2,
    )


async def _search_nozzle(slug: str, name: str) -> list[dict[str, Any]]:
    """Run Tavily search for a nozzle type. Return raw results."""
    try:
        # Prefer new langchain-tavily package; fall back to langchain_community
        try:
            from langchain_tavily import TavilySearch  # type: ignore
            tool = TavilySearch(max_results=8)
        except ImportError:
            from langchain_community.tools.tavily_search import TavilySearchResults
            tool = TavilySearchResults(max_results=8)
        query = f"{name} nozzle 3D printing settings temperature retraction specifications"
        results = await tool.ainvoke({"query": query})
        return results if isinstance(results, list) else []
    except Exception as e:
        log.warning(f"Search failed for {slug}: {e}")
        return []


async def _extract_nozzle_data(
    slug: str, name: str, material: str, diameter: float, search_results: list[dict[str, Any]]
) -> NozzleResearchData | None:
    """Use LLM to extract structured NozzleResearchData from search results."""
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = _get_extractor()
    context = "\n\n".join(
        f"Source: {r.get('url', 'unknown')}\nContent: {r.get('content', '')[:2000]}"
        for r in search_results
    )

    query = _RESEARCH_QUERY_TEMPLATE.format(name=name)
    system = (
        "You are a 3D printing expert extracting structured nozzle specifications. "
        "Return ONLY valid JSON matching the NozzleResearchData schema. "
        "If data is unavailable, use null. Never invent values. "
        "The 'slug' must be exactly: " + slug
    )
    user_msg = f"""
Research query: {query}

Search results:
{context}

Required output: JSON with fields:
slug, name, material, diameter_mm, hardness_hrc, thermal_conductivity_w_mk,
max_temp_c, abrasion_resistance, temp_offset_c, flow_multiplier,
retraction_multiplier, speed_multiplier, pressure_advance_offset,
pro_settings_matrix (dict keyed by filament category),
compatible_filaments (list), damages_from (list), abrasive_filaments_ok,
manufacturer, typical_cost_usd, when_to_use, lifespan_notes,
maintenance_notes, notes, source_url, confidence.
"""

    resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user_msg)])
    raw = resp.content.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(l for l in lines if not l.strip().startswith("```"))

    try:
        import json
        data = json.loads(raw)
        data.setdefault("slug", slug)
        data.setdefault("name", name)
        data.setdefault("material", material)
        data.setdefault("diameter_mm", diameter)
        return NozzleResearchData(**data)
    except Exception as e:
        log.error(f"Extraction failed for {slug}: {e}\nRaw: {raw[:300]}")
        return None


# ── Per-nozzle research pipeline ──────────────────────────────────────────────

@traceable(project_name=_LANGSMITH_PROJECT, run_type="chain", name="nozzle_research_run")
async def research_nozzle(
    slug: str,
    name: str,
    material: str,
    diameter: float,
    dry_run: bool = False,
) -> ResearchRun:
    """Research one nozzle type. Returns a ResearchRun."""
    run = ResearchRun(
        query=f"FDM nozzle specifications: {name}",
        domain="nozzles",
        method="hybrid",
        agent_id="nozzle_pipeline",
    )
    # We need mutable state while building up the run, so we use dicts
    findings: list[ResearchFinding] = []
    sources: list[ResearchSource] = []

    if dry_run:
        log.info(f"[DRY RUN] Would research: {name}")
        return run

    log.info(f"Researching nozzle: {name} ({slug})")

    # Step 1: Search
    search_results = await _search_nozzle(slug, name)
    for r in search_results:
        if url := r.get("url"):
            sources.append(ResearchSource(url=url, source_type="web"))

    # Step 2: Extract
    nozzle_data = await _extract_nozzle_data(slug, name, material, diameter, search_results)
    if not nozzle_data:
        return ResearchRun(
            query=run.query,
            domain="nozzles",
            method="hybrid",
            agent_id="nozzle_pipeline",
            sources=sources,
        )

    # Step 3: Convert to findings
    if nozzle_data.temp_offset_c is not None:
        findings.append(ResearchFinding(
            fact=f"{name}: temperature offset vs brass = {nozzle_data.temp_offset_c:+d}°C",
            confidence=nozzle_data.confidence,
            domain_tag=f"nozzle.{material}.temp_offset",
            entity_type="nozzle",
        ))
    if nozzle_data.abrasion_resistance:
        findings.append(ResearchFinding(
            fact=f"{name}: abrasion resistance = {nozzle_data.abrasion_resistance}",
            confidence=nozzle_data.confidence,
            domain_tag=f"nozzle.{material}.abrasion",
            entity_type="nozzle",
        ))
    if nozzle_data.damages_from:
        findings.append(ResearchFinding(
            fact=f"{name}: damaged by filaments: {', '.join(nozzle_data.damages_from)}",
            confidence=min(nozzle_data.confidence, 0.9),
            domain_tag=f"nozzle.{material}.damages_from",
            entity_type="nozzle",
        ))
    for category, settings in (nozzle_data.pro_settings_matrix or {}).items():
        findings.append(ResearchFinding(
            fact=f"{name} + {category}: {settings}",
            confidence=nozzle_data.confidence * 0.9,
            domain_tag=f"nozzle.{material}.{category.lower()}.settings",
            entity_type="nozzle",
        ))

    learned = [
        f"{name}: {nozzle_data.when_to_use}" if nozzle_data.when_to_use else None,
        f"{name} compatible with: {', '.join(nozzle_data.compatible_filaments)}" if nozzle_data.compatible_filaments else None,
    ]

    final_run = ResearchRun(
        run_id=run.run_id,
        started_at=run.started_at,
        completed_at=datetime.now(timezone.utc),
        query=run.query,
        domain="nozzles",
        method="hybrid",
        agent_id="nozzle_pipeline",
        findings=findings,
        sources=sources,
        learned_facts=[l for l in learned if l],
    )

    # Step 4: Write to BQ
    await _write_nozzle_to_bq(nozzle_data, str(final_run.run_id))

    # Step 5: Write to Cloud SQL if confidence high enough
    if nozzle_data.confidence >= 0.6:
        await _upsert_nozzle_to_sql(nozzle_data)

    return final_run


async def _write_nozzle_to_bq(nozzle: NozzleResearchData, run_id: str) -> None:
    try:
        from services.db.bigquery_client import BigQueryClient
        bq = BigQueryClient()
        await bq.write_nozzle_research(nozzle.model_dump(), run_id=run_id)
    except Exception as e:
        log.warning(f"BQ write failed for {nozzle.slug}: {e}")


async def _upsert_nozzle_to_sql(nozzle: NozzleResearchData) -> None:
    try:
        from services.db.cloud_sql import get_session, upsert_nozzle_type
        data = {
            "slug": nozzle.slug,
            "name": nozzle.name,
            "material": nozzle.material,
            "diameter_mm": nozzle.diameter_mm,
            "hardness_hrc": nozzle.hardness_hrc,
            "thermal_conductivity": nozzle.thermal_conductivity_w_mk,
            "max_temp_c": nozzle.max_temp_c,
            "abrasion_resistance": nozzle.abrasion_resistance,
            "compatible_filaments": nozzle.compatible_filaments or [],
            "abrasive_filaments_ok": nozzle.abrasive_filaments_ok,
            "settings_delta": {
                "temp_offset_c": nozzle.temp_offset_c,
                "flow_multiplier": nozzle.flow_multiplier,
                "retraction_multiplier": nozzle.retraction_multiplier,
                "speed_multiplier": nozzle.speed_multiplier,
                "pressure_advance_offset": nozzle.pressure_advance_offset,
            },
            "pro_settings_matrix": nozzle.pro_settings_matrix,
            "manufacturer": nozzle.manufacturer,
            "typical_cost_usd": nozzle.typical_cost_usd,
            "lifespan_notes": nozzle.lifespan_notes,
            "when_to_use": nozzle.when_to_use,
            "maintenance_notes": nozzle.maintenance_notes,
            "notes": nozzle.notes,
            "research_status": "draft",
        }
        async with get_session() as session:
            await upsert_nozzle_type(session, data)
        log.info(f"Upserted nozzle to Cloud SQL: {nozzle.slug}")
    except Exception as e:
        log.warning(f"Cloud SQL upsert failed for {nozzle.slug}: {e}")


# ── Main orchestrator ─────────────────────────────────────────────────────────

async def run_nozzle_pipeline(
    slugs: list[str] | None = None,
    dry_run: bool = False,
    concurrency: int = 5,
    min_quality_score: float = 0.60,
) -> ResearchReport:
    """
    Run the full nozzle research pipeline.

    - If slugs provided, only research those nozzles.
    - Otherwise, research all nozzles in SEED_NOZZLES.
    - Evaluates each run with ResearchEvaluator.
    - Returns a ResearchReport synthesising all runs.
    """
    target_nozzles = (
        [n for n in SEED_NOZZLES if n[0] in slugs]
        if slugs
        else SEED_NOZZLES
    )

    log.info(f"Nozzle pipeline starting: {len(target_nozzles)} nozzles to research")

    evaluator = ResearchEvaluator()
    semaphore = asyncio.Semaphore(concurrency)

    async def _research_with_sem(nozzle: tuple) -> ResearchRun:
        async with semaphore:
            slug, name, material, diameter, _ = nozzle
            try:
                run = await research_nozzle(slug, name, material, diameter, dry_run=dry_run)
                if not dry_run and run.findings:
                    report = await evaluator.evaluate(run)
                    log.info(f"  {slug}: {report.verdict} (score={report.scores.overall:.2f})")
                return run
            except Exception as e:
                log.error(f"Research failed for {slug}: {e}")
                return ResearchRun(
                    query=f"FDM nozzle: {name}",
                    domain="nozzles",
                    method="hybrid",
                )

    runs = await asyncio.gather(*[_research_with_sem(n) for n in target_nozzles])
    valid_runs = [r for r in runs if r]

    synthesis = (
        f"Researched {len(valid_runs)} nozzle types. "
        f"Total findings: {sum(len(r.findings) for r in valid_runs)}. "
        f"High-confidence findings: {sum(len(r.high_confidence_findings) for r in valid_runs)}."
    )

    return ResearchReport(
        topic="FDM Nozzle Repository",
        domain="nozzles",
        runs=valid_runs,
        synthesis=synthesis,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    os.environ.setdefault("LANGCHAIN_PROJECT", _LANGSMITH_PROJECT)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [nozzle-pipeline] %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    parser = argparse.ArgumentParser(description="QIDIStudio Nozzle Research Pipeline")
    parser.add_argument("--slug", nargs="*", help="Research specific nozzle slugs only")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, no writes")
    parser.add_argument("--concurrency", type=int, default=5, help="Parallel research tasks")
    parser.add_argument("--min-quality", type=float, default=0.60, help="Min eval score to write to SQL")
    args = parser.parse_args()

    report = asyncio.run(run_nozzle_pipeline(
        slugs=args.slug,
        dry_run=args.dry_run,
        concurrency=args.concurrency,
        min_quality_score=args.min_quality,
    ))

    print(f"\nNozzle Pipeline Complete")
    print(f"Runs: {len(report.runs)}")
    print(f"Total findings: {report.total_findings}")
    print(f"Synthesis: {report.synthesis}")


if __name__ == "__main__":
    main()
