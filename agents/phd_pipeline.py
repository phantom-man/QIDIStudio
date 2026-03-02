"""
agents/phd_pipeline.py — Board of Directors Knowledge Acquisition Pipeline.

Inspired by the PhD-level multi-agent acquisition pattern:
  Librarian   → deep RAG retrieval + google_search cross-domain
  Skeptic     → Popperian falsification + edge-case proof attempts
  Synthesizer → cross-domain theory unification + isomorphism detection
  Engineer    → code execution + regression verification (re-uses builder/verifier)

RAML (Retrieval-Augmented Machine Learning) pattern:
  Every failure trace is stored in LanceDB. New research cycles begin by
  retrieving similar past failures before any web search.

Dialectical loop:
  librarian → skeptic → synthesizer → [engineer] → scribe → (repeat or exit)

Entry point:
    from agents.phd_pipeline import run_phd_research
    result = run_phd_research("How should the topology classifier handle high-genus meshes?")
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# ── Environment ───────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parents[1]
load_dotenv(REPO_ROOT / ".env", override=True)

# ── Agent registry (single source of truth — no duplication) ─────────────────

from agents.agents import get_agent  # noqa: E402
from agents.tools import memory_write  # noqa: E402


# ── RAML helper ───────────────────────────────────────────────────────────────


def _retrieve_prior_failures(question: str, n: int = 4) -> str:
    """
    RAML pattern: query LanceDB for similar past failures before starting.
    Returns a formatted summary string.
    """
    try:
        from memory.store import query_similar  # type: ignore

        rows = query_similar(f"failure OR error OR broken: {question}", n=n)
        if not rows:
            return "(No prior failures found for this domain.)"
        lines = []
        for r in rows:
            lines.append(f"- [{r.get('category','')}] {r.get('decision','')}")
        return "Prior failure traces from RAML:\n" + "\n".join(lines)
    except Exception as e:
        return f"(RAML retrieval unavailable: {e})"


# ── Dialectical loop ──────────────────────────────────────────────────────────


def _invoke_agent(agent: Any, message: str, label: str, config: dict | None = None) -> str:
    """Invoke a react agent and extract the final assistant message."""
    try:
        kwargs: dict[str, Any] = {"input": {"messages": [{"role": "user", "content": message}]}}
        if config:
            kwargs["config"] = config
        result = agent.invoke(**kwargs)
        # LangGraph returns {"messages": [...]}
        msgs = result.get("messages", [])
        for msg in reversed(msgs):
            content = getattr(msg, "content", None)
            if content and isinstance(content, str) and content.strip():
                return content
        return str(msgs[-1]) if msgs else "(no output)"
    except Exception as exc:
        return f"[{label} ERROR]: {exc}"


def run_phd_research(
    question: str,
    max_rounds: int = 2,
    persist: bool = True,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """
    Run the Board of Directors dialectical research loop.

    Parameters
    ----------
    question   : The research question or problem statement.
    max_rounds : How many Librarian→Skeptic→Synthesizer cycles to run.
    persist    : Whether to write the final synthesis to LanceDB via scribe.
    thread_id  : Optional trace identifier for LangSmith (auto-generated if None).

    Returns
    -------
    {
      "question":    str,
      "synthesis":   str,   # Final Unified Theory from Synthesizer
      "librarian":   str,   # Raw Librarian report (last round)
      "skeptic":     str,   # Raw Skeptic verdict (last round)
      "rounds":      int,
      "persisted":   bool,
      "thread_id":   str,
    }
    """
    tid = thread_id or f"phd-{uuid.uuid4().hex[:8]}"
    run_config = {
        "configurable": {"thread_id": tid},
        "run_name": "phd-research",
        "tags": ["phd-pipeline"],
        "metadata": {"question_prefix": question[:80]},
    }

    print(f"\n{'='*60}")
    print(f"PhD PIPELINE: {question[:80]}  [thread={tid}]")
    print(f"{'='*60}")

    # RAML: load prior failure context
    raml_context = _retrieve_prior_failures(question)
    print(f"\n[RAML] {raml_context[:200]}")

    # Resolve agents from shared registry (stateless, safe to reuse)
    librarian = get_agent("librarian")
    skeptic = get_agent("skeptic")
    synthesizer = get_agent("synthesizer")

    librarian_out = ""
    skeptic_out = ""
    synthesis_out = ""

    for rnd in range(1, max_rounds + 1):
        print(f"\n--- Round {rnd}/{max_rounds} ---")

        # 1. Librarian: retrieve + report
        lib_prompt = (
            f"RESEARCH QUESTION: {question}\n\n"
            f"RAML CONTEXT (prior failures):\n{raml_context}\n\n"
            "Produce a First Principles Report covering domain axioms, "
            "relevant papers/code, and the Knowledge Gap."
        )
        if rnd > 1 and synthesis_out:
            lib_prompt += (
                f"\n\nPREVIOUS SYNTHESIS (challenge it):\n{synthesis_out[:500]}"
            )
        print("[Librarian] Searching...")
        librarian_out = _invoke_agent(librarian, lib_prompt, "Librarian", run_config)
        print(f"[Librarian] {librarian_out[:200]}...")

        # 2. Skeptic: falsify
        skep_prompt = (
            f"ORIGINAL QUESTION: {question}\n\n"
            f"LIBRARIAN REPORT:\n{librarian_out}\n\n"
            "Attempt to falsify every claim. Provide verdict + required fixes."
        )
        print("[Skeptic] Falsifying...")
        skeptic_out = _invoke_agent(skeptic, skep_prompt, "Skeptic", run_config)
        print(f"[Skeptic] {skeptic_out[:200]}...")

        # 3. Synthesizer: unify
        synth_prompt = (
            f"ORIGINAL QUESTION: {question}\n\n"
            f"LIBRARIAN REPORT:\n{librarian_out}\n\n"
            f"SKEPTIC REPORT:\n{skeptic_out}\n\n"
            "Produce the Unified Theory, isomorphism, and falsifiable prediction. "
            "Call memory_write to persist this synthesis."
        )
        print("[Synthesizer] Synthesizing...")
        synthesis_out = _invoke_agent(synthesizer, synth_prompt, "Synthesizer", run_config)
        print(f"[Synthesizer] {synthesis_out[:200]}...")

        # Early exit if Skeptic says ROBUST
        if "ROBUST" in skeptic_out and rnd < max_rounds:
            print("[Loop] Skeptic verdict ROBUST — early exit.")
            break

        time.sleep(1)  # Rate-limit between rounds

    result: dict[str, Any] = {
        "question": question,
        "synthesis": synthesis_out,
        "librarian": librarian_out,
        "skeptic": skeptic_out,
        "rounds": rnd,
        "persisted": False,
        "thread_id": tid,
    }

    # Scribe: persist synthesis to LanceDB
    if persist and synthesis_out:
        try:
            topic = question[:60]
            write_result = memory_write.invoke(
                {
                    "topic": topic,
                    "decision": synthesis_out[:120],
                    "content": synthesis_out,
                    "source": "phd_pipeline.py",
                    "category": "PhD_Synthesis",
                }
            )
            result["persisted"] = True
            print(f"\n[Scribe] Persisted: {write_result}")
        except Exception as exc:
            print(f"\n[Scribe] Persist failed: {exc}")

    return result


# ── Convenience entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or (
        "How should the QIDIStudio topology classifier distinguish "
        "high-genus PRISMATIC shapes from simple REVOLUTION shapes "
        "using Euler characteristic alone?"
    )
    out = run_phd_research(q, max_rounds=1)
    print("\n" + "=" * 60)
    print("FINAL SYNTHESIS:")
    print(out["synthesis"])
