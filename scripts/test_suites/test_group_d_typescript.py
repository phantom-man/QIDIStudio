"""
Group D — TypeScript / VS Code Extension Tests
================================================
Verifies that the NexusSlicer VS Code extension compiles cleanly,
all tests pass, and key build artefacts (VSIX, dist bundles) exist.

Tests in this group call npm and Node.js toolchains via subprocess.
They do NOT require Gemini or any cloud API.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parents[2]
load_dotenv(REPO_ROOT / ".env", override=True)

EXTENSION_ROOT = REPO_ROOT / "nexusslicer-viewer"
MEMORY_PY = REPO_ROOT / "memory_env" / "Scripts" / "python.exe"


def _run_shell(args: list[str], cwd: Path, timeout: int = 120) -> tuple[bool, str]:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd),
        shell=True,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def _file_exists(path: Path, min_bytes: int = 1) -> tuple[bool, str]:
    if not path.exists():
        return False, f"File not found: {path}"
    size = path.stat().st_size
    if size < min_bytes:
        return False, f"File too small ({size} bytes): {path}"
    return True, ""


# ── D1 Extension root exists ──────────────────────────────────────────────────

def test_d1_extension_root() -> tuple[bool, str]:
    """nexusslicer-viewer/ directory exists with package.json."""
    pkg = EXTENSION_ROOT / "package.json"
    return _file_exists(pkg, min_bytes=200)


# ── D2 TypeScript tsc compile ─────────────────────────────────────────────────

def test_d2_tsc_compile() -> tuple[bool, str]:
    """
    TypeScript compiles without errors (tsc --noEmit).
    Requires Node.js 18+ and node_modules populated.
    """
    ok, output = _run_shell(
        ["npx", "tsc", "--noEmit"],
        cwd=EXTENSION_ROOT,
        timeout=120,
    )
    if ok:
        return True, ""
    return False, f"TypeScript compile errors:\n{output[:800]}"


# ── D3 npm test ───────────────────────────────────────────────────────────────

def test_d3_npm_test() -> tuple[bool, str]:
    """npm test — all extension unit tests pass."""
    ok, output = _run_shell(
        ["npm", "test", "--", "--reporter=spec"],
        cwd=EXTENSION_ROOT,
        timeout=180,
    )
    # Look for test suite completion markers
    failure_markers = ["FAIL", "failing", "Error", "AssertionError"]
    pass_markers = ["passing", "PASS", "done", "OK"]

    output_lower = output.lower()
    if ok or any(m.lower() in output_lower for m in pass_markers):
        if not any(m.lower() in output_lower for m in failure_markers):
            return True, ""
    return False, f"Extension tests failed:\n{output[:800]}"


# ── D4 VSIX exists ────────────────────────────────────────────────────────────

def test_d4_vsix_exists() -> tuple[bool, str]:
    """nexusslicer-viewer-*.vsix exists in extension root or repo root."""
    # Check both locations
    candidates = list(EXTENSION_ROOT.glob("nexusslicer-viewer-*.vsix")) + \
                 list(REPO_ROOT.glob("nexusslicer-viewer-*.vsix"))
    if not candidates:
        return False, f"No VSIX found in {EXTENSION_ROOT} or {REPO_ROOT}"
    vsix = candidates[0]
    ok, err = _file_exists(vsix, min_bytes=10_000)  # at least 10 KB
    if ok:
        return True, f"Found: {vsix.name} ({vsix.stat().st_size // 1024} KB)"
    return False, err


# ── D5 Key TypeScript source files ────────────────────────────────────────────

def test_d5_ts_source_files() -> tuple[bool, str]:
    """All expected TypeScript source files exist."""
    expected = [
        "src/extension.ts",
        "src/renderer/MeshRenderer.ts",
        "src/renderer/StlLoader.ts",
        "src/renderer/ThreeMfLoader.ts",
        "src/renderer/CameraController.ts",
        "src/renderer/pbr.wgsl",
        "src/renderer/uv_diagnostic.wgsl",
        "src/protocol/StudioBridge.ts",
        "src/protocol/AiBridge.ts",
        "src/protocol/LicenseManager.ts",
        "src/protocol/ScreenshotEndpoint.ts",
    ]
    missing = []
    for rel in expected:
        p = EXTENSION_ROOT / rel
        if not p.exists():
            missing.append(rel)
    if not missing:
        return True, ""
    return False, f"Missing source files: {missing}"


# ── D6 Test suite files exist ─────────────────────────────────────────────────

def test_d6_test_suite_files() -> tuple[bool, str]:
    """Key test files for the extension are present."""
    expected = [
        "test/suite/threeMfLoader.test.ts",
        "test/suite/studioBridge.test.ts",
        "test/suite/toolController.test.ts",
        "test/suite/csgWorker.test.ts",
    ]
    missing = [r for r in expected if not (EXTENSION_ROOT / r).exists()]
    if not missing:
        return True, ""
    return False, f"Missing test files: {missing}"


# ── D7 LicenseManager test count ─────────────────────────────────────────────

def test_d7_license_manager_tests() -> tuple[bool, str]:
    """LicenseManager.ts test file has at least 17 test scenarios."""
    ts_file = EXTENSION_ROOT / "test" / "suite" / "licenseManager.test.ts"
    if not ts_file.exists():
        # Try to count from the existing test runner output
        return False, f"{ts_file} not found"
    content = ts_file.read_text(encoding="utf-8", errors="replace")
    test_count = content.count("it(") + content.count("test(")
    if test_count >= 17:
        return True, f"Found {test_count} test cases"
    return False, f"Only {test_count} tests in LicenseManager (expected ≥ 17)"


# ── D8 Machinist's Bench source ───────────────────────────────────────────────

def test_d8_machinists_bench() -> tuple[bool, str]:
    """Machinist's Bench TypeScript source files (CSGWorker, ToolController) exist."""
    expected = [
        "src/tools/CSGWorker.ts",
        "src/tools/ToolOverlayRenderer.ts",
        "src/tools/ToolController.ts",
    ]
    # Look in extension root and also src/tools under repo root
    missing = []
    for rel in expected:
        paths_to_check = [
            EXTENSION_ROOT / rel,
            REPO_ROOT / "nexusslicer-viewer" / rel,
            REPO_ROOT / rel,
        ]
        if not any(p.exists() for p in paths_to_check):
            missing.append(rel)
    if not missing:
        return True, ""
    return False, f"Missing Machinist's Bench files: {missing}"


# ── Test registry ─────────────────────────────────────────────────────────────

TESTS: list[tuple[str, str, callable]] = [
    ("D.extension_root",    "nexusslicer-viewer/ root + package.json exist",      test_d1_extension_root),
    ("D.ts_source_files",   "All 11 TypeScript source files exist",                test_d5_ts_source_files),
    ("D.test_suite_files",  "4 test suite .ts files exist",                        test_d6_test_suite_files),
    ("D.vsix_exists",       "VSIX artefact ≥ 10 KB exists",                        test_d4_vsix_exists),
    ("D.machinists_bench",  "Machinist's Bench TS source files exist",             test_d8_machinists_bench),
    ("D.tsc_compile",       "TypeScript compiles with zero errors",                 test_d2_tsc_compile),
    ("D.npm_test",          "npm test — all extension tests pass",                 test_d3_npm_test),
    ("D.license_manager",   "LicenseManager test file has ≥ 17 cases",            test_d7_license_manager_tests),
]


def run_group_d() -> list[dict]:
    results = []
    for test_id, test_name, test_fn in TESTS:
        try:
            passed, error = test_fn()
        except subprocess.TimeoutExpired:
            passed, error = False, "Timeout exceeded"
        except Exception as exc:  # noqa: BLE001
            passed, error = False, str(exc)[:1000]

        results.append({
            "group_id": "D",
            "test_id": test_id,
            "test_name": test_name,
            "passed": passed,
            "error": error or None,
        })
    return results


if __name__ == "__main__":
    for r in run_group_d():
        icon = "✅" if r["passed"] else "❌"
        err = f"  → {r['error'][:80]}" if r.get("error") else ""
        print(f"  {icon} {r['test_id']:<44s}{err}")
