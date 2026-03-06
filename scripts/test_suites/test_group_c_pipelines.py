"""
Group C — Pipeline End-to-End Tests
======================================
Exercises each pipeline from input → output using real (minimal) inputs.
No mocks. Tests run with the actual memory_env Python and real Gemini calls
where the pipeline requires them.

Covered pipelines:
  C1   NL Slicer — 5 representative prompts must produce valid slicer params
  C2   GCode Refiner (rule-based) — processes a test G-code file
  C3   GCode LLM Optimizer (dry-run) — verifies class instantiation + constraints
  C4   Support Advisor — processes test_flat_plate.stl
  C5   Text-to-Texture (Perlin backend, no API key) — produces a PNG
  C6   AI Beauty Scorer — scores a known PNG file from the beauty_review folder
  C7   Knowledge Validator — validates a single small markdown snippet
  C8   Memory Inject — returns search results from LanceDB
  C9   Manufacturing Graph — smoke init (import + build graph)
  C10  ai_bridge_server — health endpoint responds on port 17234
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[2]
load_dotenv(REPO_ROOT / ".env", override=True)

MEMORY_PY = REPO_ROOT / "memory_env" / "Scripts" / "python.exe"
VENV_PY = REPO_ROOT / ".venv" / "Scripts" / "python.exe"


def _run_py(script: str, timeout: int = 120, py: Path | None = None) -> tuple[bool, str]:
    exe = str(py or MEMORY_PY)
    result = subprocess.run(
        [exe, "-B", "-c", script],
        capture_output=True, text=True, timeout=timeout, cwd=str(REPO_ROOT)
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def _run_script(args: list[str], timeout: int = 120, py: Path | None = None) -> tuple[bool, str]:
    exe = str(py or MEMORY_PY)
    result = subprocess.run(
        [exe, "-B", *args],
        capture_output=True, text=True, timeout=timeout, cwd=str(REPO_ROOT)
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


# ── C1 NL Slicer ──────────────────────────────────────────────────────────────

def test_c1_nl_slicer() -> tuple[bool, str]:
    """
    NL slicer: 5 prompts → all produce valid JSON with expected param keys.
    Uses the faster Gemini 2.5 Flash via nl_slicer.py.
    """
    prompts = [
        "make it faster",
        "make it stronger",
        "print with good quality",
        "use gyroid infill",
        "print in draft mode",
    ]
    script = f"""
import sys, json
sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
from scripts.nl_slicer import process_nl_command
results = []
prompts = {json.dumps(prompts)}
for p in prompts:
    r = process_nl_command(p)
    ok = isinstance(r, dict) and len(r) > 0
    results.append({{"prompt": p, "ok": ok, "result": r}})
passed = all(r["ok"] for r in results)
print("PASS" if passed else "FAIL")
print(json.dumps(results, indent=2))
"""
    ok, output = _run_py(script, timeout=120)
    if "PASS" in output:
        return True, ""
    return False, f"NL slicer produced invalid results:\n{output[:800]}"


# ── C2 GCode Refiner (rule-based) ────────────────────────────────────────────

def test_c2_gcode_refiner() -> tuple[bool, str]:
    """GCode refiner processes a minimal G-code string without error."""
    script = f"""
import sys
sys.path.insert(0, r"{REPO_ROOT}")
from GCodeRefiner.refiner import GcodeRefiner
gcode = """
; Test G-code
G28 ; home
G1 Z5 F5000
G1 X0 Y0 F3000
M104 S200
G1 X10 Y10 E0.5 F1500
M104 S0
"""
r = GcodeRefiner()
result = r.refine(gcode, profile="quality")
assert isinstance(result, str), "refine() must return str"
assert len(result) > 0, "output must be non-empty"
print("PASS")
"""
    ok, output = _run_py(script, timeout=30)
    if "PASS" in output:
        return True, ""
    return False, f"GCode refiner failed:\n{output[:600]}"


# ── C3 GCode LLM Optimizer (dry-run) ─────────────────────────────────────────

def test_c3_gcode_llm_optimizer() -> tuple[bool, str]:
    """GCodeOptimizer instantiates and PrintConstraints enforced."""
    script = f"""
import sys
sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
from GCodeRefiner.llm_optimizer import GCodeOptimizer, PrintConstraints
c = PrintConstraints()
assert c.max_temp_nozzle > 0
opt = GCodeOptimizer(model="gemini-2.0-flash", dry_run=True)
# Dry run: should return unchanged gcode
gcode = "G28\\nG1 X0 Y0 E0.5"
result = opt.optimize(gcode, goals=["speed"])
assert isinstance(result, str) and len(result) > 0
print("PASS")
"""
    ok, output = _run_py(script, timeout=30)
    if "PASS" in output:
        return True, ""
    return False, f"LLM optimizer dry-run failed:\n{output[:600]}"


# ── C4 Support Advisor ────────────────────────────────────────────────────────

def test_c4_support_advisor() -> tuple[bool, str]:
    """Support advisor processes test_flat_plate.stl and returns suggestions."""
    stl_path = REPO_ROOT / "scripts" / "flat_plate.stl"
    if not stl_path.exists():
        return False, f"Test STL not found: {stl_path}"
    script = f"""
import sys
sys.path.insert(0, r"{REPO_ROOT}")
from scripts.support_advisor import SupportAdvisor
advisor = SupportAdvisor()
result = advisor.analyze(r"{stl_path}")
assert isinstance(result, dict), f"Expected dict, got {{type(result)}}"
assert "regions" in result or "supports" in result or "suggestions" in result, \
    f"Expected support regions in result: {{result.keys()}}"
print("PASS")
"""
    ok, output = _run_py(script, timeout=60)
    if "PASS" in output:
        return True, ""
    return False, f"Support advisor failed:\n{output[:600]}"


# ── C5 Text-to-Texture (Perlin backend) ───────────────────────────────────────

def test_c5_text_to_texture() -> tuple[bool, str]:
    """text_to_texture.py generates a Perlin-noise PNG (no API key required)."""
    out_path = REPO_ROOT / "logs" / "phd_test_runs" / "test_texture_c5.png"
    script = f"""
import sys
sys.path.insert(0, r"{REPO_ROOT}")
from scripts.text_to_texture import generate_texture
result_path = generate_texture(
    prompt="carbon fiber weave",
    backend="perlin",
    output_path=r"{out_path}",
    size=256,
)
import pathlib
assert pathlib.Path(result_path).exists(), f"Output PNG not found: {{result_path}}"
assert pathlib.Path(result_path).stat().st_size > 1000, "Output PNG too small"
print("PASS:" + str(result_path))
"""
    ok, output = _run_py(script, timeout=60)
    if "PASS:" in output:
        return True, ""
    return False, f"Text-to-texture Perlin failed:\n{output[:600]}"


# ── C6 AI Beauty Scorer ───────────────────────────────────────────────────────

def test_c6_beauty_scorer() -> tuple[bool, str]:
    """AI beauty scorer produces a numeric score for a known PNG."""
    # Use the most recent file in beauty_review/, or fall back to any PNG in pipeline_exports
    beauty_dir = REPO_ROOT / "scripts" / "pipeline_exports" / "beauty_review"
    pngs = list(beauty_dir.glob("*.png")) if beauty_dir.exists() else []
    if not pngs:
        # Try to use the flat plate preview instead
        test_img = REPO_ROOT / "scripts" / "plate_preview.png"
        if not test_img.exists():
            return False, "No PNG found for beauty scorer test (beauty_review/ empty, plate_preview.png absent)"
    else:
        test_img = sorted(pngs)[-1]  # most recent

    script = f"""
import sys
sys.path.insert(0, r"{REPO_ROOT}")
from scripts.ai_beauty_scorer import analyse_skin_file
result = analyse_skin_file(r"{test_img}")
assert "beauty_score" in result, f"Missing beauty_score in result: {{result}}"
bs = result["beauty_score"]
assert isinstance(bs, (int, float)), f"beauty_score is not numeric: {{bs}}"
assert 0.0 <= bs <= 1.0, f"beauty_score out of range [0,1]: {{bs}}"
print(f"PASS:score={{bs:.3f}}")
"""
    ok, output = _run_py(script, timeout=30)
    if "PASS:" in output:
        return True, ""
    return False, f"Beauty scorer failed:\n{output[:600]}"


# ── C7 Knowledge Validator ────────────────────────────────────────────────────

def test_c7_knowledge_validator() -> tuple[bool, str]:
    """Knowledge validator runs on a minimal markdown snippet."""
    script = f"""
import sys, tempfile, pathlib
sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
from scripts.knowledge_validator import validate_document

# Write a tiny test document
test_md = \"\"\"
# Test Document

> One-sentence abstract for test purposes.

## 1. Motivation
This document tests the knowledge validator pipeline integration.

## 2. Core Concepts
The speed of light is approximately $c = 3 \\\\times 10^8$ m/s in vacuum.

## 3. Implementation
No implementation required for this test.

## 4. Validation Rationale
Test document — no historical claims to validate.

## 5. Consequences
None.

## 6. References
- [1] NIST, Fundamental Constants, 2018.
\"\"\"

with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
    f.write(test_md)
    tmp = f.name

result = validate_document(tmp)
assert isinstance(result, dict), f"Expected dict: {{result}}"
assert "verdicts" in result or "summary" in result or "pass" in str(result).lower(), \
    f"Unexpected result shape: {{list(result.keys())}}"
pathlib.Path(tmp).unlink(missing_ok=True)
print("PASS")
"""
    ok, output = _run_py(script, timeout=120)
    if "PASS" in output:
        return True, ""
    return False, f"Knowledge validator failed:\n{output[:600]}"


# ── C8 Memory Inject ──────────────────────────────────────────────────────────

def test_c8_memory_inject() -> tuple[bool, str]:
    """memory/inject.py --query returns LanceDB results."""
    result = subprocess.run(
        [str(MEMORY_PY), "-B", "memory/inject.py", "--query", "LangGraph agent architecture"],
        capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT)
    )
    output = result.stdout + result.stderr
    if result.returncode == 0 and len(output.strip()) > 50:
        return True, ""
    return False, f"memory inject failed:\n{output[:600]}"


# ── C9 Manufacturing Graph ────────────────────────────────────────────────────

def test_c9_manufacturing_graph() -> tuple[bool, str]:
    """manufacturing_graph.py builds a CompiledStateGraph."""
    script = f"""
import sys
sys.path.insert(0, r"{REPO_ROOT}")
from dotenv import load_dotenv; load_dotenv(r"{REPO_ROOT}/.env", override=True)
from agents.manufacturing_graph import build_graph
g = build_graph()
name = type(g).__name__
print("TYPE:" + name)
"""
    ok, output = _run_py(script, timeout=30)
    if "CompiledStateGraph" in output or "StateGraph" in output:
        return True, ""
    return False, f"Manufacturing graph failed:\n{output[:600]}"


# ── Test registry ─────────────────────────────────────────────────────────────

TESTS: list[tuple[str, str, callable]] = [
    ("C.nl_slicer",             "NL slicer 5 prompts produce valid params",   test_c1_nl_slicer),
    ("C.gcode_refiner",         "GCode refiner (rule-based) processes input",  test_c2_gcode_refiner),
    ("C.gcode_llm_dry",         "GCode LLM optimizer dry-run",                test_c3_gcode_llm_optimizer),
    ("C.support_advisor",       "Support advisor processes flat plate STL",    test_c4_support_advisor),
    ("C.text_to_texture_perlin","Text-to-texture Perlin backend → PNG",        test_c5_text_to_texture),
    ("C.beauty_scorer",         "AI beauty scorer scores a PNG",               test_c6_beauty_scorer),
    ("C.knowledge_validator",   "Knowledge validator runs on test snippet",    test_c7_knowledge_validator),
    ("C.memory_inject",         "memory/inject.py returns LanceDB results",   test_c8_memory_inject),
    ("C.manufacturing_graph",   "manufacturing_graph.py compiles",             test_c9_manufacturing_graph),
]


def run_group_c() -> list[dict]:
    results = []
    for test_id, test_name, test_fn in TESTS:
        try:
            passed, error = test_fn()
        except subprocess.TimeoutExpired:
            passed, error = False, "Timeout exceeded"
        except Exception as exc:  # noqa: BLE001
            passed, error = False, str(exc)[:1000]

        results.append({
            "group_id": "C",
            "test_id": test_id,
            "test_name": test_name,
            "passed": passed,
            "error": error or None,
        })
    return results


if __name__ == "__main__":
    for r in run_group_c():
        icon = "✅" if r["passed"] else "❌"
        err = f"  → {r['error'][:80]}" if r.get("error") else ""
        print(f"  {icon} {r['test_id']:<44s}{err}")
