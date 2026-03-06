#!/usr/bin/env python3
"""
PHD Test Pipeline — Autonomous Verification System
====================================================
Iterates through all completed QIDIStudio / NexusSlicer master-plan tasks,
verified against 9 test groups (A–I). Any failure is autonomously
dispatched to the RectificationAgent for up to 3 fix attempts before
being marked BLOCKED.

Usage:
    memory_env\\Scripts\\python.exe -B scripts/phd_test_pipeline.py
    memory_env\\Scripts\\python.exe -B scripts/phd_test_pipeline.py --groups A,B,I
    memory_env\\Scripts\\python.exe -B scripts/phd_test_pipeline.py --dry-run
    memory_env\\Scripts\\python.exe -B scripts/phd_test_pipeline.py --no-rectify

Exit codes:
    0  All tests PASS
    1  One or more FAIL or BLOCKED
    2  Startup error (environment not ready)
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from pathlib import Path

# ── Force UTF-8 stdout (Windows terminal code-page workaround) ────────────────
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# ── Bootstrap ─────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env", override=True)

# ── Imports from test infrastructure ──────────────────────────────────────────

from scripts.test_suites.test_results import TestResult, RunSummary, Timer, persist_results
from scripts.test_suites.rectification_agent import RectificationAgent

from scripts.test_suites.test_group_a_imports   import run_group_a, TESTS as TESTS_A
from scripts.test_suites.test_group_b_agents    import run_group_b, TESTS as TESTS_B
from scripts.test_suites.test_group_c_pipelines import run_group_c, TESTS as TESTS_C
from scripts.test_suites.test_group_d_typescript import run_group_d, TESTS as TESTS_D
from scripts.test_suites.test_group_e_cpp       import run_group_e, TESTS as TESTS_E
from scripts.test_suites.test_group_f_vision    import run_group_f, TESTS as TESTS_F
from scripts.test_suites.test_group_g_database  import run_group_g, TESTS as TESTS_G
from scripts.test_suites.test_group_h_api       import run_group_h, TESTS as TESTS_H
from scripts.test_suites.test_group_i_assets    import run_group_i

# ── Group registry ────────────────────────────────────────────────────────────

GROUP_RUNNERS: dict[str, tuple[str, callable]] = {
    "A": ("Python Import / Smoke Tests",           run_group_a),
    "B": ("Agent Fleet Functional Tests",          run_group_b),
    "C": ("Pipeline End-to-End Tests",             run_group_c),
    "D": ("TypeScript / VS Code Extension Tests",  run_group_d),
    "E": ("C++ / CMake Build Gate Tests",          run_group_e),
    "F": ("Vision / Aesthetic Tests",              run_group_f),
    "G": ("Database Integrity Tests",              run_group_g),
    "H": ("API Connectivity Tests",                run_group_h),
    "I": ("File / Asset Existence Tests",          run_group_i),
}

# Tests that typically require hardware (Vulkan/SYCL) — skipped unless --include-hardware
HARDWARE_GATED_TESTS = {
    "D.tsc_compile",   # requires node_modules populated
    "D.npm_test",      # requires display or headed Electron
}


# ── Logging helpers ───────────────────────────────────────────────────────────

def _banner(msg: str, width: int = 72) -> None:
    print()
    print("═" * width)
    print(f"  {msg}")
    print("═" * width)


def _section(msg: str) -> None:
    print(f"\n  ── {msg} " + "─" * max(1, 60 - len(msg)))


# ── Core pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(
    groups: list[str] | None = None,
    dry_run: bool = False,
    no_rectify: bool = False,
    include_hardware: bool = False,
    run_id: str | None = None,
) -> RunSummary:
    """
    Execute the full PhD test pipeline.

    Parameters
    ----------
    groups          : Restrict to these group letters. None = all groups.
    dry_run         : Skip all real external calls (prints plan only).
    no_rectify      : Disable RectificationAgent (fail = BLOCKED immediately).
    include_hardware: Include hardware-gated tests that normally require GPU.
    run_id          : Override the auto-generated run UUID.
    """
    import uuid
    _run_id = run_id or str(uuid.uuid4())[:8]

    selected_groups = [g.upper() for g in (groups or list(GROUP_RUNNERS.keys()))]
    # Validate
    invalid = [g for g in selected_groups if g not in GROUP_RUNNERS]
    if invalid:
        raise ValueError(f"Unknown group letters: {invalid}. Valid: A–I")

    rectifier = RectificationAgent(dry_run=dry_run)
    summary = RunSummary(run_id=_run_id)

    _banner(f"PHD TEST PIPELINE  run={_run_id}  groups={','.join(selected_groups)}")
    print(f"  dry_run={dry_run}  no_rectify={no_rectify}  include_hardware={include_hardware}")
    print(f"  groups to execute: {len(selected_groups)} × {sum(len(list(GROUP_RUNNERS.items())) for _ in [1])} total available")

    t_total_start = time.monotonic()

    for group_id in selected_groups:
        label, runner_fn = GROUP_RUNNERS[group_id]
        _section(f"Group {group_id} — {label}")

        with Timer() as group_timer:
            try:
                raw_results: list[dict] = runner_fn() if not dry_run else _dry_run_results(group_id)
            except Exception as exc:
                # Catastrophic group-level failure
                print(f"    ✗ Group {group_id} crashed: {exc}")
                summary.add(TestResult(
                    group_id=group_id,
                    test_id=f"{group_id}.CRASH",
                    test_name=f"Group {group_id} runner crashed",
                    status="BLOCKED",
                    duration_s=0.0,
                    error_msg=str(exc)[:500],
                    run_id=_run_id,
                ))
                continue

        for r in raw_results:
            test_id = r["test_id"]
            test_name = r["test_name"]
            passed = r["passed"]
            error = r.get("error")

            # ── Hardware gate ──────────────────────────────────────────────────
            if test_id in HARDWARE_GATED_TESTS and not include_hardware:
                status = "SKIP"
                print(f"    ⊘ SKIP  {test_id:<44s} (hardware-gated)")
                summary.add(TestResult(
                    group_id=group_id,
                    test_id=test_id,
                    test_name=test_name,
                    status="SKIP",
                    duration_s=0.0,
                    run_id=_run_id,
                ))
                continue

            # ── First pass result ──────────────────────────────────────────────
            if passed:
                print(f"    ✅ PASS  {test_id:<44s}")
                summary.add(TestResult(
                    group_id=group_id,
                    test_id=test_id,
                    test_name=test_name,
                    status="PASS",
                    duration_s=r.get("duration_s", 0.0),
                    run_id=_run_id,
                ))
                continue

            # ── Failure path ───────────────────────────────────────────────────
            print(f"    ❌ FAIL  {test_id:<44s}")
            if error:
                preview = error[:120].replace("\n", " ↵ ")
                print(f"            error: {preview}")

            if no_rectify or dry_run:
                summary.add(TestResult(
                    group_id=group_id,
                    test_id=test_id,
                    test_name=test_name,
                    status="BLOCKED",
                    duration_s=r.get("duration_s", 0.0),
                    error_msg=error,
                    run_id=_run_id,
                ))
                continue

            # ── Rectification loop ─────────────────────────────────────────────
            print(f"    ↻ Dispatching rectification agent for {test_id}…")

            # We need a callable for rectifier.attempt_fix — wrap the group runner
            # to return just this test's result.
            def _retest_fn(
                _group_id=group_id,
                _test_id=test_id,
                _runner=runner_fn,
            ) -> bool:
                try:
                    results = _runner()
                    for rr in results:
                        if rr["test_id"] == _test_id:
                            return rr["passed"]
                    return False
                except Exception:
                    return False

            rectified, rect_error, attempt_count = rectifier.attempt_fix(
                group_id=group_id,
                test_id=test_id,
                test_name=test_name,
                error_msg=error or "",
                test_func=_retest_fn,
            )

            final_status = "PASS" if rectified else "BLOCKED"
            icon = "✅" if rectified else "🔴"
            print(f"    {icon} {final_status}  {test_id} (after {attempt_count} fix attempt(s))")

            summary.add(TestResult(
                group_id=group_id,
                test_id=test_id,
                test_name=test_name,
                status=final_status,
                duration_s=r.get("duration_s", 0.0),
                error_msg=rect_error,
                fix_attempt=attempt_count,
                run_id=_run_id,
            ))

    total_elapsed = time.monotonic() - t_total_start
    summary.total_elapsed_s = total_elapsed

    # ── Final report ──────────────────────────────────────────────────────────
    summary.print_summary()
    persist_results(summary)

    return summary


# ── Dry-run helper ────────────────────────────────────────────────────────────

def _dry_run_results(group_id: str) -> list[dict]:
    """Return mock PASS results for every test in the group (dry-run mode)."""
    runners_map = {
        "A": TESTS_A, "B": TESTS_B, "C": TESTS_C,
        "D": TESTS_D, "E": TESTS_E,
        "F": TESTS_F, "G": TESTS_G, "H": TESTS_H,
    }
    if group_id not in runners_map:
        return []  # Group I has no TESTS list (dynamic)
    tests = runners_map[group_id]
    return [
        {
            "group_id": group_id,
            "test_id": t[0],
            "test_name": t[1],
            "passed": True,
            "error": None,
            "duration_s": 0.0,
        }
        for t in tests
    ]


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="PhD Test Pipeline — autonomous verification of all completed tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -B scripts/phd_test_pipeline.py
  python -B scripts/phd_test_pipeline.py --groups A,B,I
  python -B scripts/phd_test_pipeline.py --groups H
  python -B scripts/phd_test_pipeline.py --dry-run
  python -B scripts/phd_test_pipeline.py --no-rectify
        """,
    )
    p.add_argument(
        "--groups",
        default=None,
        help="Comma-separated group letters to run (default: all A–I). Example: A,B,I",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip all real API/subprocess calls; print plan only (all tests report PASS)",
    )
    p.add_argument(
        "--no-rectify",
        action="store_true",
        help="Disable RectificationAgent; failures → BLOCKED immediately",
    )
    p.add_argument(
        "--include-hardware",
        action="store_true",
        help="Include hardware-gated tests that require GPU/display (npm test, tsc etc.)",
    )
    p.add_argument(
        "--run-id",
        default=None,
        help="Override the auto-generated run UUID (for deterministic test runs)",
    )
    return p


def main() -> int:
    parser = _build_argparser()
    args = parser.parse_args()

    groups: list[str] | None = None
    if args.groups:
        groups = [g.strip().upper() for g in args.groups.split(",") if g.strip()]

    try:
        summary = run_pipeline(
            groups=groups,
            dry_run=args.dry_run,
            no_rectify=args.no_rectify,
            include_hardware=args.include_hardware,
            run_id=args.run_id,
        )
    except ValueError as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        return 2

    failures = [r for r in summary.results if r.status in ("FAIL", "BLOCKED")]
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
