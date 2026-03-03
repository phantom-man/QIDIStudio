"""Show last N rows from the GCS LanceDB store via store.py (reads .env)."""

import sys

sys.path.insert(0, "memory")
from store import (
    get_all,
)  # uses LANCEDB_PATH from .env → gs://qidistudio-lancedb/lancedb

rows = get_all()
print(f"Total rows: {len(rows)}")
print()
for row in rows[-5:]:
    src = row.get("source", "?")
    topic = row.get("topic", "?")
    content = str(row.get("content", ""))[:120]
    print(f"  [{src}]")
    print(f"  topic  : {topic}")
    print(f"  content: {content}")
    print()
