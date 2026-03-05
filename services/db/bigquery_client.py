"""
services/db/bigquery_client.py — BigQuery write/read helpers for research data.

All agent research runs are written to BigQuery first (append-only audit trail),
then validated data is promoted to Cloud SQL.

Environment variables:
    GOOGLE_CLOUD_PROJECT    GCP project ID (e.g. crafty-hook-483415-b3)
    BQ_DATASET              BigQuery dataset (default: qidistudio_research)
    GOOGLE_APPLICATION_CREDENTIALS  Path to service account JSON (or use ADC)

Usage:
    from services.db.bigquery_client import BigQueryClient

    bq = BigQueryClient()
    await bq.write_research_run(run)
    rows = await bq.read_latest_runs(domain="filaments", limit=10)
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv()

_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "crafty-hook-483415-b3")
_DATASET = os.getenv("BQ_DATASET", "qidistudio_research")


class BigQueryClient:
    """
    Async-friendly wrapper around the BigQuery Python client.

    All I/O is run in a thread pool executor so it doesn't block the asyncio loop.
    BigQuery's official client is synchronous — this wrapper handles that transparently.
    """

    def __init__(
        self,
        project: str = _PROJECT,
        dataset: str = _DATASET,
    ) -> None:
        self.project = project
        self.dataset = dataset
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from google.cloud import bigquery
            except ImportError as e:
                raise RuntimeError(
                    "google-cloud-bigquery not installed. "
                    "Run: pip install google-cloud-bigquery"
                ) from e
            self._client = bigquery.Client(project=self.project)
        return self._client

    def _table_ref(self, table_id: str) -> str:
        return f"{self.project}.{self.dataset}.{table_id}"

    async def _run_sync(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking function in the default thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    # ── Dataset bootstrap ────────────────────────────────────────────────────

    async def ensure_dataset(self) -> None:
        """Create the BigQuery dataset if it doesn't exist. Idempotent."""
        from google.cloud import bigquery
        from google.cloud.exceptions import Conflict

        client = self._get_client()
        ds = bigquery.Dataset(f"{self.project}.{self.dataset}")
        ds.location = "US"

        def _create() -> None:
            try:
                client.create_dataset(ds, exists_ok=True)
            except Conflict:
                pass

        await self._run_sync(_create)

    async def ensure_tables(self) -> None:
        """Create all tables from bigquery_schema.json if they don't exist."""
        import pathlib

        schema_path = pathlib.Path(__file__).parent / "bigquery_schema.json"
        schema_doc = json.loads(schema_path.read_text())
        client = self._get_client()

        from google.cloud import bigquery

        def _create_table(table_def: dict[str, Any]) -> None:
            table_id = self._table_ref(table_def["table_id"])
            schema = [
                bigquery.SchemaField(
                    name=f["name"],
                    field_type=f["type"],
                    mode=f.get("mode", "NULLABLE"),
                    description=f.get("description", ""),
                )
                for f in table_def["schema"]
            ]
            table = bigquery.Table(table_id, schema=schema)

            # Time partitioning
            if "time_partitioning" in table_def:
                tp = table_def["time_partitioning"]
                table.time_partitioning = bigquery.TimePartitioning(
                    type_=tp["type"],
                    field=tp.get("field"),
                )

            # Clustering
            if "clustering_fields" in table_def:
                table.clustering_fields = table_def["clustering_fields"]

            client.create_table(table, exists_ok=True)

        for table_def in schema_doc["tables"]:
            await self._run_sync(_create_table, table_def)

    # ── Research run writes ───────────────────────────────────────────────────

    async def write_research_run(self, run: Any) -> str:
        """
        Write a ResearchRun (Pydantic model) to BigQuery raw_research_runs table.
        Returns the BQ insert ID (uuid).

        Accepts either a ResearchRun instance or a plain dict.
        """
        if hasattr(run, "model_dump"):
            data = run.model_dump(mode="json")
        else:
            data = dict(run)

        insert_id = str(uuid.uuid4())
        row = {
            "run_id": str(data.get("run_id", insert_id)),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "domain": data.get("domain", "unknown"),
            "query": data.get("query", ""),
            "agent_id": data.get("agent_id"),
            "method": data.get("method", "hybrid"),
            "raw_output": json.dumps(data),
            "findings": json.dumps(
                [f if isinstance(f, dict) else f for f in data.get("findings", [])]
            ),
            "sources": json.dumps(data.get("sources", [])),
            "quality_score": data.get("quality_score"),
            "eval_report": (
                json.dumps(data.get("eval_report")) if data.get("eval_report") else None
            ),
            "status": data.get("status", "draft"),
            "duration_secs": data.get("duration_secs"),
        }

        await self._stream_rows("raw_research_runs", [row], [insert_id])
        return insert_id

    async def write_filament_scrape(
        self, scrape: dict[str, Any], run_id: str | None = None
    ) -> str:
        """Write a raw filament scrape record to BigQuery."""
        insert_id = str(uuid.uuid4())
        row = {
            "scrape_id": insert_id,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "manufacturer_name": scrape.get("manufacturer_name", ""),
            "manufacturer_slug": scrape.get("manufacturer_slug", ""),
            "product_name": scrape.get("product_name", ""),
            "product_slug": scrape.get("product_slug", ""),
            "category": scrape.get("category"),
            "source_url": scrape.get("source_url"),
            "source_type": scrape.get("source_type", "web"),
            "raw_data": json.dumps(scrape.get("raw_data", {})),
            "normalized_data": json.dumps(scrape.get("normalized_data", {})),
            "confidence": scrape.get("confidence"),
            "amazon_rating": scrape.get("amazon_rating"),
            "amazon_review_count": scrape.get("amazon_review_count"),
            "asin": scrape.get("asin"),
        }
        await self._stream_rows("raw_filament_scrapes", [row], [insert_id])
        return insert_id

    async def write_nozzle_research(
        self, nozzle: dict[str, Any], run_id: str | None = None
    ) -> str:
        """Write a raw nozzle research record to BigQuery."""
        insert_id = str(uuid.uuid4())
        row = {
            "research_id": insert_id,
            "researched_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "nozzle_slug": nozzle.get("slug", ""),
            "nozzle_name": nozzle.get("name", ""),
            "material": nozzle.get("material", ""),
            "diameter_mm": nozzle.get("diameter_mm", 0.4),
            "source_url": nozzle.get("source_url"),
            "raw_data": json.dumps(nozzle.get("raw_data", {})),
            "settings_delta": json.dumps(nozzle.get("settings_delta", {})),
            "pro_settings_matrix": json.dumps(nozzle.get("pro_settings_matrix", {})),
            "confidence": nozzle.get("confidence"),
            "quality_score": nozzle.get("quality_score"),
        }
        await self._stream_rows("raw_nozzle_research", [row], [insert_id])
        return insert_id

    async def write_eval_report(self, report: Any) -> str:
        """Write a ResearchEvalReport to BigQuery."""
        if hasattr(report, "model_dump"):
            data = report.model_dump(mode="json")
        else:
            data = dict(report)

        insert_id = str(uuid.uuid4())
        scores = data.get("scores", {})
        row = {
            "eval_id": insert_id,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": str(data.get("run_id", "")),
            "domain": data.get("domain", ""),
            "overall_score": scores.get("overall"),
            "source_quality": scores.get("source_quality"),
            "completeness": scores.get("completeness"),
            "accuracy": scores.get("accuracy"),
            "consistency": scores.get("consistency"),
            "actionability": scores.get("actionability"),
            "gaps_found": json.dumps(data.get("gaps_found", [])),
            "improvements": json.dumps(data.get("improvements", [])),
            "verdict": data.get("verdict", "FAIL"),
            "full_report": json.dumps(data),
        }
        await self._stream_rows("research_quality_evals", [row], [insert_id])
        return insert_id

    # ── Read helpers ──────────────────────────────────────────────────────────

    async def read_latest_runs(
        self,
        domain: str | None = None,
        limit: int = 20,
        min_quality: float | None = None,
    ) -> list[dict[str, Any]]:
        """Read latest research runs from BigQuery. Returns list of dicts."""
        conditions = []
        if domain:
            conditions.append(f"domain = '{domain}'")
        if min_quality is not None:
            conditions.append(f"quality_score >= {min_quality}")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT run_id, domain, query, agent_id, quality_score, status, ingested_at
            FROM `{self._table_ref("raw_research_runs")}`
            {where}
            ORDER BY ingested_at DESC
            LIMIT {limit}
        """
        return await self._run_query(query)

    async def read_manufacturer_scrapes(
        self, manufacturer_slug: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        query = f"""
            SELECT *
            FROM `{self._table_ref("raw_filament_scrapes")}`
            WHERE manufacturer_slug = '{manufacturer_slug}'
            ORDER BY scraped_at DESC
            LIMIT {limit}
        """
        return await self._run_query(query)

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _stream_rows(
        self,
        table_id: str,
        rows: list[dict[str, Any]],
        insert_ids: list[str] | None = None,
    ) -> None:
        client = self._get_client()
        table_ref = self._table_ref(table_id)

        def _insert() -> list[Any]:
            return client.insert_rows_json(
                table_ref,
                rows,
                row_ids=insert_ids,
            )

        errors = await self._run_sync(_insert)
        if errors:
            raise RuntimeError(f"BigQuery insert errors for {table_id}: {errors}")

    async def _run_query(self, query: str) -> list[dict[str, Any]]:
        client = self._get_client()

        def _q() -> list[dict[str, Any]]:
            job = client.query(query)
            return [dict(row) for row in job.result()]

        return await self._run_sync(_q)

    async def health_check(self) -> bool:
        """Return True if BigQuery is reachable."""
        try:
            await self._run_query(
                f"SELECT 1 FROM `{self.project}.{self.dataset}.raw_research_runs` LIMIT 1"
            )
            return True
        except Exception:
            return False
