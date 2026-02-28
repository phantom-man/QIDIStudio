"""Diagnostic wrapper for ai_debug_pipeline.run() — captures ALL exceptions."""

import sys
import traceback
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

OUT = pathlib.Path(__file__).parent / "_diag_exception.txt"

try:
    from scripts import ai_debug_pipeline as p

    rc = p.run()
    OUT.write_text(f"SUCCESS rc={rc}\n", encoding="utf-8")
    print(f"SUCCESS rc={rc}")
    sys.exit(rc)
except Exception:
    tb = traceback.format_exc()
    OUT.write_text(tb, encoding="utf-8")
    print("EXCEPTION CAUGHT:")
    print(tb)
    sys.exit(99)
