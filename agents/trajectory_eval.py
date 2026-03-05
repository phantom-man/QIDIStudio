"""
agents/trajectory_eval.py — Trajectory evaluation for QIDIStudio dev fleet.

Uses agentevals LLM-as-judge to score the quality of coder/tester iteration
trajectories after each team run, tuned specifically for 3D parts development:

  - Did the coder reason correctly about geometry / FFF manufacturing constraints?
  - Did iterations converge efficiently, or thrash on the same failure?
  - Were test failures diagnosed precisely and each fix targeted?
  - Was retrieved LanceDB semantic memory actually applied?
  - Is the final artefact appropriate for a production 3D slicer / CAD pipeline?

Scores are attached to TeamResult["eval"] and submitted as LangSmith run feedback
so they appear on every run's detail page in the LangSmith UI.

Usage (called automatically by dev_fleet._run_team_loop):

    from agents.trajectory_eval import evaluate_team_trajectory
    eval_result = evaluate_team_trajectory(team_name, task, history, final_status)
    # → {"score": True, "reasoning": "...", "convergence_rate": 0.8, "iterations": 2}

Manual invocation for debugging:

    memory_env\\Scripts\\python.exe -m agents.trajectory_eval \\
        --task "Fix the lead screw pitch model" \\
        --history agents/_fleet_alpha_out.txt
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate

REPO_ROOT = Path(__file__).parents[1]
load_dotenv(REPO_ROOT / ".env", override=True)

# ── Domain-specific judge prompt ──────────────────────────────────────────────

_SYSTEM = """\
You are an expert trajectory evaluator for an AI-powered 3D parts development pipeline.
You are reviewing the step-by-step work (trajectory) of an AI coder/tester agent team
that is iteratively developing software for 3D part design, FFF/FDM manufacturing, and
CNC machining simulation.

Evaluate the trajectory holistically across these five dimensions:

1. MANUFACTURING CORRECTNESS
   Did the coder reason correctly about 3D geometry, FFF print constraints (overhangs,
   layer adhesion, support structures, tolerances), or CNC machining parameters where
   relevant to the task? Were domain-specific constraints respected?

2. CONVERGENCE EFFICIENCY
   Did the team converge toward a solution without thrashing? An ideal run either passes
   on the first iteration or makes clear, targeted improvements each round. Oscillating
   failures (same error repeating across iterations) indicate poor diagnosis.

3. DIAGNOSTIC PRECISION
   Were test failures (if any) accurately diagnosed? Did each new iteration address the
   root cause rather than patching symptoms? Did the tester's failure reports give enough
   signal for focused repairs?

4. CONTEXT APPLICATION
   Was the retrieved LanceDB semantic memory (project context, past learnings, architectural
   decisions) actually reflected in the implementation? Generic solutions that ignore
   project-specific context should score lower.

5. PRODUCTION READINESS
   Is the final artefact (code, schema, algorithm) appropriate for a production 3D slicer /
   CAD pipeline? Does it handle edge cases (e.g. zero-thickness walls, degenerate meshes,
   singular matrices) that are common in real 3D part data?

YOUR RESPONSE MUST be a JSON object with EXACTLY these fields:
{
  "score": true | false,          // overall pass (true) or fail (false) judgment
  "reasoning": "...",             // 2-4 sentences justifying the score
  "manufacturing_correctness": 0.0 to 1.0,
  "convergence_efficiency": 0.0 to 1.0,
  "diagnostic_precision": 0.0 to 1.0,
  "context_application": 0.0 to 1.0,
  "production_readiness": 0.0 to 1.0
}

Be strict. A trajectory that converges by luck without demonstrating sound reasoning
should score false even if the final test passes.
"""

_HUMAN = """\
TASK: {task}

TEAM: {team_name}
FINAL STATUS: {final_status}
ITERATIONS COMPLETED: {iterations_completed}

TRAJECTORY:
{trajectory_text}
"""

_JUDGE_PROMPT = ChatPromptTemplate.from_messages(
    [("system", _SYSTEM), ("human", _HUMAN)]
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _history_to_messages(task: str, history: list[dict]) -> list[Any]:
    """
    Convert dev_fleet history list → LangChain message sequence for agentevals.

    Format:
      HumanMessage  — original task
      AIMessage     — coder output (code_signal_preview) per iteration
      ToolMessage   — tester verdict (test_outcome JSON) per iteration
    """
    msgs: list[Any] = [HumanMessage(content=task)]
    for entry in history:
        i = entry.get("iteration", "?")
        code_output = entry.get("code_signal_preview", "")
        test_result = entry.get("test_outcome", {})
        status = entry.get("status", "UNKNOWN")

        msgs.append(AIMessage(content=f"[Iteration {i} — Coder]\n{code_output}"))
        msgs.append(
            ToolMessage(
                content=f"[Iteration {i} — Tester — {status}]\n{json.dumps(test_result, indent=2)}",
                tool_call_id=f"test_iter_{i}",
            )
        )
    return msgs


def _history_to_text(history: list[dict]) -> str:
    """Human-readable trajectory summary for the custom judge prompt."""
    lines: list[str] = []
    for entry in history:
        i = entry.get("iteration", "?")
        status = entry.get("status", "?")
        summary = entry.get("summary", "")
        lines.append(f"--- Iteration {i} ({status}) ---")
        if summary:
            lines.append(f"Summary: {summary}")
        failures = entry.get("test_outcome", {}).get("failures", [])
        if failures:
            for f in failures[:3]:  # cap at 3 to avoid token bloat
                lines.append(
                    f"  FAIL: {f.get('test_name','?')} — {f.get('coder_hint','')}"
                )
        code_preview = entry.get("code_signal_preview", "")
        if code_preview:
            lines.append(f"Coder output preview:\n{code_preview[:400]}")
        lines.append("")
    return "\n".join(lines)


def _convergence_rate(history: list[dict], final_status: str) -> float:
    """Simple convergence metric: 1.0 = passed on iter 1, decays with iterations."""
    n = len(history)
    if n == 0:
        return 0.0
    if final_status == "PASS":
        # Passed on iteration n: rate = 1 / n
        return round(1.0 / n, 3)
    return 0.0


# ── Core evaluator ────────────────────────────────────────────────────────────


def _build_judge_llm():
    """Lazy-import Gemini judge model (avoids import cost when module is not used)."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0,
        google_api_key=os.environ.get("GOOGLE_API_KEY"),
    ).with_structured_output(method="json_mode")


async def _run_agentevals(task: str, history: list[dict]) -> dict:
    """
    Use agentevals create_trajectory_llm_as_judge as a secondary cross-check.
    Returns the raw agentevals verdict dict, or {} if unavailable.
    """
    try:
        from agentevals import (  # type: ignore[import]
            TRAJECTORY_ACCURACY_PROMPT,
            create_trajectory_llm_as_judge,
        )
        from langchain_google_genai import ChatGoogleGenerativeAI

        judge_model = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0,
            google_api_key=os.environ.get("GOOGLE_API_KEY"),
        )
        evaluator = create_trajectory_llm_as_judge(
            model=judge_model,
            prompt=TRAJECTORY_ACCURACY_PROMPT,
        )
        messages = _history_to_messages(task, history)
        result = await evaluator(inputs={"task": task}, outputs=messages)
        return result or {}
    except Exception as exc:
        return {"agentevals_error": str(exc)}


def evaluate_team_trajectory(
    team_name: str,
    task: str,
    history: list[dict],
    final_status: str,
) -> dict:
    """
    Evaluate the quality of a single team's coder/tester trajectory.

    Returns a dict:
    {
        "score": bool,
        "reasoning": str,
        "manufacturing_correctness": float,
        "convergence_efficiency": float,
        "diagnostic_precision": float,
        "context_application": float,
        "production_readiness": float,
        "convergence_rate": float,   # computed metric (not LLM)
        "iterations": int,
        "agentevals": dict,          # raw agentevals verdict (may have agentevals_error key)
    }
    """
    if not history:
        return {
            "score": False,
            "reasoning": "No iteration history — cannot evaluate.",
            "convergence_rate": 0.0,
            "iterations": 0,
            "agentevals": {},
        }

    trajectory_text = _history_to_text(history)
    convergence_rate = _convergence_rate(history, final_status)

    # ── Custom domain judge ───────────────────────────────────────────────────
    domain_result: dict = {}
    try:
        judge = _build_judge_llm()
        prompt_value = _JUDGE_PROMPT.invoke(
            {
                "task": task,
                "team_name": team_name,
                "final_status": final_status,
                "iterations_completed": len(history),
                "trajectory_text": trajectory_text,
            }
        )
        raw = judge.invoke(prompt_value)
        if isinstance(raw, dict):
            domain_result = raw
        elif isinstance(raw, str):
            domain_result = json.loads(raw)
    except Exception as exc:
        domain_result = {"domain_eval_error": str(exc)}

    # ── agentevals cross-check (async) ────────────────────────────────────────
    try:
        agentevals_result = asyncio.run(_run_agentevals(task, history))
    except RuntimeError:
        # Already inside an event loop (e.g. Jupyter / LangGraph async context)
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _run_agentevals(task, history))
            agentevals_result = future.result(timeout=60)
    except Exception as exc:
        agentevals_result = {"agentevals_error": str(exc)}

    return {
        "score": bool(domain_result.get("score", False)),
        "reasoning": domain_result.get("reasoning", ""),
        "manufacturing_correctness": float(
            domain_result.get("manufacturing_correctness", 0.0)
        ),
        "convergence_efficiency": float(
            domain_result.get("convergence_efficiency", 0.0)
        ),
        "diagnostic_precision": float(domain_result.get("diagnostic_precision", 0.0)),
        "context_application": float(domain_result.get("context_application", 0.0)),
        "production_readiness": float(domain_result.get("production_readiness", 0.0)),
        "convergence_rate": convergence_rate,
        "iterations": len(history),
        "agentevals": agentevals_result,
    }


def submit_langsmith_feedback(
    run_id: str | None,
    eval_result: dict,
    team_name: str,
) -> None:
    """
    Push trajectory eval scores as LangSmith run feedback so they appear
    in the run detail page and are queryable via the LangSmith API.
    """
    if not run_id:
        return
    try:
        from langsmith import Client

        client = Client(api_key=os.environ.get("LANGSMITH_API_KEY"))

        score_map = {
            "trajectory_score": 1.0 if eval_result.get("score") else 0.0,
            "manufacturing_correctness": eval_result.get(
                "manufacturing_correctness", 0.0
            ),
            "convergence_efficiency": eval_result.get("convergence_efficiency", 0.0),
            "diagnostic_precision": eval_result.get("diagnostic_precision", 0.0),
            "context_application": eval_result.get("context_application", 0.0),
            "production_readiness": eval_result.get("production_readiness", 0.0),
            "convergence_rate": eval_result.get("convergence_rate", 0.0),
        }

        for key, score in score_map.items():
            client.create_feedback(
                run_id=run_id,
                key=f"{team_name.lower()}_{key}",
                score=score,
                comment=eval_result.get("reasoning", ""),
                source_info={"evaluator": "qidistudio-trajectory-eval"},
            )
    except Exception as exc:
        # Feedback submission is best-effort — never crash the main pipeline
        print(
            f"[trajectory_eval] LangSmith feedback submission failed: {exc}",
            file=sys.stderr,
        )


# ── CLI (for debugging / standalone runs) ────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate a dev fleet team trajectory")
    parser.add_argument("--task", required=True, help="Task string")
    parser.add_argument(
        "--history",
        required=True,
        help="Path to JSON file containing the history list, or _fleet_*_out.txt",
    )
    parser.add_argument("--team", default="Alpha", help="Team name")
    parser.add_argument("--status", default="PASS", help="Final status")
    args = parser.parse_args()

    history_path = Path(args.history)
    raw = json.loads(history_path.read_text(encoding="utf-8"))
    # Accept either a raw history list or the full TeamResult dict
    history_data: list[dict] = raw if isinstance(raw, list) else raw.get("history", [])

    result = evaluate_team_trajectory(args.team, args.task, history_data, args.status)
    print(json.dumps(result, indent=2))
