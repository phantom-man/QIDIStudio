"""
agents/agents.py — Agent factory for QIDIStudio sub-agents.

Loads system prompts from LangSmith Hub (or local fallback), wraps each with
a Gemini model via ChatGoogleGenerativeAI, and returns create_react_agent instances.

Model assignments:
  researcher  — gemini-2.5-flash + google_search + url_context (built-in tools)
  builder     — gemini-2.5-pro + code_execution (best reasoning)
  verifier    — gemini-2.5-flash (fast, structured output)
  scribe      — gemini-2.5-flash (fast, low cost)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent
from langsmith import Client

from agents.tools import (
    BUILDER_TOOLS,
    RESEARCHER_TOOLS,
    SCRIBE_TOOLS,
    VERIFIER_TOOLS,
)

# ── Load env ──────────────────────────────────────────────────────────────────

REPO_ROOT  = Path(__file__).parents[1]
load_dotenv(REPO_ROOT / ".env")

PROMPTS_DIR = REPO_ROOT / "agents" / "prompts"

# ── LangSmith Hub prompt loader ───────────────────────────────────────────────

_hub_client: Client | None = None

def _get_client() -> Client:
    global _hub_client
    if _hub_client is None:
        _hub_client = Client(api_key=os.environ["LANGSMITH_API_KEY"])
    return _hub_client


def load_prompt(agent_id: str) -> str:
    """
    Pull system prompt from LangSmith Hub (qidi-<agent_id>).
    Falls back to local agents/prompts/<agent_id>.md if Hub is unavailable.
    """
    try:
        client = _get_client()
        prompt_obj = client.pull_prompt(f"qidi-{agent_id}")
        # Hub prompt is a ChatPromptTemplate — extract system message text
        msgs = prompt_obj.messages if hasattr(prompt_obj, "messages") else []
        for msg in msgs:
            content = getattr(msg, "content", None) or getattr(msg, "prompt", {})
            if isinstance(content, str) and content.strip():
                return content
        # Fallback: stringify the template
        return str(prompt_obj)
    except Exception:
        # Use local file as fallback
        local = PROMPTS_DIR / f"{agent_id}.md"
        if local.exists():
            return local.read_text(encoding="utf-8")
        raise RuntimeError(f"No prompt found for agent '{agent_id}' (Hub and local both failed)")


# ── Model factory ─────────────────────────────────────────────────────────────

def _make_llm(model: str, temperature: float = 0.0, **kwargs: Any) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        google_api_key=os.environ.get("GOOGLE_API_KEY"),
        **kwargs,
    )


# ── Agent factory ─────────────────────────────────────────────────────────────

# Built-in Gemini tool specs — passed at model construction so LangGraph's
# tool-count validator only sees our custom LangChain tools.
_GEMINI_SEARCH_TOOLS = [{"google_search": {}}, {"url_context": {}}]
_GEMINI_CODE_TOOLS   = [{"code_execution": {}}]


def make_researcher() -> Any:
    """
    Researcher: Gemini 2.5 Flash + Google Search + URL Context (built-in, constructor-level)
    plus our local memory_read / file_read tools.
    """
    # Built-in tools configured at model level — not via bind_tools — so
    # LangGraph create_react_agent only counts RESEARCHER_TOOLS.
    llm = _make_llm("gemini-2.5-flash",
                    model_kwargs={"tools": _GEMINI_SEARCH_TOOLS})
    system = load_prompt("researcher")
    return create_react_agent(llm, tools=RESEARCHER_TOOLS, prompt=system)


def make_builder() -> Any:
    """
    Builder: Gemini 2.5 Pro + Code Execution (best for complex implementation).
    """
    llm = _make_llm("gemini-2.5-pro",
                    model_kwargs={"tools": _GEMINI_CODE_TOOLS})
    system = load_prompt("builder")
    return create_react_agent(llm, tools=BUILDER_TOOLS, prompt=system)


def make_verifier() -> Any:
    """
    Verifier: Gemini 2.5 Flash — structured output, fast binary verdict.
    """
    llm = _make_llm("gemini-2.5-flash")
    system = load_prompt("verifier")
    return create_react_agent(llm, tools=VERIFIER_TOOLS, prompt=system)


def make_scribe() -> Any:
    """
    Scribe: Gemini 2.5 Flash — writes to LanceDB, updates copilot-instructions.md.
    """
    llm = _make_llm("gemini-2.5-flash")
    system = load_prompt("scribe")
    return create_react_agent(llm, tools=SCRIBE_TOOLS, prompt=system)


# ── Agent registry ────────────────────────────────────────────────────────────

_REGISTRY: dict[str, Any] = {}

def get_agent(agent_id: str) -> Any:
    """Return a cached agent instance — agents are stateless, safe to reuse."""
    if agent_id not in _REGISTRY:
        factories = {
            "researcher": make_researcher,
            "builder":    make_builder,
            "verifier":   make_verifier,
            "scribe":     make_scribe,
        }
        if agent_id not in factories:
            raise ValueError(f"Unknown agent: {agent_id!r}. Valid: {list(factories)}")
        _REGISTRY[agent_id] = factories[agent_id]()
    return _REGISTRY[agent_id]
