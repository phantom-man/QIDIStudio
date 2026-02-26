"""Quick smoke test for procedural generators."""
import sys, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from generate_skin_assets import PROCEDURAL_GENERATORS, generate_procedural, _HAS_SHAPELY

print(f"Shapely available : {_HAS_SHAPELY}")
print(f"Procedures        : {list(PROCEDURAL_GENERATORS.keys())}")

if not _HAS_SHAPELY:
    print("ERROR: Shapely not importable — install it first.")
    sys.exit(1)

with tempfile.TemporaryDirectory() as td:
    root = pathlib.Path(td)
    all_ok = True
    for cat in PROCEDURAL_GENERATORS:
        p = root / cat / f"{cat}_01.png"
        ok = generate_procedural(cat, 1, p)
        size = p.stat().st_size if ok else 0
        status = "OK" if ok else "FAIL"
        print(f"  {cat:<24} {status}  ({size:,} bytes)")
        if not ok:
            all_ok = False

print()
print("All generators OK" if all_ok else "SOME GENERATORS FAILED")
