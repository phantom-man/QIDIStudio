"""
Group E — C++ / CMake Build Gate Tests
========================================
Verifies the presence and correctness of C++ source files, headers, Slang
shaders, and CMake presets without performing a full compilation
(which requires SYCL / Vulkan SDKs not guaranteed in CI).

Tests that *are* safe to run without GPU hardware:
  E1  Key headers exist (QidiTheme, GLResource, StudioApiServer, etc.)
  E2  Key C++ source files exist
  E3  Slang shader files exist and contain expected function names
  E4  CMakePresets.json has ≥ 5 configurations
  E5  CMakeLists.txt is present and references SYCL / Vulkan targets
  E6  BVH and Slice kernel files exist with documented CPU fallback
  E7  pybind11 bridge source exists
  E8  #pragma once is present in all key headers
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
SRC = REPO_ROOT / "src"
SRC_GUI = SRC / "slic3r" / "GUI"
SRC_COMPUTE = SRC / "compute"
SHADERS = REPO_ROOT / "shaders"
NATIVE_VK = REPO_ROOT / "native" / "vulkan_renderer"


def _has_pragma_once(path: Path) -> bool:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        return "#pragma once" in content
    except Exception:
        return False


def _file_contains(path: Path, *patterns: str) -> tuple[bool, list[str]]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        missing = [p for p in patterns if p not in content]
        return len(missing) == 0, missing
    except Exception as exc:
        return False, [str(exc)]


def _paths_exist(*paths: Path) -> tuple[bool, list[str]]:
    missing = [str(p) for p in paths if not p.exists()]
    return len(missing) == 0, missing


# ── E1 Key headers ────────────────────────────────────────────────────────────

def test_e1_key_headers() -> tuple[bool, str]:
    """Critical header files introduced in QIDIStudio patchset exist."""
    headers = [
        SRC_GUI / "QidiTheme.hpp",
        SRC_GUI / "GLResource.hpp",
        SRC_GUI / "StudioApiServer.hpp",
    ]
    ok, missing = _paths_exist(*headers)
    if ok:
        return True, ""
    return False, f"Missing headers: {missing}"


# ── E2 Key C++ source files ───────────────────────────────────────────────────

def test_e2_key_sources() -> tuple[bool, str]:
    """Critical C++ source files introduced by the patchset exist."""
    sources = [
        SRC_GUI / "StudioApiServer.cpp",
        SRC_GUI / "AboutDialog.cpp",
        SRC_GUI / "OpenGLManager.cpp",
        SRC_GUI / "GUI_App.cpp",
        SRC_GUI / "StateColor.cpp",
        SRC_GUI / "GUI_Colors.cpp",
    ]
    ok, missing = _paths_exist(*sources)
    if ok:
        return True, ""
    return False, f"Missing sources: {missing}"


# ── E3 Slang shader files ─────────────────────────────────────────────────────

def test_e3_slang_shaders() -> tuple[bool, str]:
    """Slang shader files exist and contain expected entry-point names."""
    checks: list[tuple[Path, str]] = [
        (SHADERS / "pbr.slang",          "GGX"),
        (SHADERS / "ssao.slang",         "Hammersley"),
        (SHADERS / "ssao_blur.slang",    "bilateral"),
        (SHADERS / "shadow_cast.slang",  "shadow"),
        (SHADERS / "shadow_pcf.slang",   "SampleShadowPCF"),
        (SHADERS / "ibl.slang",          "SH9"),
    ]
    failures = []
    for path, keyword in checks:
        if not path.exists():
            failures.append(f"MISSING: {path.name}")
        elif keyword.lower() not in path.read_text(encoding="utf-8", errors="replace").lower():
            failures.append(f"KEYWORD '{keyword}' absent in {path.name}")
    if not failures:
        return True, ""
    return False, f"Shader issues: {failures}"


# ── E4 CMakePresets ───────────────────────────────────────────────────────────

def test_e4_cmake_presets() -> tuple[bool, str]:
    """CMakePresets.json has ≥ 5 configure presets and msvc-sycl is present."""
    presets_file = REPO_ROOT / "CMakePresets.json"
    if not presets_file.exists():
        return False, "CMakePresets.json not found"
    try:
        data = json.loads(presets_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"JSON parse error: {exc}"

    configure_presets = data.get("configurePresets", [])
    names = [p.get("name", "") for p in configure_presets]
    if len(names) < 5:
        return False, f"Only {len(names)} configure presets (expected ≥ 5): {names}"
    if not any("sycl" in n.lower() for n in names):
        return False, f"No msvc-sycl preset found. Presets: {names}"
    return True, f"{len(names)} configure presets, sycl preset present"


# ── E5 CMakeLists references ──────────────────────────────────────────────────

def test_e5_cmake_lists() -> tuple[bool, str]:
    """CMakeLists.txt exists and references StudioApiServer and BVHKernel."""
    cmake_file = REPO_ROOT / "CMakeLists.txt"
    if not cmake_file.exists():
        return False, "CMakeLists.txt not found"
    content = cmake_file.read_text(encoding="utf-8", errors="replace")
    required = ["StudioApiServer", "BVHKernel"]
    missing = [r for r in required if r not in content]
    if not missing:
        return True, ""
    return False, f"CMakeLists.txt missing references: {missing}"


# ── E6 Compute kernels (SYCL/CPU) ─────────────────────────────────────────────

def test_e6_compute_kernels() -> tuple[bool, str]:
    """BVHKernel and SliceKernel source files exist with CPU fallback."""
    files_and_keywords = [
        (SRC_COMPUTE / "BVHKernel.h",   "CPU"),
        (SRC_COMPUTE / "BVHKernel.cpp", "fallback"),
        (SRC_COMPUTE / "SliceKernel.h",   "CPU"),
        (SRC_COMPUTE / "SliceKernel.cpp", "fallback"),
    ]
    failures = []
    for path, keyword in files_and_keywords:
        if not path.exists():
            failures.append(f"MISSING: {path.name}")
        elif keyword.lower() not in path.read_text(encoding="utf-8", errors="replace").lower():
            failures.append(f"CPU fallback keyword '{keyword}' absent in {path.name}")
    if not failures:
        return True, ""
    return False, f"Kernel issues: {failures}"


# ── E7 pybind11 bridge ────────────────────────────────────────────────────────

def test_e7_pybind11_bridge() -> tuple[bool, str]:
    """python_bridge.cpp exists and exposes build_bvh / compute_slices."""
    bridge = SRC_COMPUTE / "python_bridge.cpp"
    if not bridge.exists():
        return False, f"python_bridge.cpp not found at {bridge}"
    content = bridge.read_text(encoding="utf-8", errors="replace")
    required = ["build_bvh", "compute_slices", "pybind11"]
    missing = [r for r in required if r not in content]
    if not missing:
        return True, ""
    return False, f"python_bridge.cpp missing: {missing}"


# ── E8 #pragma once in headers ────────────────────────────────────────────────

def test_e8_pragma_once() -> tuple[bool, str]:
    """All key headers include #pragma once."""
    headers = [
        SRC_GUI / "QidiTheme.hpp",
        SRC_GUI / "GLResource.hpp",
        SRC_GUI / "StudioApiServer.hpp",
    ]
    missing_pragma = [str(h.name) for h in headers if h.exists() and not _has_pragma_once(h)]
    if not missing_pragma:
        return True, ""
    return False, f"Missing #pragma once: {missing_pragma}"


# ── E9 Vulkan renderer scaffolding ────────────────────────────────────────────

def test_e9_vulkan_scaffold() -> tuple[bool, str]:
    """Vulkan renderer source files exist with VMA and vk-bootstrap references."""
    vk_cpp = NATIVE_VK / "vulkan_renderer.cpp"
    vk_hpp = NATIVE_VK / "vulkan_renderer.h"
    if not vk_cpp.exists() or not vk_hpp.exists():
        return False, f"Vulkan renderer files missing in {NATIVE_VK}"
    content = vk_cpp.read_text(encoding="utf-8", errors="replace")
    required = ["vma", "vk-bootstrap", "Hammersley"]
    # Case-insensitive search — vma is often uppercase
    content_lower = content.lower()
    missing = [r for r in required if r.lower() not in content_lower]
    if not missing:
        return True, ""
    return False, f"Vulkan renderer missing references: {missing}"


# ── Test registry ─────────────────────────────────────────────────────────────

TESTS: list[tuple[str, str, callable]] = [
    ("E.key_headers",       "Critical C++ headers exist",           test_e1_key_headers),
    ("E.key_sources",       "Critical C++ source files exist",      test_e2_key_sources),
    ("E.slang_shaders",     "6 Slang shaders with correct entries", test_e3_slang_shaders),
    ("E.cmake_presets",     "CMakePresets.json ≥ 5 presets + sycl", test_e4_cmake_presets),
    ("E.cmake_lists",       "CMakeLists.txt references new targets", test_e5_cmake_lists),
    ("E.compute_kernels",   "BVH + Slice kernels with CPU fallback", test_e6_compute_kernels),
    ("E.pybind_bridge",     "python_bridge.cpp with pybind11",       test_e7_pybind11_bridge),
    ("E.pragma_once",       "#pragma once in all key headers",       test_e8_pragma_once),
    ("E.vulkan_scaffold",   "Vulkan renderer files with VMA/vk-bootstrap", test_e9_vulkan_scaffold),
]


def run_group_e() -> list[dict]:
    results = []
    for test_id, test_name, test_fn in TESTS:
        try:
            passed, error = test_fn()
        except Exception as exc:  # noqa: BLE001
            passed, error = False, str(exc)[:1000]

        results.append({
            "group_id": "E",
            "test_id": test_id,
            "test_name": test_name,
            "passed": passed,
            "error": error or None,
        })
    return results


if __name__ == "__main__":
    for r in run_group_e():
        icon = "✅" if r["passed"] else "❌"
        err = f"  → {r['error'][:80]}" if r.get("error") else ""
        print(f"  {icon} {r['test_id']:<44s}{err}")
