"""memory/predator.py — Context Window Predator (Prompt-Targeted Pruner)

Called as the final step of inject.py's semantic retrieval before returning
context to the agent. Aggressively prunes candidate memory chunks to only
what the current prompt actually needs.

Strategy
--------
1.  LangSmith identity chunk (source starts with "langsmith-prompt") is NEVER
    dropped — it carries authentication and LangSmith project identity.
2.  Remaining candidate chunks are scored by BM25-style keyword overlap against
    the user's prompt text. High overlap → kept. Zero overlap → dropped (unless
    it's the only result).
3.  Hard budget:  max_items chunks, max_chars total injected content.

Design goal: fast. No LLM API calls. Pure Python math only. <10 ms per call.
"""

import math
import re
from collections import Counter
from typing import Any

# ── Constants ─────────────────────────────────────────────────────────────────

_LANGSMITH_SOURCE = "langsmith-prompt"

# Minimum BM25 overlap score to survive pruning; below this the chunk is
# considered topic-drift noise. We always keep at least 1 non-identity chunk.
_RELEVANCE_FLOOR = 0.015

# English stop-words that carry no semantic signal.
_STOP_WORDS: frozenset[str] = frozenset(
    "a an the and or but in on at to for of with is are was were be been "
    "have has had do does did will would could should may might i you we "
    "it its this that these those from by into about as up if my your our "
    "how what when where who which why not no yes can just all any some "
    "more most also such than then so there here use using used get got "
    "set let new one two also need like want make do does go going gone "
    "see seen seeing make made making take taken taking".split()
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split into word tokens, remove stop words."""
    tokens = re.findall(r"\b[a-z0-9_]{2,}\b", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS]


def _bm25_overlap(prompt_tokens: Counter[str], chunk_text: str) -> float:
    """
    Simplified BM25 overlap score: how much of the prompt's vocabulary appears
    in the chunk.  Returns a value in [0, 1].

    Formula:  Σ prompt_tf(t) * log(1 + chunk_tf(t))  /  normaliser
    """
    if not prompt_tokens:
        return 0.0
    chunk_tokens = Counter(_tokenize(chunk_text))
    score = sum(
        prompt_count * math.log1p(chunk_tokens[token])
        for token, prompt_count in prompt_tokens.items()
        if token in chunk_tokens
    )
    normaliser = sum(c * math.log1p(c) for c in prompt_tokens.values())
    return score / normaliser if normaliser > 0 else 0.0


def _is_langsmith(row: dict[str, Any]) -> bool:
    return (row.get("source") or "").startswith(_LANGSMITH_SOURCE)


def _content_len(row: dict[str, Any]) -> int:
    return len(row.get("content") or row.get("decision") or "")


def _apply_char_budget(
    always_keep: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    max_chars: int,
) -> list[dict[str, Any]]:
    """
    Greedily pack candidates into the char budget.
    Tiny rows (<200 chars) are always included regardless of budget.
    """
    result = list(always_keep)
    used = sum(_content_len(r) for r in result)
    for row in candidates:
        clen = _content_len(row)
        if used + clen <= max_chars or clen < 200:
            result.append(row)
            used += clen
    return result


# ── Public API ────────────────────────────────────────────────────────────────


def prune_context(
    prompt: str,
    rows: list[dict[str, Any]],
    max_items: int = 5,
    max_chars: int = 3500,
) -> list[dict[str, Any]]:
    """
    Predator pass: drop injected memory chunks not relevant to this prompt.

    Parameters
    ----------
    prompt    : Raw user prompt text.
    rows      : Candidate chunks (already deduped + distance-filtered by inject.py).
    max_items : Hard cap on non-identity returned chunks (default 5).
    max_chars : Hard cap on total content characters across all returned chunks.

    Returns
    -------
    Pruned list — LangSmith identity preserved, rest ranked by keyword relevance.
    """
    if not rows:
        return rows

    prompt_tokens: Counter[str] = Counter(_tokenize(prompt))

    # Partition: always-keep (LangSmith identity) vs scoreable candidates
    always_keep = [r for r in rows if _is_langsmith(r)]
    candidates = [r for r in rows if not _is_langsmith(r)]

    if not candidates:
        return always_keep

    if not prompt_tokens:
        # No meaningful tokens in prompt — fall back to top-N by vector distance
        top = sorted(candidates, key=lambda r: r.get("_distance") or 1.0)
        return _apply_char_budget(always_keep, top[:max_items], max_chars)

    # Score each candidate
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in candidates:
        topic = row.get("topic") or ""
        content = row.get("content") or row.get("decision") or ""
        # Double-weight topic so short topic matches count more
        combined = f"{topic} {topic} {content}"
        overlap = _bm25_overlap(prompt_tokens, combined)
        dist = row.get("_distance") or 0.5
        # Final: overlap primary, distance secondary (lower dist → higher score)
        final_score = overlap + max(0.0, (1.0 - dist) * 0.08)
        scored.append((final_score, row))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Always keep at least 1 non-identity result even with zero overlap
    kept: list[dict[str, Any]] = []
    for i, (score, row) in enumerate(scored):
        overlap_only = score - max(0.0, (1.0 - (row.get("_distance") or 0.5)) * 0.08)
        if overlap_only < _RELEVANCE_FLOOR and i > 0:
            # Below floor and not the first result — drop
            continue
        kept.append(row)
        if len(kept) >= max_items:
            break

    return _apply_char_budget(always_keep, kept, max_chars)
