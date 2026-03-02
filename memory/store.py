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
from datetime import date, timedelta
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


# GCS storage options — improve reliability for remote tables (v0.29+/v0.30)
_GCS_STORAGE_OPTIONS = {
    "timeout": "60s",
    "connect_timeout": "30s",
    "max_retries": "5",
}


def _get_db():
    global _db
    if _db is None:
        # Support both local paths and remote URIs (gs://, s3://, az://)
        if LANCEDB_PATH.startswith(("gs://", "s3://", "az://", "gcs://")):
            _db = lancedb.connect(
                LANCEDB_PATH,
                storage_options=_GCS_STORAGE_OPTIONS,
            )
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
    # Open-first pattern: avoids list_tables() membership issues on GCS
    # (list_tables() may return objects that don't compare equal to plain strings).
    try:
        t = db.open_table(LANCEDB_TABLE)
        # Schema migration: if 'content' column missing, drop and recreate
        if "content" not in t.schema.names:
            db.drop_table(LANCEDB_TABLE)
            _table = db.create_table(LANCEDB_TABLE, schema=_SCHEMA)
        else:
            _table = t
    except Exception:
        # Table does not exist yet — create it fresh
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
    Insert or replace a single row. Topic is the dedup key.
    For syncing many rows at once, prefer batch_upsert() — it does one
    embed pass + one GCS write instead of N round trips.
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


def batch_upsert(rows: list[dict], replace_all: bool = False) -> tuple[int, int]:
    """
    Upsert many rows in a single GCS round-trip pair.

    Instead of N×(delete+add) calls, this does:
      1. One batch embed pass over all topics+decisions (GPU/CPU parallelism)
      2a. If replace_all=True: DELETE everything from the table (eliminates orphan rows
          from stale/renamed topics in old doc versions) — use this for full syncs.
      2b. If replace_all=False: DELETE WHERE topic IN (...) covering all new topics.
      3. One table.add() writing all rows as a single fragment

    Returns (inserted, skipped).
    """
    table = _get_table()
    embedder = _get_embedder()
    today = date.today().isoformat()

    valid = [r for r in rows if (r.get("topic") or "").strip()]
    skipped = len(rows) - len(valid)
    if not valid:
        return 0, skipped

    # ── 1. Batch embed all texts at once ──────────────────────────────────
    embed_texts = [
        f"{r['topic']}: {r.get('decision', '')}. {r.get('rationale', '')}"
        for r in valid
    ]
    vectors = embedder.encode(
        embed_texts,
        normalize_embeddings=True,
        batch_size=64,
        show_progress_bar=False,
    )

    # ── 2. Delete rows ───────────────────────────────────────────────────────
    if replace_all:
        # Scoped rebuild — delete only document-sourced rows so that agent-written
        # rows (source LIKE 'agents/%') are NEVER wiped by a routine extract run.
        # Agent contributions are permanent unless explicitly deleted by topic.
        try:
            table.delete("source NOT LIKE 'agents/%'")
        except Exception:
            try:
                # Fallback: read the table and delete non-agent rows one by one.
                # Slower but preserves agent rows even if LIKE predicate fails.
                existing = table.to_arrow().to_pylist()
                for row in existing:
                    src = str(row.get("source", ""))
                    if not src.startswith("agents/") and row.get("topic"):
                        esc = row["topic"].replace("'", "''")
                        try:
                            table.delete(f"topic = '{esc}'")
                        except Exception:
                            pass
            except Exception:
                pass
    else:
        # Targeted delete — only remove rows for topics we're replacing.
        escaped = [t["topic"].replace("'", "''") for t in valid]
        in_clause = ", ".join(f"'{t}'" for t in escaped)
        try:
            table.delete(f"topic IN ({in_clause})")
        except Exception:
            # GCS LanceDB may reject large IN clauses — fall back to per-row deletes.
            # This is slower but guarantees no row accumulation over repeated runs.
            for esc_topic in escaped:
                try:
                    table.delete(f"topic = '{esc_topic}'")
                except Exception:
                    pass

    # ── 3. Build all rows and write in a single add() call ────────────────
    all_rows = []
    for r, vec in zip(valid, vectors):
        all_rows.append(
            {
                "id": r.get("id") or str(uuid.uuid4()),
                "date": r.get("date") or today,
                "category": (r.get("category") or "general").strip(),
                "topic": r["topic"].strip(),
                "decision": (r.get("decision") or "").strip(),
                "rationale": (r.get("rationale") or "").strip(),
                "content": (r.get("content") or r.get("decision") or "").strip(),
                "source": (r.get("source") or "unknown"),
                "vector": vec.tolist(),
            }
        )

    table.add(all_rows)
    return len(all_rows), skipped


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


def maintenance(
    compact: bool = True,
    vacuum_days: int = 0,
) -> dict:
    """Compact small GCS fragments and optionally prune old table versions.

    GCS storage costs for this knowledge base are negligible — the full version
    history is small and deliberately preserved for Time Travel / audit purposes.
    compact_files() is safe to run periodically (merges tiny fragment files for
    better read performance).

    ╔══════════════════════════════════════════════════════════════════════════╗
    ║  WARNING — DO NOT VACUUM WITHOUT CONSULTING THE REPO OWNER FIRST.       ║
    ║  vacuum() permanently deletes historical GCS objects and makes those    ║
    ║  table versions unrecoverable.  This should happen at most once a year  ║
    ║  and only after explicit sign-off.  The default keeps vacuum disabled.  ║
    ╚══════════════════════════════════════════════════════════════════════════╝

    Args:
        compact:     Merge small fragment files into larger ones (safe, reversible).
        vacuum_days: Permanently delete GCS objects for versions older than this
                     many days.  Default 0 = DISABLED.  Do not enable without
                     consulting the repo owner — data loss is irreversible.

    Returns dict with keys: version (int), compacted (bool), vacuumed (bool).
    """
    table = _get_table()
    result = {"version": None, "compacted": False, "vacuumed": False}

    if compact:
        try:
            table.compact_files()
            result["compacted"] = True
        except Exception as exc:
            print(f"[maintenance] compact_files failed: {exc}")

    if vacuum_days > 0:
        # ── CONSULT REPO OWNER BEFORE ENABLING ────────────────────────────────
        # Vacuuming permanently removes GCS objects. Only run after sign-off.
        try:
            table.vacuum(older_than=timedelta(days=vacuum_days))
            result["vacuumed"] = True
        except Exception as exc:
            print(f"[maintenance] vacuum failed: {exc}")

    try:
        result["version"] = table.version()
    except Exception:
        pass

    return result


# ── Time Travel (LanceDB v0.29+ / v0.30+) ─────────────────────────────────────


def current_version() -> Optional[int]:
    """Return the current manifest version number of the table on GCS."""
    try:
        return _get_table().version()
    except Exception:
        return None


def open_at_version(version: int):
    """Return a Table pinned to a specific historical version (read-only snapshot).

    Usage:
        snap = open_at_version(5)
        rows = snap.to_arrow().to_pylist()

    Safe for agents: the main `_table` singleton is NOT replaced, so normal writes
    continue against the current HEAD.  Snapshots are read-only.
    """
    db = _get_db()
    return db.open_table(LANCEDB_TABLE, version=version)


def open_at_timestamp(timestamp: str):
    """Return a Table pinned to a specific ISO-8601 timestamp (read-only snapshot).

    Usage:
        snap = open_at_timestamp("2026-03-01T12:00:00Z")
        rows = snap.to_arrow().to_pylist()
    """
    db = _get_db()
    return db.open_table(LANCEDB_TABLE, timestamp=timestamp)


def query_similar_at_version(
    query_text: str,
    version: int,
    n: int = 10,
    category: Optional[str] = None,
) -> list[dict]:
    """Run a vector search against a historical version of the table.

    Useful for auditing what an agent saw at a prior point in time.
    """
    snap = open_at_version(version)
    vector = embed(query_text)
    try:
        q = snap.search(vector).limit(n)
        if category:
            q = q.where(f"category = '{category}'")
        return q.to_list()
    except Exception:
        return []


if __name__ == "__main__":
    if LANCEDB_PATH.startswith(("gs://", "s3://", "az://", "gcs://")):
        print(f"LanceDB at : {LANCEDB_PATH}")
    else:
        print(f"LanceDB at : {Path(__file__).parents[1] / LANCEDB_PATH}")
    print(f"Table      : {LANCEDB_TABLE}")
    print(f"Rows       : {count()}")
    results = query_similar("cmake build command", n=3)
    print(f"Sample query 'cmake build command' -> {len(results)} results")
    for r in results:
        topic = (r.get("topic") or "")[:80].encode("ascii", errors="replace").decode()
        print(f"  [{r.get('category')}] {topic}")
