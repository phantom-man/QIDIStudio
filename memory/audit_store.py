"""Quick audit of LanceDB content — what's fat, what's duplicated."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from memory.store import get_all

rows = get_all()
print(f"Total rows in LanceDB: {len(rows)}")

by_source = {}
for r in rows:
    s = r.get("source", "?")
    by_source[s] = by_source.get(s, 0) + 1
for k, v in sorted(by_source.items()):
    print(f"  {v:3d}  {k}")

print()
print("Top 10 fattest rows by content length:")
fat = sorted(rows, key=lambda r: len(r.get("content") or ""), reverse=True)[:10]
for r in fat:
    clen = len(r.get("content") or "")
    topic = (r.get("topic") or "")[:70]
    src = r.get("source") or ""
    print(f"  {clen:6d} chars  [{src}]  {topic}")

print()
total_chars = sum(len(r.get("content") or "") for r in rows)
print(f"Total content chars in store: {total_chars:,}")
print(f"Avg per row: {total_chars // max(len(rows),1):,}")
