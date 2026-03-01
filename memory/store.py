"""
store.py — LanceDB vector store for QIDIStudio knowledge base.

Table schema:
  id          : str  — UUID
  date        : str  — YYYY-MM-DD
  category    : str  — domain bucket (see CATEGORIES)
  topic       : str  — short phrase / section heading
  decision    : str  — summary / first paragraph
  rationale   : str  — why it matters / source note
  content     : str  — FULL verbatim text of the chunk (code blocks and all)
  source      : str  — e.g. "copilot-instructions/section", "session", "protocol"
  vector      : List[float]  — 384-dim sentence-transformers embedding of topic+decision

Embedding model: all-MiniLM-L6-v2 (local, no API key)
"""

import os
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[1] / ".env")

import lancedb
import pyarrow as pa
from sentence_transformers import SentenceTransformer

LANCEDB_PATH = os.getenv("LANCEDB_PATH", "data/lancedb")
LANCEDB_TABLE = os.getenv("LANCEDB_TABLE", "qidistudio_learnings")
EMBED_DIMS = int(os.getenv("LANCEDB_EMBEDDING_DIMS", "384"))
EMBED_MODEL = "all-MiniLM-L6-v2"

CATEGORIES = [
    "bpy_pipeline",
    "build_system",
    "cpp_gotcha",
    "api_key",
    "hooks_and_memory",
    "gcode_refiner",
    "workflow",
    "tools_and_env",
    "architecture",
    "general",
]

_embedder: Optional[SentenceTransformer] = None
_db = None
_table = None


def _get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


def _get_db():
    global _db
    if _db is None:
        # Support both local paths and remote URIs (gs://, s3://, az://)
        if LANCEDB_PATH.startswith(("gs://", "s3://", "az://", "gcs://")):
            uri = LANCEDB_PATH
            _db = lancedb.connect(uri)
        else:
            repo_root = Path(__file__).parents[1]
            db_path = repo_root / LANCEDB_PATH
            db_path.mkdir(parents=True, exist_ok=True)
            _db = lancedb.connect(str(db_path))
    return _db


_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("date", pa.string()),
        pa.field("category", pa.string()),
        pa.field("topic", pa.string()),
        pa.field("decision", pa.string()),
        pa.field("rationale", pa.string()),
        pa.field("content", pa.string()),  # ← full verbatim text
        pa.field("source", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), EMBED_DIMS)),
    ]
)


def _get_table():
    global _table
    if _table is not None:
        return _table

    db = _get_db()
    try:
        resp = db.list_tables()  # lancedb >= 0.5 — returns ListTablesResponse
        existing = list(resp.tables) if hasattr(resp, "tables") else list(resp)
    except AttributeError:
        existing = db.table_names()  # older API

    if LANCEDB_TABLE in existing:
        t = db.open_table(LANCEDB_TABLE)
        # Schema migration: if 'content' column missing, drop and recreate
        if "content" not in t.schema.names:
            db.drop_table(LANCEDB_TABLE)
            _table = db.create_table(LANCEDB_TABLE, schema=_SCHEMA)
        else:
            _table = t
    else:
        _table = db.create_table(LANCEDB_TABLE, schema=_SCHEMA)

    return _table


def embed(text: str) -> list[float]:
    return _get_embedder().encode(text, normalize_embeddings=True).tolist()


def upsert_learning(
    topic: str,
    decision: str,
    rationale: str = "",
    category: str = "general",
    source: str = "session",
    learning_date: Optional[str] = None,
    content: str = "",
    existing_id: Optional[str] = None,
) -> str:
    """
    Insert or replace a row. Topic is the dedup key.
    `content` holds the full verbatim text of the chunk.
    Returns the row id.
    """
    table = _get_table()
    row_id = existing_id or str(uuid.uuid4())
    row_date = learning_date or date.today().isoformat()

    embed_text = f"{topic}: {decision}. {rationale}"
    vector = embed(embed_text)

    row = {
        "id": row_id,
        "date": row_date,
        "category": category,
        "topic": topic,
        "decision": decision,
        "rationale": rationale,
        "content": content or decision,
        "source": source,
        "vector": vector,
    }

    try:
        table.delete(f"topic = '{topic.replace(chr(39), chr(39)*2)}'")
    except Exception:
        pass

    table.add([row])
    return row_id


def query_similar(
    query_text: str, n: int = 10, category: Optional[str] = None
) -> list[dict]:
    """Retrieve the n most semantically similar rows."""
    table = _get_table()
    vector = embed(query_text)

    try:
        q = table.search(vector).limit(n)
        if category:
            q = q.where(f"category = '{category}'")
        return q.to_list()
    except Exception:
        return []


def get_all(source_filter: Optional[str] = None) -> list[dict]:
    """Return every row, optionally filtered by source prefix."""
    try:
        rows = _get_table().to_arrow().to_pylist()
        if source_filter:
            rows = [
                r for r in rows if str(r.get("source", "")).startswith(source_filter)
            ]
        return sorted(rows, key=lambda r: (r.get("source", ""), r.get("topic", "")))
    except Exception:
        return []


def get_recent(n: int = 30, days: int = 90) -> list[dict]:
    """Return rows with a date set, sorted newest-first, limited to `n`."""
    try:
        rows = _get_table().to_arrow().to_pylist()
        from datetime import timedelta

        cutoff = (date.today() - timedelta(days=days)).isoformat()
        dated = [r for r in rows if (r.get("date") or "") >= cutoff]
        return sorted(dated, key=lambda r: r.get("date", ""), reverse=True)[:n]
    except Exception:
        return []


def count() -> int:
    try:
        return _get_table().count_rows()
    except Exception:
        try:
            return len(_get_table().to_arrow().to_pylist())
        except Exception:
            return 0


if __name__ == "__main__":
    if LANCEDB_PATH.startswith(("gs://", "s3://", "az://", "gcs://")):
        print(f"LanceDB at : {LANCEDB_PATH}")
    else:
        print(f"LanceDB at : {Path(__file__).parents[1] / LANCEDB_PATH}")
    print(f"Table      : {LANCEDB_TABLE}")
    print(f"Rows       : {count()}")
    results = query_similar("cmake build command", n=3)
    print(f"Sample query 'cmake build command' → {len(results)} results")
    for r in results:
        print(f"  [{r.get('category')}] {r.get('topic')[:80]}")
