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
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from dotenv import load_dotenv
from langchain.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import NotRequired

# ── Env ───────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parents[1]
load_dotenv(REPO_ROOT / ".env")


# ── State schema ─────────────────────────────────────────────────────────────

class AgentTask(TypedDict):
    agent_id:   str           # "researcher" | "builder" | "verifier" | "scribe"
    task:       str           # specific instruction for that agent
    context:    dict          # supporting context (file paths, facts, etc.)
    depends_on: list[str]     # logical deps (informational only — enforced via graph topology)


class AgentResult(TypedDict):
    agent_id: str
    task:     str
    result:   str             # JSON string of agent output
    success:  bool
    error:    NotRequired[str]


def _merge_results(left: list, right: list) -> list:
    """Reducer: accumulate results from parallel agent nodes."""
    return left + right


class OrchestratorState(TypedDict):
    user_request: str
    tasks:        list[AgentTask]
    results:      Annotated[list[AgentResult], _merge_results]
    final_response: NotRequired[str]


class SingleTaskState(TypedDict):
    """State passed to each parallel agent node via Send."""
    task: AgentTask


# ── Director LLM ─────────────────────────────────────────────────────────────

def _director_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.0,
        google_api_key=os.environ.get("GOOGLE_API_KEY"),
    )


_DIRECTOR_SYSTEM = (REPO_ROOT / "agents" / "prompts" / "director.md").read_text(encoding="utf-8")

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "agent_id":   {"type": "string", "enum": ["researcher", "builder", "verifier", "scribe"]},
                    "task":       {"type": "string"},
                    "context":    {"type": "object"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
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
        {"role": "user",   "content": state["user_request"]},
    ]
    response = llm.invoke(messages)
    raw = response.content if isinstance(response.content, str) else response.text
    plan_data = json.loads(raw)
    tasks: list[AgentTask] = [
        AgentTask(
            agent_id=t["agent_id"],
            task=t["task"],
            context=t.get("context", {}),
            depends_on=t.get("depends_on", []),
        )
        for t in plan_data.get("tasks", [])
    ]
    return {"tasks": tasks, "results": []}


def dispatch(state: OrchestratorState) -> list[Send]:
    """
    Fan-out all tasks to agent nodes in parallel via Send API.
    Tasks with depends_on[] = [] run immediately (same superstep).
    For tasks with deps, we run them all anyway — deps are informational in
    this simple topology; for strict ordering, use subgraphs.
    """
    return [
        Send(task["agent_id"], SingleTaskState(task=task))
        for task in state["tasks"]
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


def synthesize(state: OrchestratorState) -> OrchestratorState:
    """
    Collect all results, build a human-readable summary.
    The director LLM synthesises the final response.
    """
    llm = _director_llm()
    results_text = json.dumps(
        [{"agent": r["agent_id"], "success": r["success"], "result": r["result"]} for r in state["results"]],
        indent=2
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


# ── Build graph ────────────────────────────────────────────────────────────────

def build_graph() -> Any:
    builder_graph = StateGraph(OrchestratorState)

    # Nodes
    builder_graph.add_node("plan",       plan)
    builder_graph.add_node("researcher", researcher)
    builder_graph.add_node("builder",    builder)
    builder_graph.add_node("verifier",   verifier)
    builder_graph.add_node("scribe",     scribe)
    builder_graph.add_node("synthesize", synthesize)

    # Edges
    builder_graph.add_edge(START, "plan")
    builder_graph.add_conditional_edges("plan", dispatch)   # Send API fan-out

    # All agent nodes converge to synthesize
    for agent_id in ("researcher", "builder", "verifier", "scribe"):
        builder_graph.add_edge(agent_id, "synthesize")

    builder_graph.add_edge("synthesize", END)

    return builder_graph.compile()


# ── Public interface ──────────────────────────────────────────────────────────

_graph: Any = None


def run(request: str) -> str:
    """
    Run the director-agent fleet on a user request.
    Returns the synthesised final response as a string.

    Example:
        result = run("Research whether our CMake fix for QIDINetwork.cpp is in the fork")
        print(result)
    """
    global _graph
    if _graph is None:
        _graph = build_graph()

    final_state = _graph.invoke({"user_request": request, "tasks": [], "results": []})
    return final_state.get("final_response", "No response synthesized.")


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What is the current build status?"
    print(run(q))
