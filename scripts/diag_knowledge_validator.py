"""Quick knowledge_validator diagnostic — shows full error."""
import sys, tempfile, pathlib

REPO_ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env", override=True)

print("Importing knowledge_validator...")
try:
    from scripts.knowledge_validator import validate_document
    print("Import OK")
except Exception as e:
    import traceback
    print(f"Import FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

test_md = """
# Test Document

> One-sentence abstract for test purposes.

## 1. Motivation
This document tests the knowledge validator pipeline integration.

## 2. Core Concepts
The speed of light is approximately $c = 3 \\times 10^8$ m/s in vacuum.

## 3. Implementation
No implementation required for this test.

## 4. Validation Rationale
Test document — no historical claims to validate.

## 5. Consequences
None.

## 6. References
- [1] NIST, Fundamental Constants, 2018.
"""

print("Writing temp file...")
with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, encoding="utf-8") as f:
    f.write(test_md)
    tmp = f.name
print(f"Temp file: {tmp}")

print("Running validate_document()...")
try:
    result = validate_document(tmp)
    print(f"Type: {type(result)}")
    print(f"Has verdicts: {hasattr(result, 'verdicts')}")
    if hasattr(result, 'verdicts'):
        print(f"Verdicts type: {type(result.verdicts)}")
        print(f"Verdicts count: {len(result.verdicts)}")
        print("PASS")
    else:
        print(f"FAIL: no verdicts attr. Result: {result}")
except Exception as e:
    import traceback
    print(f"EXCEPTION: {e}")
    traceback.print_exc()
finally:
    pathlib.Path(tmp).unlink(missing_ok=True)
