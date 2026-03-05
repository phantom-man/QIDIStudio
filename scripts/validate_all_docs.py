"""
validate_all_docs.py
====================
Batch validator — runs every .md (and other supported) document in docs/
through knowledge_validator.py and aggregates all found hallucinations into:

  docs/HALLUCINATION_REPORT.md          — human-readable markdown report
  docs/hallucinations.json              — machine-readable aggregated data

Usage:
  memory_env\\Scripts\\python.exe scripts\\validate_all_docs.py [--docs-dir docs] [--no-llm]

Outputs per document  (auto-created by knowledge_validator.py):
  docs/<doc>_validated.md
  docs/<doc>.validation.json

Progress is written to stdout in real time.
Failed documents are logged but do not abort the run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time

# Ensure emoji / UTF-8 output works on Windows cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime
from pathlib import Path

# Load .env so GOOGLE_API_KEY is available for LLM claim extraction
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env", override=False)
except ImportError:
    pass  # python-dotenv not installed; rely on env vars already being set

# Allow importing from scripts/ when running from repo root
sys.path.insert(0, str(Path(__file__).parent))

from knowledge_validator import KnowledgeValidator, ValidationReport

log = logging.getLogger("validate_all_docs")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Skip list — index / log / meta files that contain no factual claims
# ---------------------------------------------------------------------------
SKIP_FILES = {
    "QIDISTUDIO_KNOWLEDGE.md",
    "DOCS_OVERHAUL_LOG.md",
    "HALLUCINATION_REPORT.md",
    "3D_Viewer_Code_Review_Report.md",
    "CPP_MODERNIZATION_SCORE.md",
    "AGENT_PROTOCOL.md",
    "AGENT_MEMORY_WIRING.md",
    "DESKTOP_COMMANDER_MCP.md",
    "displacement-texture-research.md",
}

SUPPORTED_EXTENSIONS = {
    ".md",
    ".txt",
    ".rst",
    ".tex",
    ".html",
    ".htm",
    ".pdf",
    ".docx",
    ".json",
    ".csv",
    ".py",
    ".cpp",
}

# Persistent checksum log — records SHA-256 of every validated doc so we
# can skip re-validating unchanged files on subsequent runs.
CHECKSUM_LOG_PATH = Path("logs") / "validation_checksums.log"


# ---------------------------------------------------------------------------
# Checksum helpers
# ---------------------------------------------------------------------------


def _file_sha256(path: Path) -> str:
    """Return the hex-encoded SHA-256 digest of a file's bytes."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _load_checksum_log(log_path: Path) -> dict:
    """Load the persistent checksum log, returning an empty dict on any error."""
    if log_path.exists():
        try:
            return json.loads(log_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning(
                "Could not parse checksum log (%s) — starting fresh: %s", log_path, exc
            )
    return {}


def _save_checksum_log(log_data: dict, log_path: Path) -> None:
    """Atomically persist the checksum log to disk."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps(log_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Fix-only mode — apply corrections from existing .validation.json files
# without any network / LLM calls.
# ---------------------------------------------------------------------------


def apply_fixes_only(docs_dir: Path) -> None:
    """
    Read every ``<doc>.validation.json`` in *docs_dir*, apply the stored
    corrected text for each flagged verdict back to the source document,
    write the result as ``<doc>_validated.md``, and record the new SHA-256
    in the persistent checksum log.

    No network calls are made — this just replays previously-computed
    corrections.
    """
    checksum_log = _load_checksum_log(CHECKSUM_LOG_PATH)
    fixed_count = 0
    skipped_count = 0
    clean_count = 0

    json_paths = sorted(docs_dir.glob("*.validation.json"))
    if not json_paths:
        print("No .validation.json files found — run full validation first.")
        return

    log.info("Fix-only mode: processing %d .validation.json files", len(json_paths))

    for json_path in json_paths:
        # json_path.stem strips only ".json", leaving ".validation" — strip the full suffix manually
        doc_stem = json_path.name.replace(
            ".validation.json", ""
        )  # e.g. "3D Printing Physics-Informed Function"
        doc_path = docs_dir / f"{doc_stem}.md"

        if not doc_path.exists():
            log.warning("  Source doc not found for %s — skipping", json_path.name)
            skipped_count += 1
            continue

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.error("  Cannot read %s: %s", json_path.name, exc)
            skipped_count += 1
            continue

        verdicts_to_fix = [v for v in data.get("verdicts", []) if v.get("corrected")]

        if not verdicts_to_fix:
            clean_count += 1
            sha = _file_sha256(doc_path)
            checksum_log.setdefault(doc_path.name, {}).update(
                {
                    "sha256": sha,
                    "validated_at": datetime.now().isoformat(),
                    "claims": data.get("claims", 0),
                    "corrections": 0,
                    "hallucinations": 0,
                    "flag": "✅ clean",
                }
            )
            log.info("  CLEAN (no corrections needed): %s", doc_stem)
            continue

        source_text = doc_path.read_text(encoding="utf-8", errors="replace")
        corrected_text = source_text
        applied = 0

        for v in verdicts_to_fix:
            sentence = v.get("sentence", "")
            corrected = v.get("corrected", "")
            if sentence and corrected and sentence in corrected_text:
                corrected_text = corrected_text.replace(sentence, corrected, 1)
                applied += 1
            else:
                log.debug(
                    "  Sentence not found verbatim in %s — skipping verdict", doc_stem
                )

        validated_path = doc_path.with_name(f"{doc_stem}_validated.md")
        validated_path.write_text(corrected_text, encoding="utf-8")

        sha = _file_sha256(doc_path)
        checksum_log[doc_path.name] = {
            "sha256": sha,
            "validated_at": datetime.now().isoformat(),
            "claims": data.get("claims", 0),
            "corrections": data.get("corrections", 0),
            "hallucinations": data.get("hallucinations", 0),
            "flag": f"🔧 fixed ({applied}/{len(verdicts_to_fix)} corrections applied)",
        }

        if applied > 0:
            log.info(
                "  FIXED (%d/%d corrections): %s → %s",
                applied,
                len(verdicts_to_fix),
                doc_stem,
                validated_path.name,
            )
            fixed_count += 1
        else:
            log.warning(
                "  No sentences matched verbatim in %s — _validated.md written unchanged",
                doc_stem,
            )
            skipped_count += 1

    _save_checksum_log(checksum_log, CHECKSUM_LOG_PATH)
    log.info("Checksum log updated: %s", CHECKSUM_LOG_PATH)

    print("\n" + "=" * 70)
    print(f"FIX-ONLY COMPLETE")
    print(f"  🔧 Fixed   : {fixed_count}")
    print(f"  ✅ Clean   : {clean_count}")
    print(f"  ⏭ Skipped : {skipped_count}")
    print(f"\nChecksum log: {CHECKSUM_LOG_PATH}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------


def run_batch(
    docs_dir: Path,
    use_llm: bool = True,
    confidence_threshold: float = 0.60,
) -> None:
    docs = sorted(
        p
        for p in docs_dir.iterdir()
        if p.suffix.lower() in SUPPORTED_EXTENSIONS
        and p.name not in SKIP_FILES
        and not p.name.endswith("_validated.md")
        and not p.name.endswith(".validation.json")
    )

    total = len(docs)
    log.info("Found %d documents to validate in %s", total, docs_dir)

    validator = KnowledgeValidator(use_llm_extraction=use_llm)
    validator.UNCERTAINTY_THRESHOLD = confidence_threshold

    all_hallucinations: list[dict] = []
    report_rows: list[dict] = []  # per-doc summary row
    failed_docs: list[str] = []

    # Load persistent checksum log — docs with matching hashes are skipped.
    checksum_log = _load_checksum_log(CHECKSUM_LOG_PATH)
    skipped_unchanged = 0

    t0_total = time.monotonic()

    for idx, doc_path in enumerate(docs, start=1):
        short = doc_path.name

        # ------------------------------------------------------------------
        # Checksum gate — skip docs that haven't changed since last validate
        # ------------------------------------------------------------------
        current_sha = _file_sha256(doc_path)
        cached = checksum_log.get(short)
        if cached and cached.get("sha256") == current_sha:
            log.info(
                "[%d/%d] SKIP (sha256 match, unchanged): %s",
                idx,
                total,
                short,
            )
            # Replay cached row into report so totals stay accurate
            report_rows.append(
                {
                    "doc": short,
                    "claims": cached.get("claims", 0),
                    "corrections": cached.get("corrections", 0),
                    "hallucinations": cached.get("hallucinations", 0),
                    "flag": cached.get("flag", "✅ clean (cached)"),
                    "elapsed": 0.0,
                }
            )
            skipped_unchanged += 1
            continue

        log.info("[%d/%d] Validating: %s", idx, total, short)
        t0 = time.monotonic()

        try:
            report = validator.validate(doc_path)
        except Exception as exc:
            log.error("  FAILED: %s — %s", short, exc)
            failed_docs.append(f"{short}: {exc}")
            continue

        elapsed = time.monotonic() - t0

        # Write corrected doc + JSON report
        if report.correction_count > 0:
            report.write_corrected()
        report.write_json_report()

        # Collect hallucinations
        doc_hallucinations = [
            {
                "doc": short,
                "claim": v.claim.text,
                "sentence": v.claim.sentence,
                "confidence": round(v.confidence, 3),
                "claim_type": v.claim.claim_type,
                "corrected": v.corrected_text,
                "sources": [e.source_url for e in v.evidence[:2]],
            }
            for v in report.verdicts
            if v.needs_correction
        ]
        all_hallucinations.extend(doc_hallucinations)

        row_flag = ""
        if report.hallucination_count:
            row_flag = f"🔴 {report.hallucination_count} hallucination(s)"
        elif report.correction_count:
            row_flag = f"🟡 {report.correction_count} uncertain claim(s)"
        else:
            row_flag = "✅ clean"

        row = {
            "doc": short,
            "claims": len(report.verdicts),
            "corrections": report.correction_count,
            "hallucinations": report.hallucination_count,
            "flag": row_flag,
            "elapsed": round(elapsed, 1),
        }
        report_rows.append(row)

        # Update checksum log after every validated doc
        checksum_log[short] = {
            "sha256": current_sha,
            "validated_at": datetime.now().isoformat(),
            "claims": len(report.verdicts),
            "corrections": report.correction_count,
            "hallucinations": report.hallucination_count,
            "flag": row_flag,
        }
        _save_checksum_log(checksum_log, CHECKSUM_LOG_PATH)

        log.info(
            "  → %s  [%d claims, %d⚑ corrections, %.1fs]",
            row_flag,
            len(report.verdicts),
            report.correction_count,
            elapsed,
        )

    if skipped_unchanged:
        log.info("Skipped %d unchanged docs (checksum match).", skipped_unchanged)

    total_elapsed = time.monotonic() - t0_total

    # -------------------------------------------------------------------
    # Write aggregated JSON
    # -------------------------------------------------------------------
    agg_json_path = docs_dir / "hallucinations.json"
    agg_data = {
        "run_timestamp": datetime.now().isoformat(),
        "docs_scanned": total,
        "docs_failed": len(failed_docs),
        "total_hallucinations": sum(r["hallucinations"] for r in report_rows),
        "total_corrections": sum(r["corrections"] for r in report_rows),
        "elapsed_seconds": round(total_elapsed, 1),
        "hallucinations": all_hallucinations,
        "per_doc": report_rows,
        "failed": failed_docs,
    }
    agg_json_path.write_text(
        json.dumps(agg_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Aggregated JSON written: %s", agg_json_path)

    # -------------------------------------------------------------------
    # Write human-readable markdown report
    # -------------------------------------------------------------------
    md_path = docs_dir / "HALLUCINATION_REPORT.md"
    _write_markdown_report(
        md_path, agg_data, report_rows, all_hallucinations, failed_docs
    )
    log.info("Markdown report written: %s", md_path)

    # -------------------------------------------------------------------
    # Final summary to stdout
    # -------------------------------------------------------------------
    total_h = agg_data["total_hallucinations"]
    total_c = agg_data["total_corrections"]
    print("\n" + "=" * 70)
    print(f"VALIDATION COMPLETE — {total} docs in {total_elapsed:.0f}s")
    print(f"  🔴 Hallucinations : {total_h}")
    print(f"  🟡 Uncertain      : {total_c - total_h}")
    print(
        f"  ✅ Clean docs     : {sum(1 for r in report_rows if r['corrections'] == 0)}"
    )
    print(f"  ❌ Failed         : {len(failed_docs)}")
    print(f"\nSee: {md_path}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Markdown report writer
# ---------------------------------------------------------------------------


def _write_markdown_report(
    path: Path,
    agg: dict,
    rows: list[dict],
    hallucinations: list[dict],
    failed: list[str],
) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []

    # Header
    lines += [
        "# Knowledge Base Hallucination Report",
        "",
        f"> **Generated:** {ts}  ",
        f"> **Docs scanned:** {agg['docs_scanned']}  ",
        f"> **Total hallucinations / uncertain claims:** "
        f"{agg['total_hallucinations']} / {agg['total_corrections']}  ",
        f"> **Validation engine:** `scripts/knowledge_validator.py`  ",
        f"> **Sources:** CrossRef (0.92) · arXiv (0.90) · PubMed (0.91) · "
        f"MathWorld (0.93) · NIST (0.95) · Semantic Scholar (0.88) · "
        f"Wikipedia (0.72) · Tavily (0.70)",
        "",
        "---",
        "",
    ]

    # Per-doc summary table
    lines += [
        "## Per-Document Summary",
        "",
        "| # | Document | Claims | Corrections | Hallucinations | Status | Time |",
        "| - | -------- | ------:| ----------: | -------------: | ------ | ---: |",
    ]
    for i, row in enumerate(rows, 1):
        lines.append(
            f"| {i} | [{row['doc']}]({row['doc']}) "
            f"| {row['claims']} | {row['corrections']} "
            f"| {row['hallucinations']} | {row['flag']} | {row['elapsed']}s |"
        )
    lines += ["", "---", ""]

    # Hallucination detail
    lines += [
        "## Hallucination Detail",
        "",
        "_Claims with confidence < 0.40 (directly false or completely unverifiable):_",
        "",
    ]

    h_only = [h for h in hallucinations if h["confidence"] < 0.40]
    u_only = [h for h in hallucinations if 0.40 <= h["confidence"] < 0.60]

    if not h_only and not u_only:
        lines.append(
            "**No hallucinations or uncertain claims found. All documents are clean.**"
        )
    else:
        if h_only:
            lines += [
                f"### 🔴 Hallucinations ({len(h_only)} total)",
                "",
            ]
            current_doc = ""
            for h in sorted(h_only, key=lambda x: x["doc"]):
                if h["doc"] != current_doc:
                    current_doc = h["doc"]
                    lines += [f"#### `{current_doc}`", ""]
                lines += [
                    f"- **Claim** (conf={h['confidence']}, type={h['claim_type']}):  ",
                    f"  > {h['sentence']}",
                ]
                if h.get("corrected"):
                    lines += [
                        f"  **Corrected:** {h['corrected']}",
                    ]
                if h.get("sources"):
                    src_links = " · ".join(f"[source]({s})" for s in h["sources"] if s)
                    if src_links:
                        lines.append(f"  **Evidence:** {src_links}")
                lines.append("")

        if u_only:
            lines += [
                f"### 🟡 Uncertain Claims ({len(u_only)} total — confidence 0.40–0.59)",
                "",
            ]
            current_doc = ""
            for h in sorted(u_only, key=lambda x: (x["doc"], x["confidence"])):
                if h["doc"] != current_doc:
                    current_doc = h["doc"]
                    lines += [f"#### `{current_doc}`", ""]
                lines += [
                    f"- **Claim** (conf={h['confidence']}, type={h['claim_type']}):  ",
                    f"  > {h['sentence']}",
                ]
                if h.get("corrected"):
                    lines.append(f"  **Corrected:** {h['corrected']}")
                lines.append("")

    lines += ["", "---", ""]

    # Failed docs
    if failed:
        lines += [
            f"## Failed Documents ({len(failed)})",
            "",
        ]
        for f_entry in failed:
            lines.append(f"- `{f_entry}`")
        lines += ["", "---", ""]

    # Footer
    lines += [
        "## How to Use This Report",
        "",
        "1. For each 🔴 entry: open the `_validated.md` version of the doc and review the correction.",
        "2. For each 🟡 entry: add a primary source citation or reword to hedge the claim.",
        "3. Re-run: `memory_env\\Scripts\\python.exe scripts\\validate_all_docs.py`",
        "4. When this report shows all ✅: commit `docs/` with message `docs: resolve hallucinations`.",
        "",
        "```powershell",
        "# Quick single-doc re-validation",
        "memory_env\\Scripts\\python.exe scripts\\knowledge_validator.py docs\\<YourDoc>.md",
        "```",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> None:
    parser = argparse.ArgumentParser(
        prog="validate_all_docs",
        description="Batch-validate every document in docs/ and produce a hallucination report.",
    )
    parser.add_argument(
        "--docs-dir",
        default="docs",
        help="Directory containing knowledge documents (default: docs)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable Gemini LLM; use regex claim extraction only",
    )
    parser.add_argument(
        "--threshold",
        "-t",
        type=float,
        default=0.60,
        help="Confidence threshold for flagging (default: 0.60)",
    )
    parser.add_argument(
        "--fix-only",
        action="store_true",
        help=(
            "Apply corrections from existing .validation.json files without "
            "re-validating against external sources. Uses the persistent checksum "
            "log to track which docs have been fixed."
        ),
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    docs_dir = Path(args.docs_dir)
    if not docs_dir.is_dir():
        print(f"Error: docs directory not found: {docs_dir}", file=sys.stderr)
        sys.exit(2)

    if args.fix_only:
        apply_fixes_only(docs_dir=docs_dir)
    else:
        run_batch(
            docs_dir=docs_dir,
            use_llm=not args.no_llm,
            confidence_threshold=args.threshold,
        )


if __name__ == "__main__":
    _cli()
