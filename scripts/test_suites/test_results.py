"""
scripts/test_suites/test_results.py — Persistent test result model.

Every test result (PASS / FAIL / SKIP / BLOCKED) is recorded to:
  1. PostgreSQL table `phd_test_results`  — structured, queryable
  2. LanceDB documents table             — semantic retrieval
  3. logs/phd_test_runs/*.jsonl           — local immutable append-only log

Schema (Postgres):
  id           SERIAL PRIMARY KEY
  run_id       TEXT      — UUID of the test-pipeline invocation
  group_id     TEXT      — A–I
  test_id      TEXT      — e.g. "A.nl_slicer_import"
  test_name    TEXT      — human-readable
  status       TEXT      — PASS | FAIL | SKIP | BLOCKED
  duration_s   FLOAT     — wall-clock seconds
  error_msg    TEXT      — NULL on PASS
  fix_attempt  INTEGER   — rectification attempt number (0 = first run)
  artifact     TEXT      — path to screenshot / log / output file, if any
  created_at   TIMESTAMPTZ DEFAULT now()
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[2]
load_dotenv(REPO_ROOT / ".env", override=True)

RUNS_DIR = REPO_ROOT / "logs" / "phd_test_runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

Status = Literal["PASS", "FAIL", "SKIP", "BLOCKED"]

# ── DDL (run once at startup) ─────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS phd_test_results (
    id          SERIAL PRIMARY KEY,
    run_id      TEXT        NOT NULL,
    group_id    TEXT        NOT NULL,
    test_id     TEXT        NOT NULL,
    test_name   TEXT        NOT NULL,
    status      TEXT        NOT NULL,
    duration_s  FLOAT       NOT NULL DEFAULT 0,
    error_msg   TEXT,
    fix_attempt INTEGER     NOT NULL DEFAULT 0,
    artifact    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ptr_run     ON phd_test_results(run_id);
CREATE INDEX IF NOT EXISTS idx_ptr_group   ON phd_test_results(group_id);
CREATE INDEX IF NOT EXISTS idx_ptr_status  ON phd_test_results(status);
"""

_pg_ready = False


def _ensure_pg_table() -> bool:
    global _pg_ready
    if _pg_ready:
        return True
    try:
        import psycopg2

        dsn = os.environ.get("PG_DSN", "postgresql://postgres:d1204l0723@localhost:5432/postgres")
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(_DDL)
        cur.close()
        conn.close()
        _pg_ready = True
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[test_results] Postgres not available: {exc}")
        return False


# ── Dataclass ─────────────────────────────────────────────────────────────────


@dataclass
class TestResult:
    group_id: str
    test_id: str
    test_name: str
    status: Status = "PASS"
    duration_s: float = 0.0
    error_msg: str | None = None
    fix_attempt: int = 0
    artifact: str | None = None
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # ── convenience ──────────────────────────────────────────────────────────

    @classmethod
    def from_exception(
        cls,
        group_id: str,
        test_id: str,
        test_name: str,
        exc: Exception,
        fix_attempt: int = 0,
        run_id: str | None = None,
    ) -> "TestResult":
        r = cls(
            group_id=group_id,
            test_id=test_id,
            test_name=test_name,
            status="FAIL",
            error_msg=str(exc)[:4000],
            fix_attempt=fix_attempt,
        )
        if run_id:
            r.run_id = run_id
        return r

    # ── persistence ──────────────────────────────────────────────────────────

    def save(self) -> None:
        """Write to Postgres (best-effort) + local JSONL."""
        self._save_jsonl()
        self._save_pg()

    def _save_jsonl(self) -> None:
        log_path = RUNS_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(self)) + "\n")

    def _save_pg(self) -> None:
        if not _ensure_pg_table():
            return
        try:
            import psycopg2

            dsn = os.environ.get("PG_DSN", "postgresql://postgres:d1204l0723@localhost:5432/postgres")
            conn = psycopg2.connect(dsn)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO phd_test_results
                    (run_id, group_id, test_id, test_name, status,
                     duration_s, error_msg, fix_attempt, artifact, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self.run_id,
                    self.group_id,
                    self.test_id,
                    self.test_name,
                    self.status,
                    self.duration_s,
                    self.error_msg,
                    self.fix_attempt,
                    self.artifact,
                    self.created_at,
                ),
            )
            cur.close()
            conn.close()
        except Exception as exc:  # noqa: BLE001
            print(f"[test_results] Postgres write error: {exc}")


# ── Run-level summary ─────────────────────────────────────────────────────────


@dataclass
class RunSummary:
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    results: list[TestResult] = field(default_factory=list)
    total_elapsed_s: float = 0.0

    def add(self, result: TestResult) -> None:
        result.run_id = self.run_id
        self.results.append(result)
        result.save()

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def blocked(self) -> int:
        return sum(1 for r in self.results if r.status == "BLOCKED")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == "SKIP")

    def failures(self) -> list[TestResult]:
        return [r for r in self.results if r.status in ("FAIL", "BLOCKED")]

    def print_summary(self) -> None:
        width = 72
        print("=" * width)
        print(f"  PHD TEST PIPELINE  run_id={self.run_id[:8]}")
        print("=" * width)
        for r in self.results:
            icon = {"PASS": "✅", "FAIL": "❌", "BLOCKED": "🚫", "SKIP": "⏭"}.get(r.status, "?")
            err_snippet = f"  → {r.error_msg[:80]}" if r.error_msg else ""
            fix_tag = f" [fix#{r.fix_attempt}]" if r.fix_attempt > 0 else ""
            print(f"  {icon} [{r.group_id}] {r.test_id:<40s} {r.duration_s:6.2f}s{fix_tag}{err_snippet}")
        print("-" * width)
        print(
            f"  TOTAL={self.total}  PASS={self.passed}  FAIL={self.failed}"
            f"  BLOCKED={self.blocked}  SKIP={self.skipped}"
        )
        print("=" * width)

    def to_lancedb_summary(self) -> str:
        """Return a text summary suitable for LanceDB upsert."""
        return (
            f"PHD test run {self.run_id} started {self.started_at}. "
            f"Results: {self.passed}/{self.total} PASS, {self.failed} FAIL, "
            f"{self.blocked} BLOCKED, {self.skipped} SKIP. "
            f"Failed tests: {[r.test_id for r in self.failures()]}."
        )


# ── Top-level persist helper ─────────────────────────────────────────────────


def persist_results(summary: RunSummary) -> None:
    """
    Persist a completed RunSummary to:
      1. Postgres phd_test_results (already done per-result via TestResult.save)
      2. A summary JSONL entry in logs/phd_test_runs/
      3. LanceDB documents table (best-effort) for semantic retrieval
    """
    # ── JSONL summary entry ────────────────────────────────────────────────────
    summary_path = RUNS_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
    summary_record = {
        "type": "run_summary",
        "run_id": summary.run_id,
        "started_at": summary.started_at,
        "total": summary.total,
        "passed": summary.passed,
        "failed": summary.failed,
        "blocked": summary.blocked,
        "skipped": summary.skipped,
        "total_elapsed_s": summary.total_elapsed_s,
        "failed_tests": [r.test_id for r in summary.failures()],
    }
    with open(summary_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary_record) + "\n")

    # ── LanceDB upsert (best-effort) ──────────────────────────────────────────
    try:
        import lancedb

        uri = os.environ.get("LANCEDB_PATH", "gs://qidistudio-lancedb/lancedb")
        db = lancedb.connect(uri)
        if "documents" in db.table_names():
            tbl = db.open_table("documents")
            tbl.add([{
                "source_file": f"phd_test_run/{summary.run_id}",
                "text": summary.to_lancedb_summary(),
                "category": "test_run",
            }])
    except Exception as exc:  # noqa: BLE001
        print(f"[test_results] LanceDB summary upsert skipped: {exc}")


# ── Timer context manager ─────────────────────────────────────────────────────


class Timer:
    """with Timer() as t: ...; t.elapsed → duration in seconds."""

    def __enter__(self) -> "Timer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *_: object) -> None:
        self.elapsed: float = time.monotonic() - self._start
