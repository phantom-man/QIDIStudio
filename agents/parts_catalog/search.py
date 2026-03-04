"""
agents/parts_catalog/search.py

Shared search utility for all parts-catalog harvesters.

Uses Gemini 2.5 Flash with native Google Search grounding + url_context tool.
No Tavily required — Gemini handles both discovery and full-page extraction in
a single call.

Usage:
    from agents.parts_catalog.search import gemini_search, extract_structured

    # Discovery: find all stepper motor brands
    results = gemini_search(
        "complete list of NEMA 23 stepper motor manufacturers with product lines",
        response_schema=list[str]   # optional pydantic or basic type
    )

    # Deep extraction: get specs from a product page
    part = extract_structured(
        url="https://www.stepperonline.com/nema-23-stepper-motor-...",
        instruction="Extract all available specifications as a Motor object",
        output_schema=Motor
    )
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Type, TypeVar

from dotenv import load_dotenv
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
load_dotenv(REPO_ROOT / ".env", override=True)

log = logging.getLogger("parts_catalog.search")

T = TypeVar("T")

# ── Lazy Gemini client ────────────────────────────────────────────────────────

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        from langchain_google_genai import ChatGoogleGenerativeAI

        _llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=os.environ["GOOGLE_API_KEY"],
            temperature=0.1,
        )
    return _llm


def _get_llm_with_search():
    """Gemini with Google Search grounding enabled."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0.1,
        tools=[{"google_search": {}}],
    )


# ── Core search function ──────────────────────────────────────────────────────


def gemini_search(query: str, extra_context: str = "", retries: int = 3) -> str:
    """
    Run a Google Search grounded query through Gemini 2.5 Flash.
    Returns the model's synthesised response as a string.

    The model autonomously decides how many search calls to make.
    """
    llm = _get_llm_with_search()
    prompt = query
    if extra_context:
        prompt = f"{extra_context}\n\n{query}"

    for attempt in range(retries):
        try:
            resp = llm.invoke(prompt)
            return resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:
            log.warning("gemini_search attempt %d failed: %s", attempt + 1, e)
            if attempt < retries - 1:
                time.sleep(2**attempt)
    return ""


def gemini_search_json(query: str, extra_context: str = "", retries: int = 3) -> Any:
    """
    Like gemini_search but requests JSON output and parses it.
    Returns parsed Python object (dict, list, etc.) or None on failure.
    """
    json_prompt = (
        f"{query}\n\n"
        "Return ONLY a valid JSON object or array. No markdown, no explanation, no code fences."
    )
    raw = gemini_search(json_prompt, extra_context=extra_context, retries=retries)
    # Strip common LLM wrapping
    raw = raw.strip()
    for fence in ("```json", "```JSON", "```"):
        if raw.startswith(fence):
            raw = raw[len(fence) :].strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract the first JSON block
        import re

        match = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
        log.warning("Failed to parse JSON from gemini_search response: %s", raw[:200])
        return None


def extract_page_specs(url: str, instruction: str, retries: int = 3) -> str:
    """
    Fetch a URL via Gemini's url_context tool and extract information.
    Returns the model's extraction as a string.
    """
    from langchain_google_genai import ChatGoogleGenerativeAI

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0.0,
        tools=[{"url_context": {}}],
    )
    prompt = f"Read this page: {url}\n\n{instruction}"
    for attempt in range(retries):
        try:
            resp = llm.invoke(prompt)
            return resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:
            log.warning(
                "extract_page_specs attempt %d failed for %s: %s", attempt + 1, url, e
            )
            if attempt < retries - 1:
                time.sleep(2**attempt)
    return ""


def extract_page_specs_json(url: str, instruction: str, retries: int = 3) -> Any:
    """Like extract_page_specs but requests JSON output and parses it."""
    json_instruction = (
        f"{instruction}\n\n"
        "Return ONLY valid JSON. No markdown, no explanation, no code fences."
    )
    raw = extract_page_specs(url, json_instruction, retries=retries)
    raw = raw.strip()
    for fence in ("```json", "```JSON", "```"):
        if raw.startswith(fence):
            raw = raw[len(fence) :].strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        import re

        match = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
        log.warning("Failed to parse JSON from extract_page_specs: %.200s", raw)
        return None


def search_and_extract_json(
    query: str,
    extraction_instruction: str,
    extra_context: str = "",
    retries: int = 3,
) -> Any:
    """
    One-shot: search Google via Gemini grounding AND extract structured data
    from the found content in a single model call.

    Best for: "find the spec sheet for X and return it as JSON"
    """
    llm = _get_llm_with_search()
    prompt = (f"{extra_context}\n\n" if extra_context else "") + (
        f"Search for: {query}\n\n"
        f"From the search results, {extraction_instruction}\n\n"
        "Return ONLY valid JSON (object or array). No markdown, no explanation."
    )
    for attempt in range(retries):
        try:
            resp = llm.invoke(prompt)
            raw = resp.content if hasattr(resp, "content") else str(resp)
            raw = raw.strip()
            for fence in ("```json", "```JSON", "```"):
                if raw.startswith(fence):
                    raw = raw[len(fence) :].strip()
                if raw.endswith("```"):
                    raw = raw[:-3].strip()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                import re

                match = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(1))
                    except Exception:
                        pass
                log.warning("JSON parse failed on attempt %d: %.200s", attempt + 1, raw)
        except Exception as e:
            log.warning("search_and_extract_json attempt %d failed: %s", attempt + 1, e)
            if attempt < retries - 1:
                time.sleep(2**attempt)
    return None
