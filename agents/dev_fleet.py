"""
agents/dev_fleet.py — Named Coder/Tester team fleet for QIDIStudio.

Architecture: Parallel named teams (Alpha, Beta, Gamma), each running a
coder→tester iteration loop. Teams can work on independent sub-tasks of the
same request, or compete on the same task.

Flow per team:
  prime (inject LanceDB semantic memories)
    └─ coder (PhD-level implementation, produces code_signal JSON)
         └─ [AgentComms signal: code_ready]
              └─ tester (Gemini Vision + test runner, produces test_outcome JSON)
                   ├─ PASS    → scribe (persist learnings) → DONE
                   ├─ FAIL    → coder (iterate, max 5 rounds)
                   └─ ESCALATE→ scribe (persist blocker) → DONE

Global flow:
  START → plan_teams → dispatch (Send API, true parallel) → [Alpha|Beta|Gamma] → report → END

Key features:
  - PHD-level coder agent primed from LanceDB semantic memory
  - Tester uses Gemini Vision (gemini-2.5-pro multimodal) for visual artifact analysis
  - AgentComms signaling via LangGraph state: code_signal → test_outcome
  - Scribe persists all learnings to LanceDB after every team completes
  - Postgres checkpointer: each team gets unique thread_id for resumable state
  - Full LangSmith tracing under project 'qidistudio-dev-fleet'

Usage:
    # CLI — dispatch to all teams in parallel
    memory_env\\Scripts\\python.exe -B agents/dev_fleet.py "Implement [task here]"

    # With specific teams and iteration cap
    memory_env\\Scripts\\python.exe -B agents/dev_fleet.py "task" --teams Alpha Beta --max-iter 3

    # Python API
    from agents.dev_fleet import run_fleet
    result = run_fleet("Implement X", teams=["Alpha", "Beta"])
    print(result["final_report"])

Output files (per run):
    agents/_fleet_alpha_out.txt
    agents/_fleet_beta_out.txt
    agents/_fleet_gamma_out.txt
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from textwrap import dedent
from typing import Annotated, Any, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from langsmith import traceable
from typing_extensions import NotRequired

# ── Env ───────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parents[1]
load_dotenv(REPO_ROOT / ".env", override=True)

os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
os.environ.setdefault("LANGCHAIN_PROJECT", "qidistudio-dev-fleet")

_GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "crafty-hook-483415-b3")
_GCP_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

# Named teams — fixed roster, extensible
TEAM_NAMES = ["Alpha", "Beta", "Gamma"]
MAX_ITERATIONS_DEFAULT = 5


# ── State schemas ─────────────────────────────────────────────────────────────


class TeamTask(TypedDict):
    team_name: str  # "Alpha" | "Beta" | "Gamma"
    task: str  # specific sub-task for this team
    max_iterations: int  # iteration cap, default 5


class TeamResult(TypedDict):
    team_name: str
    task: str
    iterations_completed: int
    final_status: str  # "PASS" | "FAIL" | "ESCALATED" | "EXHAUSTED"
    history: list[dict]  # iteration-by-iteration record
    lancedb_written: bool
    eval: NotRequired[dict]  # trajectory eval scores from trajectory_eval.py
    error: NotRequired[str]


def _merge_results(left: list, right: list) -> list:
    return left + right


class FleetState(TypedDict):
    user_request: str
    max_iterations: int
    team_tasks: list[TeamTask]
    team_results: Annotated[list[TeamResult], _merge_results]
    final_report: NotRequired[str]


class SingleTeamState(TypedDict):
    """State passed to each parallel team node via Send."""

    team_task: TeamTask


# ── Director LLM ─────────────────────────────────────────────────────────────


def _director_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.0,
        project=_GCP_PROJECT,
        location=_GCP_LOCATION,
    )


_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "team_tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "team_name": {"type": "string", "enum": TEAM_NAMES},
                    "task": {"type": "string"},
                    "max_iterations": {"type": "integer"},
                },
                "required": ["team_name", "task"],
            },
        },
    },
    "required": ["team_tasks"],
}

_PLAN_SYSTEM = dedent(
    """
    You are the fleet director for the QIDIStudio dev fleet.
    Decompose the user request into sub-tasks, one per named team (Alpha, Beta, Gamma).

    Rules:
    - Assign at most one task per team.
    - If the request has only one concern, assign it to Alpha only.
    - If the request has N independent concerns (N ≤ 3), fan them out across teams.
    - If the request is ambiguous, assign to Alpha and mark it clearly.
    - default max_iterations is 5; reduce to 2 for trivial changes, raise to 7 for hard problems.

    Output strict JSON matching the schema.
"""
).strip()


# ── Semantic memory injection ─────────────────────────────────────────────────


def _query_lancedb(query: str, n: int = 8) -> str:
    """Pull top-N relevant memories from LanceDB. Returns formatted string."""
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from memory.store import query_similar

        rows = query_similar(query, n=n)
        if not rows:
            return "(no relevant memories found)"
        lines = []
        for r in rows:
            topic = r.get("topic", "")
            decision = r.get("decision", "")
            content = (r.get("content") or decision)[:400]
            lines.append(f"• [{topic}] {decision}\n  {content}")
        return "\n\n".join(lines)
    except Exception as exc:
        return f"(LanceDB unavailable: {exc})"


def _persist_team_learnings(team_name: str, task: str, history: list[dict]) -> bool:
    """Write team iteration learnings to LanceDB. Returns True on success."""
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from memory.store import upsert

        # Persist the per-team learning summary
        final_iter = history[-1] if history else {}
        status = final_iter.get("status", "UNKNOWN")
        iterations = len(history)
        content = json.dumps(
            {
                "team": team_name,
                "task": task,
                "iterations": iterations,
                "history": history,
            },
            indent=2,
        )
        upsert(
            topic=f"dev-fleet-{team_name.lower()}: {task[:60]}",
            decision=f"{status} after {iterations} iterations",
            content=content,
            source=f"agents/dev_fleet.py:team_{team_name.lower()}",
            category="DevFleet",
        )
        return True
    except Exception as exc:
        print(
            f"[dev_fleet] LanceDB write failed for {team_name}: {exc}", file=sys.stderr
        )
        return False


# ── Agent invocation helpers ──────────────────────────────────────────────────


def _extract_last_ai_message(response: Any) -> str:
    """Extract final AI message content from a create_react_agent response dict."""
    msgs = response.get("messages", [])
    last = next(
        (m for m in reversed(msgs) if getattr(m, "type", None) == "ai"),
        None,
    )
    if last is None:
        return str(response)
    content = getattr(last, "content", "")
    # Handle list-of-dict content (Gemini multimodal response)
    if isinstance(content, list):
        parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
        return "\n".join(parts)
    return str(content)


def _safe_parse_json(text: str) -> dict:
    """Try to parse JSON from agent output; return raw dict on failure."""
    # Strip markdown code fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract JSON object from prose response
        import re

        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {
            "status": "FAIL",
            "summary": cleaned[:500],
            "next_action": "fix_and_retry",
        }


def _build_coder_prompt(
    task: str,
    semantic_context: str,
    prior_failure: str | None,
    iteration: int,
    team_name: str,
) -> str:
    """Build the enriched coder prompt with semantic memory and failure context."""
    parts = [
        f"## Team {team_name} — Coding Task (Iteration {iteration})",
        "",
        f"**Task:** {task}",
        "",
        "## Semantic Memory (from LanceDB — read this before touching any file)",
        semantic_context,
    ]
    if prior_failure and iteration > 1:
        parts += [
            "",
            f"## Prior Test Failure (Iteration {iteration - 1})",
            "The Tester ran your previous code and reported this failure.",
            "Study it carefully before writing new code — do NOT repeat the same approach.",
            "",
            prior_failure,
            "",
            "## Instructions",
            "1. Re-read the relevant files from scratch (your mental model may be stale).",
            "2. Address EVERY failure in `failures[]` from the test outcome.",
            "3. Pay special attention to each `coder_hint` — it's the Tester's diagnosis.",
            "4. Produce your code changes and the test_instructions for the Tester.",
        ]
    else:
        parts += [
            "",
            "## Instructions",
            "1. Use `memory_read` for any additional context before touching files.",
            "2. Use `file_read` to confirm current content before any edit.",
            "3. Use `write_file` to apply your changes.",
            "4. Produce your code changes and `test_instructions` for the Tester.",
            "5. Your final JSON response MUST include `test_instructions.command`.",
        ]
    return "\n".join(parts)


def _build_tester_prompt(
    team_name: str,
    code_signal: str,
    iteration: int,
    semantic_context: str,
) -> str:
    """Build the tester prompt with code signal and semantic context."""
    return dedent(
        f"""
        ## Team {team_name} — Testing Round {iteration}

        The Coder has produced the following code changes and test instructions.
        Run the tests, analyze all output, and return your structured TestOutcome JSON.

        ## Semantic Memory (LanceDB — check for known failure patterns first)
        {semantic_context}

        ## Coder's Output
        {code_signal}

        ## Instructions
        1. Call `memory_read` with a query about this type of code change first.
        2. Run the test command via `run_tests(command, output_file="agents/_test_out_{team_name.lower()}_{iteration}.txt")`.
        3. Read the full output file with `file_read` if the inline preview is truncated.
        4. If `test_instructions.visual_check` is set, call `read_image(path, question)`.
        5. Return your TestOutcome JSON with team="{team_name}", iteration={iteration}.
        6. Every failure MUST have a specific `coder_hint` — diagnose the root cause.
    """
    ).strip()


# ── Team iteration loop ───────────────────────────────────────────────────────


@traceable(
    name="team-run",
    tags=["dev-fleet"],
    metadata={"environment": "dev", "project": "qidistudio"},
)
def _run_team_loop(team_name: str, task: str, max_iterations: int) -> TeamResult:
    """
    Core iteration loop for a single named team.
    coder → tester → (pass | iterate | escalate) → scribe
    """
    from agents.agents import get_agent

    print(f"[{team_name}] Starting: {task[:80]}", flush=True)

    # Prime with semantic memory — shared context for both coder and tester
    semantic_context = _query_lancedb(task)

    history: list[dict] = []
    prior_failure: str | None = None
    final_status = "EXHAUSTED"
    error: str | None = None

    coder_agent = get_agent("coder")
    tester_agent = get_agent("tester")

    for iteration in range(1, max_iterations + 1):
        print(
            f"[{team_name}] Iteration {iteration}/{max_iterations} — coding...",
            flush=True,
        )

        # ── Coder pass ────────────────────────────────────────────────────────
        coder_prompt = _build_coder_prompt(
            task, semantic_context, prior_failure, iteration, team_name
        )
        try:
            coder_response = coder_agent.invoke(
                {"messages": [HumanMessage(content=coder_prompt)]}
            )
            code_signal = _extract_last_ai_message(coder_response)
        except Exception as exc:
            error = f"Coder crashed on iteration {iteration}: {exc}"
            print(f"[{team_name}] CODER ERROR: {exc}", file=sys.stderr, flush=True)
            history.append(
                {"iteration": iteration, "status": "CODER_ERROR", "error": str(exc)}
            )
            break

        print(f"[{team_name}] Iteration {iteration} — testing...", flush=True)

        # ── Tester pass ───────────────────────────────────────────────────────
        tester_prompt = _build_tester_prompt(
            team_name, code_signal, iteration, semantic_context
        )
        try:
            tester_response = tester_agent.invoke(
                {"messages": [HumanMessage(content=tester_prompt)]}
            )
            test_outcome_raw = _extract_last_ai_message(tester_response)
            test_outcome = _safe_parse_json(test_outcome_raw)
        except Exception as exc:
            error = f"Tester crashed on iteration {iteration}: {exc}"
            print(f"[{team_name}] TESTER ERROR: {exc}", file=sys.stderr, flush=True)
            history.append(
                {
                    "iteration": iteration,
                    "status": "TESTER_ERROR",
                    "code_signal_preview": code_signal[:200],
                    "error": str(exc),
                }
            )
            break

        status = test_outcome.get("status", "FAIL")
        next_action = test_outcome.get("next_action", "fix_and_retry")
        summary = test_outcome.get("summary", "")

        history.append(
            {
                "iteration": iteration,
                "status": status,
                "summary": summary,
                "test_outcome": test_outcome,
                "code_signal_preview": code_signal[:500],
            }
        )

        print(
            f"[{team_name}] Iteration {iteration} — {status}: {summary[:80]}",
            flush=True,
        )

        if status == "PASS":
            final_status = "PASS"
            break

        if next_action == "escalate" or test_outcome.get("stuck"):
            final_status = "ESCALATED"
            print(f"[{team_name}] ESCALATED — {summary}", flush=True)
            break

        if iteration == max_iterations:
            final_status = "EXHAUSTED"
            break

        # Feed failure summary back to coder for next iteration
        prior_failure = json.dumps(
            {
                "summary": summary,
                "failures": test_outcome.get("failures", []),
                "visual_findings": test_outcome.get("visual_findings", {}),
            },
            indent=2,
        )

    # ── Persist learnings to LanceDB ──────────────────────────────────────────
    print(f"[{team_name}] Persisting learnings to LanceDB...", flush=True)
    written = _persist_team_learnings(team_name, task, history)

    # ── Trajectory evaluation ─────────────────────────────────────────────────
    print(f"[{team_name}] Running trajectory evaluation...", flush=True)
    eval_result: dict = {}
    try:
        from agents.trajectory_eval import (
            evaluate_team_trajectory,
            submit_langsmith_feedback,
        )

        eval_result = evaluate_team_trajectory(team_name, task, history, final_status)
        score_str = "PASS" if eval_result.get("score") else "FAIL"
        print(
            f"[{team_name}] Eval → {score_str} | "
            f"mfg={eval_result.get('manufacturing_correctness', 0):.2f} "
            f"conv={eval_result.get('convergence_efficiency', 0):.2f} "
            f"prod={eval_result.get('production_readiness', 0):.2f}",
            flush=True,
        )

        # Submit scores to LangSmith as run feedback
        try:
            import langsmith as _ls

            run_tree = _ls.get_current_run_tree()
            run_id = str(run_tree.id) if run_tree else None
        except Exception:
            run_id = None
        submit_langsmith_feedback(run_id, eval_result, team_name)
    except Exception as exc:
        eval_result = {"eval_error": str(exc)}
        print(
            f"[{team_name}] Trajectory eval failed: {exc}", file=sys.stderr, flush=True
        )

    result: TeamResult = {
        "team_name": team_name,
        "task": task,
        "iterations_completed": len(history),
        "final_status": final_status,
        "history": history,
        "lancedb_written": written,
        "eval": eval_result,
    }
    if error:
        result["error"] = error

    # Write output file for external monitoring
    out_file = REPO_ROOT / "agents" / f"_fleet_{team_name.lower()}_out.txt"
    out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"[{team_name}] Done → {out_file.name} | status={final_status}", flush=True)

    return result


# ── LangGraph fleet graph ─────────────────────────────────────────────────────


def plan_teams(state: FleetState) -> FleetState:
    """Director: decompose user_request into TeamTask list."""
    llm = _director_llm().bind(
        response_mime_type="application/json",
        response_schema=_PLAN_SCHEMA,
    )
    response = llm.invoke(
        [
            {"role": "system", "content": _PLAN_SYSTEM},
            {"role": "user", "content": state["user_request"]},
        ]
    )
    raw = response.content if isinstance(response.content, str) else str(response)
    try:
        plan_data = json.loads(raw)
    except json.JSONDecodeError:
        plan_data = {
            "team_tasks": [{"team_name": "Alpha", "task": state["user_request"]}]
        }

    team_tasks: list[TeamTask] = [
        TeamTask(
            team_name=t["team_name"],
            task=t["task"],
            max_iterations=t.get(
                "max_iterations", state.get("max_iterations", MAX_ITERATIONS_DEFAULT)
            ),
        )
        for t in plan_data.get("team_tasks", [])
    ]
    print(
        f"[fleet] Planned {len(team_tasks)} team(s): {[t['team_name'] for t in team_tasks]}",
        flush=True,
    )
    return {"team_tasks": team_tasks, "team_results": []}


def dispatch_teams(state: FleetState) -> list[Send]:
    """Fan-out all team tasks in parallel via the Send API."""
    return [
        Send(f"team_{t['team_name'].lower()}", SingleTeamState(team_task=t))
        for t in state["team_tasks"]
    ]


def _make_team_node(team_name: str):
    """Factory: creates the LangGraph node function for a given team."""

    def team_node(state: SingleTeamState) -> FleetState:
        tt = state["team_task"]
        result = _run_team_loop(
            team_name=tt["team_name"],
            task=tt["task"],
            max_iterations=tt.get("max_iterations", MAX_ITERATIONS_DEFAULT),
        )
        return {"team_results": [result]}

    team_node.__name__ = f"team_{team_name.lower()}"
    return team_node


team_alpha = _make_team_node("Alpha")
team_beta = _make_team_node("Beta")
team_gamma = _make_team_node("Gamma")


def report(state: FleetState) -> FleetState:
    """Synthesize all team results into a final report."""
    llm = _director_llm()
    results_text = json.dumps(
        [
            {
                "team": r["team_name"],
                "task": r["task"],
                "status": r["final_status"],
                "iterations": r["iterations_completed"],
                "summary": r["history"][-1].get("summary", "") if r["history"] else "",
                "trajectory_eval": {
                    "score": r.get("eval", {}).get("score"),
                    "reasoning": r.get("eval", {}).get("reasoning", ""),
                    "manufacturing_correctness": r.get("eval", {}).get(
                        "manufacturing_correctness"
                    ),
                    "convergence_efficiency": r.get("eval", {}).get(
                        "convergence_efficiency"
                    ),
                    "production_readiness": r.get("eval", {}).get(
                        "production_readiness"
                    ),
                    "convergence_rate": r.get("eval", {}).get("convergence_rate"),
                },
            }
            for r in state["team_results"]
        ],
        indent=2,
    )
    response = llm.invoke(
        [
            {
                "role": "system",
                "content": "You are the fleet director. Synthesize team results into a concise final report.",
            },
            {
                "role": "user",
                "content": (
                    f"Original request: {state['user_request']}\n\n"
                    f"Team results (including trajectory evaluation scores):\n{results_text}\n\n"
                    "Write a brief final report: what was implemented, what passed, "
                    "what failed or is still open, trajectory quality scores (manufacturing "
                    "correctness, convergence, production readiness), and recommended next steps."
                ),
            },
        ]
    )
    content = response.content if isinstance(response.content, str) else str(response)
    return {"final_report": content}


# ── Checkpointer ──────────────────────────────────────────────────────────────


def _build_checkpointer() -> Any:
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg_pool import ConnectionPool

        dsn = os.environ.get(
            "PG_DSN", "postgresql://postgres:d1204l0723@localhost:5432/postgres"
        )
        pool = ConnectionPool(
            conninfo=dsn, max_size=6, kwargs={"autocommit": True}, open=True
        )
        saver = PostgresSaver(pool)
        saver.setup()
        return saver
    except Exception as exc:
        import warnings

        warnings.warn(
            f"PostgresSaver unavailable ({exc}), falling back to MemorySaver.",
            stacklevel=2,
        )
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()


# ── Graph assembly ────────────────────────────────────────────────────────────


def build_fleet_graph() -> Any:
    checkpointer = _build_checkpointer()
    g = StateGraph(FleetState)

    # Nodes
    g.add_node("plan_teams", plan_teams)
    g.add_node("team_alpha", team_alpha)
    g.add_node("team_beta", team_beta)
    g.add_node("team_gamma", team_gamma)
    g.add_node("report", report)

    # Edges
    g.add_edge(START, "plan_teams")
    g.add_conditional_edges("plan_teams", dispatch_teams)  # Send API fan-out
    for team in ("team_alpha", "team_beta", "team_gamma"):
        g.add_edge(team, "report")
    g.add_edge("report", END)

    return g.compile(checkpointer=checkpointer)


_fleet_graph: Any = None


# ── Public API ────────────────────────────────────────────────────────────────


@traceable(
    name="dev-fleet-run",
    tags=["dev-fleet"],
    metadata={"environment": "dev", "project": "qidistudio"},
)
def run_fleet(
    request: str,
    teams: list[str] | None = None,
    max_iterations: int = MAX_ITERATIONS_DEFAULT,
    thread_id: str | None = None,
) -> dict:
    """
    Run the coder/tester dev fleet on a user request.

    Results are durably persisted to the ``agent_runs`` Postgres table so they
    survive terminal closures and conversation summarizations.  Retrieve them
    with ``agents.run_store.list_runs(fleet='dev_fleet')`` or
    ``agents.run_store.get_latest_run(fleet='dev_fleet')``.

    Args:
        request:        Natural language coding task (may reference files, features, bugs).
        teams:          Optional list of team names to use (default: director decides).
                        Pass e.g. ["Alpha"] to force a single-team run.
        max_iterations: Per-team iteration cap (default 5).
        thread_id:      Postgres checkpoint thread ID for resumable runs.

    Returns:
        dict with keys: final_report, team_results, thread_id, run_id
    """
    from agents.run_store import save_run, save_run_failed  # lazy import
    from datetime import datetime, timezone

    global _fleet_graph
    if _fleet_graph is None:
        _fleet_graph = build_fleet_graph()

    # If specific teams requested, prepend a hint to the director
    effective_request = request
    if teams:
        team_str = ", ".join(teams)
        effective_request = f"[Use only teams: {team_str}]\n\n{request}"

    tid = thread_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    config = {"configurable": {"thread_id": tid}}

    try:
        final_state = _fleet_graph.invoke(
            {
                "user_request": effective_request,
                "max_iterations": max_iterations,
                "team_tasks": [],
                "team_results": [],
            },
            config=config,
        )
    except Exception as exc:
        save_run_failed(
            thread_id=tid,
            fleet="dev_fleet",
            request=request,
            error=str(exc),
        )
        raise

    team_results = final_state.get("team_results", [])
    final_report = final_state.get("final_report", "No report synthesized.")

    # ── Persist results to agent_runs table (survives terminal/session death) ──
    run_id = save_run(
        thread_id=tid,
        fleet="dev_fleet",
        request=request,
        agent_results=team_results,  # TeamResult objects stored as JSONB blobs
        final_response=final_report,
        status="completed",
        metadata={
            "teams_requested": teams or [],
            "max_iterations": max_iterations,
            "team_statuses": {r["team_name"]: r["final_status"] for r in team_results},
        },
        created_at=created_at,
    )

    return {
        "thread_id": tid,
        "run_id": run_id,
        "final_report": final_report,
        "team_results": team_results,
    }


# ── CLI entry point ───────────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="QIDIStudio Dev Fleet — parallel coder/tester teams"
    )
    parser.add_argument("task", nargs="+", help="Coding task description")
    parser.add_argument(
        "--teams",
        nargs="+",
        choices=TEAM_NAMES,
        help="Specific teams to use (default: director decides)",
    )
    parser.add_argument(
        "--max-iter",
        type=int,
        default=MAX_ITERATIONS_DEFAULT,
        help=f"Max iterations per team (default: {MAX_ITERATIONS_DEFAULT})",
    )
    parser.add_argument("--thread", type=str, default=None, help="Resume a prior run")
    args = parser.parse_args()

    task_str = " ".join(args.task)
    print(f"\n[dev_fleet] Request: {task_str}", flush=True)
    print(f"[dev_fleet] Teams: {args.teams or 'director decides'}", flush=True)
    print(f"[dev_fleet] Max iterations: {args.max_iter}\n", flush=True)

    result = run_fleet(
        request=task_str,
        teams=args.teams,
        max_iterations=args.max_iter,
        thread_id=args.thread,
    )

    print("\n" + "=" * 70)
    print("FINAL REPORT")
    print("=" * 70)
    print(result["final_report"])
    print("=" * 70)
    print(f"Thread ID : {result['thread_id']}")
    print(
        f"Run ID    : {result.get('run_id', 'n/a')}  ← query with: python -m agents.run_store -r <run_id>"
    )
    for tr in result["team_results"]:
        print(
            f"  Team {tr['team_name']}: {tr['final_status']} "
            f"({tr['iterations_completed']} iterations) "
            f"| LanceDB={'ok' if tr.get('lancedb_written') else 'FAIL'}"
        )
