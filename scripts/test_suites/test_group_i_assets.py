"""
Group I — File / Asset Existence Tests
========================================
Verifies that every committed artefact required by the master plan
is present on disk at the expected path.

These tests are purely file-system checks — zero network calls, zero
subprocess invocations, zero external dependencies.
They run in < 1 second total and are the first line of defence
against accidental deletions or mis-named files.

Categories:
  I1  C++ GUI headers and sources
  I2  Shaders (WGSL + Slang)
  I3  VS Code extension TypeScript sources
  I4  Test suite files (TS)
  I5  Build artefacts (VSIX, icons, SVG assets)
  I6  Python scripts (AI features)
  I7  Agent modules
  I8  GCodeRefiner
  I9  Documentation (PhD docs sample)
  I10 Configuration files
  I11 Memory / hooks
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).parents[2]
EXT = REPO_ROOT / "nexusslicer-viewer"
AGENTS = REPO_ROOT / "agents"
SCRIPTS = REPO_ROOT / "scripts"
SRC_GUI = REPO_ROOT / "src" / "slic3r" / "GUI"
SRC_COMPUTE = REPO_ROOT / "src" / "compute"
SHADERS = REPO_ROOT / "shaders"
NATIVE_VK = REPO_ROOT / "native" / "vulkan_renderer"
MEDIA = REPO_ROOT / "media"
RESOURCES = REPO_ROOT / "resources"
DOCS = REPO_ROOT / "docs"
DOCS_PRIVATE = DOCS / "private"
HOOKS = REPO_ROOT / ".vscode" / "hooks"
MEMORY = REPO_ROOT / "memory"
GCODE_REFINER = REPO_ROOT / "GCodeRefiner"
CLOUD_API = REPO_ROOT / "cloud_api"


class FileCheck(NamedTuple):
    path: Path
    min_bytes: int = 1
    description: str = ""


# ── I1  C++ GUI ────────────────────────────────────────────────────────────────
I1_CPP_GUI: list[FileCheck] = [
    FileCheck(SRC_GUI / "QidiTheme.hpp",        200,  "Brand theme header"),
    FileCheck(SRC_GUI / "GLResource.hpp",        200,  "RAII GL resource header"),
    FileCheck(SRC_GUI / "StudioApiServer.hpp",   200,  "HTTP bridge header"),
    FileCheck(SRC_GUI / "StudioApiServer.cpp",   500,  "HTTP bridge impl"),
    FileCheck(SRC_GUI / "AboutDialog.cpp",       200,  "About dialog patched"),
    FileCheck(SRC_GUI / "OpenGLManager.cpp",     200,  "OpenGL manager patched"),
    FileCheck(SRC_GUI / "GUI_App.cpp",           200,  "GUI app patched"),
    FileCheck(SRC_GUI / "StateColor.cpp",        200,  "State color patched"),
    FileCheck(SRC_GUI / "GUI_Colors.cpp",        200,  "GUI colors patched"),
]

# ── I2  Shaders ────────────────────────────────────────────────────────────────
I2_SHADERS: list[FileCheck] = [
    FileCheck(SHADERS / "pbr.slang",             500,  "PBR Slang shader"),
    FileCheck(SHADERS / "ssao.slang",            400,  "SSAO Slang shader"),
    FileCheck(SHADERS / "ssao_blur.slang",       300,  "SSAO bilateral blur"),
    FileCheck(SHADERS / "shadow_cast.slang",     300,  "Shadow cast shader"),
    FileCheck(SHADERS / "shadow_pcf.slang",      300,  "PCF shadow filter"),
    FileCheck(SHADERS / "ibl.slang",             400,  "SH9 IBL shader"),
    FileCheck(EXT / "src" / "renderer" / "pbr.wgsl",             300,  "WebGPU PBR WGSL"),
    FileCheck(EXT / "src" / "renderer" / "uv_diagnostic.wgsl",   300,  "UV diagnostic WGSL"),
]

# ── I3  TS extension sources ───────────────────────────────────────────────────
I3_TS_SOURCES: list[FileCheck] = [
    FileCheck(EXT / "src" / "extension.ts",                     1000, "Extension entry point"),
    FileCheck(EXT / "src" / "renderer" / "MeshRenderer.ts",     1000, "WebGPU mesh renderer"),
    FileCheck(EXT / "src" / "renderer" / "StlLoader.ts",         500, "STL loader"),
    FileCheck(EXT / "src" / "renderer" / "ThreeMfLoader.ts",     500, "3MF loader"),
    FileCheck(EXT / "src" / "renderer" / "CameraController.ts",  500, "Camera controller"),
    FileCheck(EXT / "src" / "protocol" / "StudioBridge.ts",      500, "Studio bridge client"),
    FileCheck(EXT / "src" / "protocol" / "AiBridge.ts",          500, "AI bridge (11 commands)"),
    FileCheck(EXT / "src" / "protocol" / "LicenseManager.ts",    500, "License manager (HMAC)"),
    FileCheck(EXT / "src" / "protocol" / "ScreenshotEndpoint.ts",300, "Screenshot HTTP endpoint"),
    FileCheck(EXT / "package.json",                              200, "Extension package.json"),
]

# ── I4  TS test suite ──────────────────────────────────────────────────────────
I4_TS_TESTS: list[FileCheck] = [
    FileCheck(EXT / "test" / "suite" / "threeMfLoader.test.ts",  1000, "3MF loader tests (11)"),
    FileCheck(EXT / "test" / "suite" / "studioBridge.test.ts",    800, "StudioBridge tests (10)"),
    FileCheck(EXT / "test" / "suite" / "toolController.test.ts",  800, "ToolController tests"),
    FileCheck(EXT / "test" / "suite" / "csgWorker.test.ts",       600, "CSGWorker tests"),
]

# ── I5  Build artefacts / assets ──────────────────────────────────────────────
_vsix_candidates = list(REPO_ROOT.glob("nexusslicer-viewer-*.vsix")) + \
                   list(EXT.glob("nexusslicer-viewer-*.vsix"))

I5_ASSETS: list[FileCheck] = [
    FileCheck(RESOURCES / "splash_logo.svg",   500,  "Splash logo SVG"),
    FileCheck(REPO_ROOT / "README.md",        1000,  "README.md (NexusSlicer branding)"),
]
if _vsix_candidates:
    I5_ASSETS.append(FileCheck(_vsix_candidates[0], 10_000, "VSIX extension package"))

# ── I6  Python scripts (AI features) ──────────────────────────────────────────
I6_SCRIPTS: list[FileCheck] = [
    FileCheck(SCRIPTS / "nl_slicer.py",               2000, "NL slicer (Phase 6.1)"),
    FileCheck(SCRIPTS / "support_advisor.py",         1000, "Support advisor (6.5)"),
    FileCheck(SCRIPTS / "text_to_texture.py",         1000, "Text-to-texture (6.4)"),
    FileCheck(SCRIPTS / "ai_beauty_scorer.py",         800, "Beauty scorer"),
    FileCheck(SCRIPTS / "pipeline_tools.py",          1000, "Pipeline tools (7 tools)"),
    FileCheck(SCRIPTS / "autonomous_pipeline.py",     1500, "Autonomous pipeline"),
    FileCheck(SCRIPTS / "visualizer_computer.py",     1000, "Visualizer computer"),
    FileCheck(SCRIPTS / "ai_bridge_server.py",        1500, "AI bridge server (port 17234)"),
    FileCheck(SCRIPTS / "knowledge_validator.py",     3000, "Knowledge validator"),
    FileCheck(SCRIPTS / "startup_check.py",           2000, "Startup health check"),
]

# ── I7  Agents ────────────────────────────────────────────────────────────────
I7_AGENTS: list[FileCheck] = [
    FileCheck(AGENTS / "agents.py",             2000, "Agent factory"),
    FileCheck(AGENTS / "tools.py",              3000, "Agent tools (write_file, read_image)"),
    FileCheck(AGENTS / "orchestrator.py",       1500, "Fleet orchestrator"),
    FileCheck(AGENTS / "dev_fleet.py",          5000, "Dev fleet (coder/tester, 747 lines)"),
    FileCheck(AGENTS / "run_store.py",          1000, "Run store (Postgres)"),
    FileCheck(AGENTS / "torch_tools.py",        2000, "Torch tools (GNN/LSTM/MLP)"),
    FileCheck(AGENTS / "manufacturing_graph.py",1500, "Manufacturing LangGraph"),
    FileCheck(AGENTS / "hardware_feedback.py",  1000, "RLHF hardware feedback"),
    FileCheck(AGENTS / "prompts" / "coder.md",   400, "Coder agent prompt"),
    FileCheck(AGENTS / "prompts" / "tester.md",  400, "Tester agent prompt"),
]

# ── I8  GCodeRefiner ──────────────────────────────────────────────────────────
I8_GCODE: list[FileCheck] = [
    FileCheck(GCODE_REFINER / "refiner.py",      4000, "GCode refiner (493 lines)"),
    FileCheck(GCODE_REFINER / "llm_optimizer.py",1500, "GCode LLM optimizer"),
]

# ── I9  Key documentation ─────────────────────────────────────────────────────
I9_DOCS: list[FileCheck] = [
    FileCheck(DOCS / "KNOWN_PIPELINES.md",       2000, "Known pipelines catalog"),
    FileCheck(DOCS / "QIDISTUDIO_KNOWLEDGE.md",  1000, "Knowledge manifest"),
    FileCheck(DOCS / "Agent_Almanac.md",        10000, "Agent Almanac (1135 lines)"),
    FileCheck(DOCS_PRIVATE / "MASTER_PLAN.md",  10000, "Master plan"),
    FileCheck(DOCS_PRIVATE / "NEXUSMILL_SPEC.md",3000, "NexusMill spec"),
    FileCheck(DOCS_PRIVATE / "NEXUSGAUGE_SPEC.md",3000,"NexusGauge spec"),
]

# ── I10 Configuration files ───────────────────────────────────────────────────
I10_CONFIG: list[FileCheck] = [
    FileCheck(REPO_ROOT / "CMakeLists.txt",     5000, "Root CMakeLists.txt"),
    FileCheck(REPO_ROOT / "CMakePresets.json",  1000, "CMake presets"),
    FileCheck(REPO_ROOT / ".env",               100,  ".env (API keys present)"),
]

# ── I11 Memory / hooks ────────────────────────────────────────────────────────
I11_MEMORY: list[FileCheck] = [
    FileCheck(MEMORY / "inject.py",             1000, "Memory inject (LanceDB query)"),
    FileCheck(MEMORY / "extract.py",            1000, "Memory extract (LanceDB write)"),
    FileCheck(MEMORY / "prompt_store.py",       1000, "Prompt/response store"),
]

# ── I12 Compute kernels ───────────────────────────────────────────────────────
I12_COMPUTE: list[FileCheck] = [
    FileCheck(SRC_COMPUTE / "BVHKernel.h",     1000, "BVH kernel header (SYCL)"),
    FileCheck(SRC_COMPUTE / "BVHKernel.cpp",   2000, "BVH kernel impl"),
    FileCheck(SRC_COMPUTE / "SliceKernel.h",    800, "Slice kernel header"),
    FileCheck(SRC_COMPUTE / "SliceKernel.cpp", 1500, "Slice kernel impl"),
    FileCheck(SRC_COMPUTE / "python_bridge.cpp",500, "pybind11 bridge"),
]

# ── I13 Cloud API ─────────────────────────────────────────────────────────────
I13_CLOUD: list[FileCheck] = [
    FileCheck(CLOUD_API / "app.py",             1000, "Cloud API FastAPI scaffold"),
]

# ── Combine all groups ────────────────────────────────────────────────────────
ALL_CHECKS: dict[str, list[FileCheck]] = {
    "I1_cpp_gui":       I1_CPP_GUI,
    "I2_shaders":       I2_SHADERS,
    "I3_ts_sources":    I3_TS_SOURCES,
    "I4_ts_tests":      I4_TS_TESTS,
    "I5_assets":        I5_ASSETS,
    "I6_scripts":       I6_SCRIPTS,
    "I7_agents":        I7_AGENTS,
    "I8_gcode":         I8_GCODE,
    "I9_docs":          I9_DOCS,
    "I10_config":       I10_CONFIG,
    "I11_memory":       I11_MEMORY,
    "I12_compute":      I12_COMPUTE,
    "I13_cloud":        I13_CLOUD,
}


def _check_file(fc: FileCheck) -> tuple[bool, str]:
    if not fc.path.exists():
        return False, f"MISSING: {fc.path.relative_to(REPO_ROOT)}"
    size = fc.path.stat().st_size
    if size < fc.min_bytes:
        return False, f"TOO_SMALL ({size}B < {fc.min_bytes}B): {fc.path.relative_to(REPO_ROOT)}"
    return True, ""


def run_group_i() -> list[dict]:
    results = []
    for category, checks in ALL_CHECKS.items():
        all_ok = True
        errors: list[str] = []
        for fc in checks:
            ok, err = _check_file(fc)
            if not ok:
                all_ok = False
                errors.append(err)

        # One result per category (summary)
        results.append({
            "group_id": "I",
            "test_id": f"I.{category}",
            "test_name": f"File existence: {category.replace('_', ' ')}",
            "passed": all_ok,
            "error": "; ".join(errors) if errors else None,
        })

        # Also emit per-file failures for granularity
        if not all_ok:
            for fc in checks:
                ok, err = _check_file(fc)
                if not ok:
                    results.append({
                        "group_id": "I",
                        "test_id": f"I.file.{fc.path.stem}",
                        "test_name": f"File: {fc.path.relative_to(REPO_ROOT)}",
                        "passed": False,
                        "error": err,
                    })

    return results


if __name__ == "__main__":
    for r in run_group_i():
        icon = "✅" if r["passed"] else "❌"
        err = f"  → {r['error'][:80]}" if r.get("error") else ""
        print(f"  {icon} {r['test_id']:<44s}{err}")
