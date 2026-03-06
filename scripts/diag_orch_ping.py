"""Quick orchestrator ping diagnostic - shows full error output."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=True)

print("Importing orchestrator...")
try:
    from agents.orchestrator import run

    print("Import OK")
except Exception as e:
    print(f"Import FAILED: {e}")
    sys.exit(1)

print("Calling run()...")
try:
    result = run("reply with exactly the single word ONLINE — no other text")
    print(f"run() returned type: {type(result)}")
    print(
        f"run() result keys: {list(result.keys()) if isinstance(result, dict) else 'N/A'}"
    )
    response = (result.get("final_response") or "").strip().upper()
    print(f"final_response: {response[:300]}")
    if "ONLINE" in response:
        print("PING_PASS")
    else:
        print(f"PING_FAIL: response did not contain ONLINE")
except Exception as e:
    import traceback

    print(f"EXCEPTION: {e}")
    traceback.print_exc()
