"""
agents/parts_catalog/search_utils.py

Dual-engine search for parts catalog harvesters:
  1. Gemini Grounded Search  — native Google Search baked into the model response.
     No CSE ID needed. Uses GOOGLE_API_KEY. Best for: discovery, finding product
     pages, cross-referencing specs, finding distributors.
  2. Tavily  — structured web scraping with content extraction. Best for:
     extracting clean spec text from a known product page URL.

Usage:
    from agents.parts_catalog.search_utils import grounded_search, tavily_search

    # Discovery: find all NEMA 23 motors on Stepperonline
    results = grounded_search("NEMA 23 stepper motor specifications site:stepperonline.com")

    # Deep spec extraction from a product page
    specs = tavily_search("57HS76-3004 stepper motor datasheet specifications", max_results=5)
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

log = logging.getLogger("parts_catalog.search")


# ─── Gemini Grounded Search ───────────────────────────────────────────────────


def grounded_search(
    query: str,
    *,
    model: str = "gemini-2.0-flash",
    temperature: float = 0.1,
    max_retries: int = 3,
) -> str:
    """
    Call Gemini with Google Search grounding enabled.
    Returns the full text response (which already has web search results baked in).
    This uses Gemini's native Google Search tool — no Custom Search Engine ID needed.
    """
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

    gemini_model = genai.GenerativeModel(
        model_name=model,
        tools="google_search_retrieval",  # built-in grounding tool
        generation_config={"temperature": temperature},
    )

    for attempt in range(1, max_retries + 1):
        try:
            response = gemini_model.generate_content(query)
            return response.text
        except Exception as e:
            log.warning("Gemini grounded search attempt %d failed: %s", attempt, e)
            if attempt < max_retries:
                time.sleep(2**attempt)
    return ""


def grounded_extract(
    prompt: str,
    *,
    system: str = "",
    model: str = "gemini-2.0-flash",
) -> str:
    """
    Gemini with grounded search + a structured extraction prompt.
    Use when you want the model to search AND return JSON.
    """
    full_prompt = (system + "\n\n" + prompt).strip() if system else prompt
    return grounded_search(full_prompt, model=model)


# ─── Tavily Search ────────────────────────────────────────────────────────────


def tavily_search(
    query: str,
    *,
    max_results: int = 5,
    include_raw_content: bool = True,
    search_depth: str = "advanced",
) -> list[dict[str, Any]]:
    """
    Tavily structured search. Returns list of {url, title, content, raw_content}.
    Best for extracting clean spec text from known product/datasheet pages.
    search_depth: "basic" (fast) | "advanced" (deeper, costs 2 Tavily credits)
    """
    from tavily import TavilyClient  # type: ignore

    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    try:
        resp = client.search(
            query=query,
            max_results=max_results,
            include_raw_content=include_raw_content,
            search_depth=search_depth,
        )
        return resp.get("results", [])
    except Exception as e:
        log.warning("Tavily search failed for '%s': %s", query[:80], e)
        return []


def tavily_extract(url: str) -> str:
    """Extract full content from a single URL via Tavily."""
    from tavily import TavilyClient  # type: ignore

    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    try:
        resp = client.extract(urls=[url])
        results = resp.get("results", [])
        if results:
            return results[0].get("raw_content", "")
    except Exception as e:
        log.warning("Tavily extract failed for %s: %s", url, e)
    return ""


# ─── Gemini JSON extraction helper ──────────────────────────────────────────


def gemini_to_json(
    prompt: str, *, model: str = "gemini-2.5-flash"
) -> dict | list | None:
    """
    Call Gemini (no grounding) and parse the response as JSON.
    Strips markdown code fences if present. Returns None on failure.
    Use for structured extraction AFTER grounded_search has gathered raw data.
    """
    import re
    from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore

    llm = ChatGoogleGenerativeAI(
        model=model,
        google_api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0.0,
    )
    try:
        response = llm.invoke(prompt)
        text = response.content.strip()
        # Strip markdown fences
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
        # Find the first JSON object or array
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if match:
            return json.loads(match.group(1))
    except Exception as e:
        log.warning("gemini_to_json failed: %s", e)
    return None
