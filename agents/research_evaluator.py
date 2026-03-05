"""
agents/research_evaluator.py — Research quality evaluation agent.

Uses the research_evaluator prompt (agents/prompts/research_evaluator.md) to
evaluate structured research outputs produced by the researcher agent or any
pipeline that produces ResearchRun objects.

The evaluator is an LLM-as-judge: it receives structured research data and
returns a scored ResearchEvalReport with PASS/FAIL/NEEDS_IMPROVEMENT verdict.

Integration:
  - Called by filament_pipeline.py after each research run
  - Called by nozzle_pipeline.py after each nozzle research session
  - Results written to BigQuery `research_quality_evals` table
  - Runs with their own LangSmith project: qidistudio-manufacturing

Usage:
    from agents.research_evaluator import ResearchEvaluator

    evaluator = ResearchEvaluator()
    report = await evaluator.evaluate(run)
    print(report.verdict)  # "PASS" | "FAIL" | "NEEDS_IMPROVEMENT"
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import uuid
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from langsmith import traceable

from schemas.research_data import (
    KnowledgeGap,
    ResearchEvalReport,
    ResearchEvalScores,
    ResearchRun,
)

load_dotenv()
log = logging.getLogger(__name__)

_PROMPT_PATH = pathlib.Path(__file__).parent / "prompts" / "research_evaluator.md"
_LANGSMITH_PROJECT = "qidistudio-manufacturing"


class ResearchEvaluator:
    """
    LLM-as-judge evaluator for research runs.

    Backed by Gemini 2.5 Flash (fast, cheap for evaluation tasks).
    Falls back to Gemini 1.5 Pro if Flash is unavailable.
    """

    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.1,   # Low temp for deterministic scoring
    ) -> None:
        self.model = model or os.getenv("EVAL_MODEL", "gemini-2.5-flash")
        self.temperature = temperature
        self._prompt: str | None = None
        self._llm: Any | None = None

    def _load_prompt(self) -> str:
        if self._prompt is None:
            self._prompt = _PROMPT_PATH.read_text(encoding="utf-8")
        return self._prompt

    def _get_llm(self) -> Any:
        if self._llm is None:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
            except ImportError as e:
                raise RuntimeError(
                    "langchain-google-genai not installed. "
                    "Run: pip install langchain-google-genai"
                ) from e
            self._llm = ChatGoogleGenerativeAI(
                model=self.model,
                temperature=self.temperature,
                convert_system_message_to_human=False,
            )
        return self._llm

    def _build_eval_payload(self, run: ResearchRun | dict[str, Any]) -> str:
        """Serialise the research run to a JSON string for the evaluator prompt."""
        if hasattr(run, "model_dump"):
            data = run.model_dump(mode="json")
        else:
            data = dict(run)
        # Include only the fields the evaluator needs (keep token count manageable)
        payload = {
            "run_id": str(data.get("run_id", "")),
            "domain": data.get("domain", ""),
            "query": data.get("query", ""),
            "agent_id": data.get("agent_id", ""),
            "findings": data.get("findings", []),
            "sources": [
                {k: v for k, v in s.items() if k in ("url", "source_type", "title")}
                for s in data.get("sources", [])
            ],
            "knowledge_gaps": data.get("knowledge_gaps", []),
            "learned_facts": data.get("learned_facts", []),
        }
        return json.dumps(payload, indent=2, default=str)

    @traceable(project_name=_LANGSMITH_PROJECT, run_type="chain", name="research_evaluator")
    async def evaluate(
        self,
        run: ResearchRun | dict[str, Any],
    ) -> ResearchEvalReport:
        """
        Evaluate a research run. Returns a ResearchEvalReport.

        Writes the evaluation to BigQuery automatically if WRITE_EVAL_TO_BQ=true.
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        system_prompt = self._load_prompt()
        eval_payload = self._build_eval_payload(run)

        llm = self._get_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Evaluate this research run:\n\n{eval_payload}"),
        ]

        log.info(f"Evaluating research run {run.run_id if hasattr(run, 'run_id') else '?'}")

        response = await llm.ainvoke(messages)
        raw_output = response.content.strip()

        # Strip markdown code fences if present
        if raw_output.startswith("```"):
            lines = raw_output.splitlines()
            raw_output = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            )

        try:
            eval_data = json.loads(raw_output)
        except json.JSONDecodeError as e:
            log.error(f"Evaluator produced invalid JSON: {e}\nRaw output:\n{raw_output[:500]}")
            # Return a fail-safe report
            run_id = run.run_id if hasattr(run, "run_id") else uuid.uuid4()
            return ResearchEvalReport(
                run_id=run_id,
                domain=run.domain if hasattr(run, "domain") else "unknown",
                scores=ResearchEvalScores(
                    source_quality=0.0,
                    completeness=0.0,
                    accuracy=0.0,
                    consistency=0.0,
                    actionability=0.0,
                    overall=0.0,
                ),
                verdict="FAIL",
                improvements=[f"Evaluator error: {e}"],
            )

        # Parse scores
        scores_raw = eval_data.get("scores", {})
        scores = ResearchEvalScores(
            source_quality=float(scores_raw.get("source_quality", 0)),
            completeness=float(scores_raw.get("completeness", 0)),
            accuracy=float(scores_raw.get("accuracy", 0)),
            consistency=float(scores_raw.get("consistency", 0)),
            actionability=float(scores_raw.get("actionability", 0)),
            overall=float(scores_raw.get("overall", 0)),
        )

        # Parse gaps
        gaps = [
            KnowledgeGap(
                description=g.get("description", ""),
                importance=g.get("importance", "medium"),
                suggested_query=g.get("suggested_query"),
                domain_tag=g.get("domain_tag"),
            )
            for g in eval_data.get("gaps_found", [])
        ]

        run_id = uuid.UUID(eval_data.get("run_id", str(uuid.uuid4())))
        report = ResearchEvalReport(
            eval_id=uuid.UUID(eval_data.get("eval_id", str(uuid.uuid4()))),
            run_id=run_id,
            domain=eval_data.get("domain", ""),
            scores=scores,
            verdict=eval_data.get("verdict", "FAIL"),
            gaps_found=gaps,
            improvements=eval_data.get("improvements", []),
            evaluator_notes=eval_data.get("evaluator_notes"),
        )

        # Optional BQ write
        if os.getenv("WRITE_EVAL_TO_BQ", "true").lower() == "true":
            await self._write_to_bq(report)

        log.info(
            f"Eval complete: verdict={report.verdict} overall={scores.overall:.2f}"
        )
        return report

    async def _write_to_bq(self, report: ResearchEvalReport) -> None:
        try:
            from services.db.bigquery_client import BigQueryClient
            bq = BigQueryClient()
            await bq.write_eval_report(report)
        except Exception as e:
            log.warning(f"BQ eval write failed (non-fatal): {e}")

    def evaluate_sync(self, run: ResearchRun | dict[str, Any]) -> ResearchEvalReport:
        """Synchronous wrapper for non-async callers."""
        import asyncio
        return asyncio.run(self.evaluate(run))
