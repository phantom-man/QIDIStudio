"""
agents/orchestrator.py — LangGraph supervisor for QIDIStudio.

Architecture: Supervisor pattern with parallel fan-out via Send API.

Flow:
  START
    └─ plan        (director LLM decomposes request into typed tasks)
         └─ dispatch (Send API: fan-out tasks to agents in parallel)
              ├─ researcher ──┐
              ├─ builder    ──┤
              ├─ verifier   ──┤  (all run in same LangGraph superstep = true parallel)
              └─ scribe     ──┘
                   └─ synthesize (collect results → final response)
                        └─ END

Each agent node receives a single AgentTask, invokes the appropriate sub-agent,
and appends its AgentResult to the shared `results` list (via add reducer).

Usage:
    from agents.orchestrator import run
    result = run("Research the CMake QIDINetwork.cpp fix and verify it's in our fork")
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

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

# Project name for this pipeline -- LANGSMITH_TRACING=true is set in .env.
# Using setdefault so a shell-level LANGCHAIN_PROJECT override still works.
os.environ.setdefault("LANGCHAIN_PROJECT", "qidistudio-agents")


# ── State schema ─────────────────────────────────────────────────────────────


class AgentTask(TypedDict):
    agent_id: str  # "researcher"|"builder"|"verifier"|"scribe"|"librarian"|"skeptic"|"synthesizer"
    task: str  # specific instruction for that agent
    context: dict  # supporting context (file paths, facts, etc.)
    # NOTE: all tasks run as a parallel superstep — no sequential deps are enforced.


class AgentResult(TypedDict):
    agent_id: str
    task: str
    result: str  # JSON string of agent output
    success: bool
    error: NotRequired[str]


def _merge_results(left: list, right: list) -> list:
    """Reducer: accumulate results from parallel agent nodes."""
    return left + right


class OrchestratorState(TypedDict):
    user_request: str
    tasks: list[AgentTask]
    results: Annotated[list[AgentResult], _merge_results]
    final_response: NotRequired[str]


class SingleTaskState(TypedDict):
    """State passed to each parallel agent node via Send."""

    task: AgentTask


# ── Director LLM ─────────────────────────────────────────────────────────────

_GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "crafty-hook-483415-b3")
_GCP_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")


def _director_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.0,
        project=_GCP_PROJECT,
        location=_GCP_LOCATION,
    )


_DIRECTOR_SYSTEM = (REPO_ROOT / "agents" / "prompts" / "director.md").read_text(
    encoding="utf-8"
)

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "enum": [
                            "researcher",
                            "builder",
                            "verifier",
                            "scribe",
                            "librarian",
                            "skeptic",
                            "synthesizer",
                        ],
                    },
                    "task": {"type": "string"},
                    "context": {"type": "object"},
                },
                "required": ["agent_id", "task"],
            },
        },
    },
    "required": ["tasks"],
}


# ── Graph nodes ───────────────────────────────────────────────────────────────


def plan(state: OrchestratorState) -> OrchestratorState:
    """
    Director: decompose user_request into a list of AgentTasks.
    Uses structured output so the result is always valid JSON.
    """
    llm = _director_llm().bind(
        response_mime_type="application/json",
        response_schema=_PLAN_SCHEMA,
    )
    messages = [
        {"role": "system", "content": _DIRECTOR_SYSTEM},
        {"role": "user", "content": state["user_request"]},
    ]
    response = llm.invoke(messages)
    raw = response.content if isinstance(response.content, str) else response.text
    try:
        plan_data = json.loads(raw)
    except json.JSONDecodeError:
        import warnings

        warnings.warn(
            f"Director returned invalid JSON — falling back to single researcher task. "
            f"raw={raw[:200]!r}",
            stacklevel=2,
        )
        plan_data = {
            "tasks": [
                {"agent_id": "researcher", "task": state["user_request"], "context": {}}
            ]
        }
    tasks: list[AgentTask] = [
        AgentTask(
            agent_id=t["agent_id"],
            task=t["task"],
            context=t.get("context", {}),
        )
        for t in plan_data.get("tasks", [])
    ]
    return {"tasks": tasks, "results": []}


def dispatch(state: OrchestratorState) -> list[Send]:
    """
    Fan-out all tasks to agent nodes in parallel via the Send API.
    All tasks run in the same LangGraph superstep — true parallelism.
    Task ordering is not enforced; decompose into independent units.
    """
    return [
        Send(task["agent_id"], SingleTaskState(task=task)) for task in state["tasks"]
    ]


def _run_agent(agent_id: str, state: SingleTaskState) -> OrchestratorState:
    """Generic agent executor — runs agent, catches errors, returns AgentResult."""
    from agents.agents import get_agent  # lazy import to avoid circular at module level

    task = state["task"]
    try:
        agent = get_agent(agent_id)
        prompt = f"{task['task']}\n\nContext: {json.dumps(task.get('context', {}), indent=2)}"
        response = agent.invoke({"messages": [HumanMessage(content=prompt)]})
        # extract last AI message content
        msgs = response.get("messages", [])
        last = next(
            (m for m in reversed(msgs) if getattr(m, "type", None) == "ai"),
            None,
        )
        result_str = getattr(last, "content", str(response)) if last else str(response)
        result = AgentResult(
            agent_id=agent_id,
            task=task["task"],
            result=result_str,
            success=True,
        )
    except Exception as exc:
        result = AgentResult(
            agent_id=agent_id,
            task=task["task"],
            result="{}",
            success=False,
            error=str(exc),
        )
    return {"results": [result]}


def researcher(state: SingleTaskState) -> OrchestratorState:
    return _run_agent("researcher", state)


def builder(state: SingleTaskState) -> OrchestratorState:
    return _run_agent("builder", state)


def verifier(state: SingleTaskState) -> OrchestratorState:
    return _run_agent("verifier", state)


def scribe(state: SingleTaskState) -> OrchestratorState:
    return _run_agent("scribe", state)


def librarian(state: SingleTaskState) -> OrchestratorState:
    return _run_agent("librarian", state)


def skeptic(state: SingleTaskState) -> OrchestratorState:
    return _run_agent("skeptic", state)


def synthesizer(state: SingleTaskState) -> OrchestratorState:
    return _run_agent("synthesizer", state)


def synthesize(state: OrchestratorState) -> OrchestratorState:
    """
    Collect all results, build a human-readable summary.
    The director LLM synthesises the final response.
    """
    llm = _director_llm()
    results_text = json.dumps(
        [
            {"agent": r["agent_id"], "success": r["success"], "result": r["result"]}
            for r in state["results"]
        ],
        indent=2,
    )
    messages = [
        {"role": "system", "content": _DIRECTOR_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Original request: {state['user_request']}\n\n"
                f"All agent results:\n{results_text}\n\n"
                "Synthesise a concise final response covering what was done, what changed, "
                "and any follow-up steps. Return plain text — no JSON required here."
            ),
        },
    ]
    response = llm.invoke(messages)
    content = response.content if isinstance(response.content, str) else response.text
    return {"final_response": content}


# ── Checkpointer (PostgresSaver) ─────────────────────────────────────────────

_checkpointer: Any = None


def _build_checkpointer() -> Any:
    """
    Build a PostgresSaver backed by our local Postgres instance.
    Connection string is read from PG_DSN env var (set in .env).
    Falls back gracefully to MemorySaver if postgres is unavailable.
    """
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg_pool import ConnectionPool

        dsn = os.environ.get(
            "PG_DSN", "postgresql://postgres:d1204l0723@localhost:5432/postgres"
        )
        pool = ConnectionPool(
            conninfo=dsn,
            max_size=10,
            kwargs={"autocommit": True},
            open=False,
            reconnect_timeout=3,
        )
        pool.open(
            wait=True, timeout=5.0
        )  # raises PoolTimeout/ConnectionError if PG is down
        saver = PostgresSaver(pool)
        saver.setup()  # idempotent — creates langgraph_checkpoints tables if needed
        return saver
    except Exception as exc:
        import warnings

        warnings.warn(
            f"PostgresSaver unavailable ({exc}), falling back to MemorySaver (state is NOT persistent).",
            stacklevel=2,
        )
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()


# ── Build graph ────────────────────────────────────────────────────────────────


def build_graph() -> Any:
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = _build_checkpointer()

    builder_graph = StateGraph(OrchestratorState)

    # Nodes
    builder_graph.add_node("plan", plan)
    builder_graph.add_node("researcher", researcher)
    builder_graph.add_node("builder", builder)
    builder_graph.add_node("verifier", verifier)
    builder_graph.add_node("scribe", scribe)
    builder_graph.add_node("librarian", librarian)
    builder_graph.add_node("skeptic", skeptic)
    builder_graph.add_node("synthesizer", synthesizer)
    builder_graph.add_node("synthesize", synthesize)

    # Edges
    builder_graph.add_edge(START, "plan")
    builder_graph.add_conditional_edges("plan", dispatch)  # Send API fan-out

    # All agent nodes converge to synthesize
    for agent_id in (
        "researcher",
        "builder",
        "verifier",
        "scribe",
        "librarian",
        "skeptic",
        "synthesizer",
    ):
        builder_graph.add_edge(agent_id, "synthesize")

    builder_graph.add_edge("synthesize", END)

    return builder_graph.compile(checkpointer=_checkpointer)


# ── Public interface ──────────────────────────────────────────────────────────

_graph: Any = None


@traceable(
    name="orchestrator-run",
    tags=["orchestrator"],
    metadata={"environment": "dev", "project": "qidistudio"},
)
def run(request: str, thread_id: str | None = None) -> str:
    """
    Run the director-agent fleet on a user request.
    Returns the synthesised final response as a string.

    Results are durably persisted to the ``agent_runs`` Postgres table so they
    survive terminal closures and conversation summarizations.  Retrieve them
    with ``agents.run_store.list_runs()`` or ``agents.run_store.get_latest_run()``.

    Args:
        request:   User instruction for the agent fleet.
        thread_id: Conversation thread identifier. Pass the same ID across calls
                   to resume a checkpointed session. Auto-generated if None.

    Example:
        result = run("Research whether our CMake fix for QIDINetwork.cpp is in the fork")
        print(result)

        # Resume same thread (state persisted in Postgres):
        result2 = run("Now apply the fix", thread_id=tid)
    """
    from agents.run_store import (
        save_run,
        save_run_failed,
    )  # lazy — avoids circular at module level
    from datetime import datetime, timezone

    global _graph
    if _graph is None:
        _graph = build_graph()

    tid = thread_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    config = {"configurable": {"thread_id": tid}}
    try:
        final_state = _graph.invoke(
            {"user_request": request, "tasks": [], "results": []},
            config=config,
        )
    except Exception as exc:
        save_run_failed(
            thread_id=tid,
            fleet="orchestrator",
            request=request,
            error=str(exc),
        )
        raise

    response = final_state.get("final_response", "No response synthesized.")

    # ── Persist results to agent_runs table (survives terminal/session death) ──
    save_run(
        thread_id=tid,
        fleet="orchestrator",
        request=request,
        agent_results=final_state.get("results", []),
        final_response=response,
        status="completed",
        created_at=created_at,
    )

    return f"[thread:{tid}] {response}"


if __name__ == "__main__":
    import sys
    import pathlib as _pl

    # When run as `python agents/orchestrator.py`, Python adds the agents/ dir to
    # sys.path[0] instead of the repo root, breaking `from agents.xxx` imports.
    # Insert the repo root (parent of the agents/ directory) if not already present.
    _repo_root = str(_pl.Path(__file__).parents[1])
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

    args = sys.argv[1:]
    # Optional --thread <id> flag
    tid = None
    if "--thread" in args:
        idx = args.index("--thread")
        tid = args[idx + 1]
        args = args[:idx] + args[idx + 2 :]
    q = " ".join(args) if args else "What is the current build status?"
    output = run(q, thread_id=tid)
    print(output)
    print("\n[Results persisted to agent_runs table. Query with:]")
    print("  python -m agents.run_store --latest")
    print("  python -m agents.run_store -n 5")
