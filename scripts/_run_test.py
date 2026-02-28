"""Minimal wrapper to catch errors in ai_debug_pipeline.run()"""

import sys, traceback, os

os.chdir(r"C:\Users\User\source\repos\QIDIStudio")
sys.path.insert(0, ".")

print("Importing...", flush=True)
from scripts.ai_debug_pipeline import run, TEST_CASES

print("Imported OK", flush=True)

try:
    rc = run(TEST_CASES, render_heatmap=False)
    print(f"run() returned {rc}", flush=True)
except SystemExit as e:
    print(f"SystemExit: {e}", flush=True)
except Exception as e:
    print(f"EXCEPTION: {type(e).__name__}: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)

print("Done.", flush=True)
