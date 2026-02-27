"""
store.py — LanceDB vector store for QIDIStudio session learnings.

Table schema:
  id          : str  — UUID
  date        : str  — YYYY-MM-DD
  category    : str  — domain bucket (see CATEGORIES)
  topic       : str  — short phrase, e.g. "calc_normals_split removed in Blender 4.1"
  decision    : str  — what was decided/discovered
  rationale   : str  — why it matters
  source      : str  — "copilot-instructions" | "knowledge-doc" | "session"
  vector      : List[float]  — 384-dim sentence-transformers embedding

Embedding model: all-MiniLM-L6-v2 (runs locally, no API key required)
"""

import os
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[1] / ".env")

# ── LanceDB setup ─────────────────────────────────────────────────────────
import lancedb
import pyarrow as pa
from sentence_transformers import SentenceTransformer

LANCEDB_PATH  = os.getenv("LANCEDB_PATH",  "data/lancedb")
LANCEDB_TABLE = os.getenv("LANCEDB_TABLE", "qidistudio_learnings")
EMBED_DIMS    = int(os.getenv("LANCEDB_EMBEDDING_DIMS", "384"))
EMBED_MODEL   = "all-MiniLM-L6-v2"

CATEGORIES = [
    "bpy_pipeline",      # Blender/apply_texture_bpy.py specifics
    "build_system",      # CMake, MSBuild, deps, sync workflow
    "cpp_gotcha",        # C++ / wxWidgets pitfalls
    "api_key",           # confirmed API values / endpoints
    "hooks_and_memory",  # VS Code hooks, PreCompact, Save This Protocol
    "gcode_refiner",     # GCodeRefiner post-processor
    "workflow",          # agent/user workflow conventions
    "tools_and_env",     # Python envs, Blender paths, terminal names
    "architecture",      # system design decisions
    "general",           # catch-all
]

# Lazily loaded so import is fast
_embedder: Optional[SentenceTransformer] = None
_db: Optional[lancedb.LanceDBConnection] = None
_table = None


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


def _get_db():
    global _db
    if _db is None:
        repo_root = Path(__file__).parents[1]
        db_path   = repo_root / LANCEDB_PATH
        db_path.mkdir(parents=True, exist_ok=True)
        _db = lancedb.connect(str(db_path))
    return _db


def _get_table():
    global _table
    if _table is not None:
        return _table

    db = _get_db()
    existing = db.table_names()

    if LANCEDB_TABLE not in existing:
        schema = pa.schema([
            pa.field("id",        pa.string()),
            pa.field("date",      pa.string()),
            pa.field("category",  pa.string()),
            pa.field("topic",     pa.string()),
            pa.field("decision",  pa.string()),
            pa.field("rationale", pa.string()),
            pa.field("source",    pa.string()),
            pa.field("vector",    pa.list_(pa.float32(), EMBED_DIMS)),
        ])
        _table = db.create_table(LANCEDB_TABLE, schema=schema)
    else:
        _table = db.open_table(LANCEDB_TABLE)

    return _table


def embed(text: str) -> list[float]:
    """Embed a string with the local sentence-transformers model."""
    return _get_embedder().encode(text, normalize_embeddings=True).tolist()


def upsert_learning(
    topic: str,
    decision: str,
    rationale: str,
    category: str = "general",
    source: str = "session",
    learning_date: Optional[str] = None,
    existing_id: Optional[str] = None,
) -> str:
    """
    Insert or replace a learning row.
    Uses topic as the dedup key — if a row with the same topic exists, replace it.
    Returns the row id.
    """
    table = _get_table()
    row_id = existing_id or str(uuid.uuid4())
    row_date = learning_date or date.today().isoformat()

    # Embed the combined text for semantic search
    embed_text = f"{topic}: {decision}. {rationale}"
    vector = embed(embed_text)

    row = {
        "id":        row_id,
        "date":      row_date,
        "category":  category,
        "topic":     topic,
        "decision":  decision,
        "rationale": rationale,
        "source":    source,
        "vector":    vector,
    }

    # Check for existing row with same topic → delete then re-insert
    try:
        table.delete(f"topic = '{topic.replace(chr(39), chr(39)*2)}'")
    except Exception:
        pass  # table may be empty; safe to ignore

    table.add([row])
    return row_id


def query_similar(query_text: str, n: int = 10, category: Optional[str] = None) -> list[dict]:
    """
    Retrieve the n most semantically similar learnings.
    Optionally filter by category.
    """
    table = _get_table()
    vector = embed(query_text)

    try:
        q = table.search(vector).limit(n)
        if category:
            q = q.where(f"category = '{category}'")
        results = q.to_list()
    except Exception:
        results = []

    return results


def get_recent(n: int = 30, days: int = 90) -> list[dict]:
    """Return the n most recently added learnings (by date string, descending)."""
    table = _get_table()
    try:
        from datetime import timedelta
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        rows = (
            table.search()
                 .where(f"date >= '{cutoff}'")
                 .limit(n)
                 .to_list()
        )
    except Exception:
        try:
            rows = table.to_pandas().tail(n).to_dict("records")
        except Exception:
            rows = []

    # Sort by date descending
    return sorted(rows, key=lambda r: r.get("date", ""), reverse=True)


def count() -> int:
    """Return total number of stored learnings."""
    try:
        return len(_get_table().to_pandas())
    except Exception:
        return 0


if __name__ == "__main__":
    # Quick smoke test
    print(f"LanceDB at: {Path(__file__).parents[1] / LANCEDB_PATH}")
    print(f"Table: {LANCEDB_TABLE}")
    print(f"Existing rows: {count()}")

    test_id = upsert_learning(
        topic="store.py smoke test",
        decision="LanceDB initialised and write/read confirmed working",
        rationale="Validates memory module is operational",
        category="hooks_and_memory",
        source="smoke_test",
    )
    print(f"Wrote test row: {test_id}")
    print(f"Total rows now: {count()}")

    results = query_similar("LanceDB test", n=3)
    print(f"Query returned {len(results)} results")
    for r in results:
        print(f"  [{r.get('category')}] {r.get('topic')} — {r.get('date')}")
