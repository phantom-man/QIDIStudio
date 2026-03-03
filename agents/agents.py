"""
agents/agents.py — Agent factory for QIDIStudio sub-agents.

Loads system prompts from LangSmith Hub (or local fallback), wraps each with
a Gemini model via ChatGoogleGenerativeAI, and returns create_react_agent instances.

Model assignments:
  researcher  — gemini-2.5-flash  (web search via google_search tool)
  builder     — gemini-2.5-pro    (best reasoning for implementation)
  verifier    — gemini-2.5-flash  (fast, structured verdict)
  scribe      — gemini-2.5-flash  (fast, low cost)
  librarian   — gemini-2.5-flash  (deep RAG + web)
  skeptic     — gemini-2.5-flash  (falsification)
  synthesizer — gemini-2.5-pro    (theory unification)
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
    LIBRARIAN_TOOLS,
    RESEARCHER_TOOLS,
    SCRIBE_TOOLS,
    SKEPTIC_TOOLS,
    SYNTHESIZER_TOOLS,
    VERIFIER_TOOLS,
)

# ── Load env ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parents[1]
load_dotenv(REPO_ROOT / ".env", override=True)

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
        # Render the template (empty vars) so we get concrete message objects,
        # then extract the first non-empty string which is the system message.
        try:
            rendered = prompt_obj.invoke({})
            messages = getattr(rendered, "messages", [])
            for msg in messages:
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content.strip():
                    return content
        except Exception:
            pass
        # Last-resort: stringify the template object
        return str(prompt_obj)
    except Exception as exc:
        import warnings

        warnings.warn(
            f"LangSmith Hub prompt load failed for '{agent_id}': {exc} — using local fallback.",
            stacklevel=2,
        )
        local = PROMPTS_DIR / f"{agent_id}.md"
        if local.exists():
            return local.read_text(encoding="utf-8")
        raise RuntimeError(
            f"No prompt found for agent '{agent_id}' (Hub failed: {exc}; local file missing)"
        )


# ── Model factory ─────────────────────────────────────────────────────────────

# Vertex AI project + region — auth via gcloud ADC (no API key needed)
_GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "crafty-hook-483415-b3")
_GCP_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")


def _make_llm(
    model: str, temperature: float = 0.0, **kwargs: Any
) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        project=_GCP_PROJECT,
        location=_GCP_LOCATION,
        **kwargs,
    )


# ── Agent factory ─────────────────────────────────────────────────────────────


def make_researcher() -> Any:
    """
    Researcher: Gemini 2.5 Flash + google_search (explicit ReAct tool, ADC auth).
    Web search is fully visible in LangGraph trace and LangSmith runs.
    """
    llm = _make_llm("gemini-2.5-flash")
    system = load_prompt("researcher")
    return create_react_agent(llm, tools=RESEARCHER_TOOLS, prompt=system)


def make_builder() -> Any:
    """
    Builder: Gemini 2.5 Pro — best reasoning + code via run_command tool.
    """
    llm = _make_llm("gemini-2.5-pro")
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


def make_librarian() -> Any:
    """
    Librarian: Gemini 2.5 Flash + Tavily + memory_read + file_read.
    Board of Directors — deep RAG retrieval + cross-domain web search.
    """
    llm = _make_llm("gemini-2.5-flash")
    system = load_prompt("librarian")
    return create_react_agent(llm, tools=LIBRARIAN_TOOLS, prompt=system)


def make_skeptic() -> Any:
    """
    Skeptic: Gemini 2.5 Flash + file execution + memory_read.
    Board of Directors — Popperian falsification + edge-case enumeration.
    """
    llm = _make_llm("gemini-2.5-flash")
    system = load_prompt("skeptic")
    return create_react_agent(llm, tools=SKEPTIC_TOOLS, prompt=system)


def make_synthesizer() -> Any:
    """
    Synthesizer: Gemini 2.5 Pro + memory_write.
    Board of Directors — cross-domain theory unification + isomorphism detection.
    """
    llm = _make_llm("gemini-2.5-pro")
    system = load_prompt("synthesizer")
    return create_react_agent(llm, tools=SYNTHESIZER_TOOLS, prompt=system)


# ── Agent registry ────────────────────────────────────────────────────────────

_REGISTRY: dict[str, Any] = {}


def get_agent(agent_id: str) -> Any:
    """Return a cached agent instance — agents are stateless, safe to reuse."""
    if agent_id not in _REGISTRY:
        factories = {
            "researcher": make_researcher,
            "builder": make_builder,
            "verifier": make_verifier,
            "scribe": make_scribe,
            "librarian": make_librarian,
            "skeptic": make_skeptic,
            "synthesizer": make_synthesizer,
        }
        if agent_id not in factories:
            raise ValueError(f"Unknown agent: {agent_id!r}. Valid: {list(factories)}")
        _REGISTRY[agent_id] = factories[agent_id]()
    return _REGISTRY[agent_id]
