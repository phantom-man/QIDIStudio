## src/compute/CMakeLists.txt
## Phase 5: SYCL Compute Acceleration
##
## Dual-compiler build: MSVC for the main app, Intel DPC++ (icx -fsycl) for SYCL kernels.
## Builds one shared library: qidi_compute (C++17) + optional pybind11 module (qidi_compute_py).
##
## Usage:
##   cmake -DQIDI_ENABLE_SYCL=ON -DQIDI_ENABLE_PYTHON_BRIDGE=ON ...
##   cmake --preset msvc-sycl  (preset defined in CMakePresets.json)
##
## MASTER_PLAN §5.4 CMake Build Integration
## Speedup targets: BVH 8-20×, Slice 16-32×, UV Jacobian 50-100×

cmake_minimum_required(VERSION 3.21)

# ─── Sources ──────────────────────────────────────────────────────────────────

set(COMPUTE_SOURCES
    BVHKernel.cpp
    BVHKernel.h
    SliceKernel.cpp
    SliceKernel.h
)

# ─── Core qidi_compute library ────────────────────────────────────────────────

add_library(qidi_compute STATIC ${COMPUTE_SOURCES})
target_include_directories(qidi_compute PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(qidi_compute PUBLIC cxx_std_17)

if(MSVC)
    target_compile_options(qidi_compute PRIVATE /W4 /WX-)
else()
    target_compile_options(qidi_compute PRIVATE -Wall -Wextra)
endif()

# ─── SYCL path ────────────────────────────────────────────────────────────────

option(QIDI_ENABLE_SYCL "Enable Intel DPC++/SYCL GPU acceleration" OFF)

if(QIDI_ENABLE_SYCL)
    # Requires: Intel oneAPI toolkit installed; compiler set to icx
    # CMake invocation: -DCMAKE_CXX_COMPILER=icx -DQIDI_ENABLE_SYCL=ON
    find_package(IntelSYCL REQUIRED)

    target_compile_definitions(qidi_compute PUBLIC QIDI_ENABLE_SYCL)
    target_link_libraries(qidi_compute PUBLIC IntelSYCL::SYCL_CXX)

    # add_sycl_to_target marks .cpp files for -fsycl compilation
    add_sycl_to_target(
        TARGET  qidi_compute
        SOURCES BVHKernel.cpp SliceKernel.cpp)

    # Work-group portability note (§5.3): always use multiples of 64
    target_compile_options(qidi_compute PRIVATE
        $<$<CXX_COMPILER_ID:IntelLLVM>:-fsycl -fsycl-targets=spir64>)

    message(STATUS "[qidi_compute] SYCL enabled — using Intel DPC++ (icx)")
else()
    message(STATUS "[qidi_compute] SYCL disabled — CPU-only scalar fallback")
endif()

# ─── pybind11 Python bridge ───────────────────────────────────────────────────

option(QIDI_ENABLE_PYTHON_BRIDGE "Build the pybind11 Python bridge" OFF)

if(QIDI_ENABLE_PYTHON_BRIDGE)
    find_package(pybind11 REQUIRED)

    pybind11_add_module(qidi_compute_py
        python_bridge.cpp)

    target_compile_definitions(qidi_compute_py PRIVATE QIDI_ENABLE_PYTHON_BRIDGE)
    target_link_libraries(qidi_compute_py PRIVATE qidi_compute)

    install(TARGETS qidi_compute_py
        DESTINATION ${CMAKE_INSTALL_LIBDIR}/python)

    message(STATUS "[qidi_compute] Python bridge enabled")
endif()

# ─── Tests  ────────────────────────────────────────────────────────────────────
# Lightweight CTest smoke tests — no SYCL device required (CPU fallback)

option(QIDI_BUILD_COMPUTE_TESTS "Build compute unit tests" OFF)

if(QIDI_BUILD_COMPUTE_TESTS)
    enable_testing()

    add_executable(test_bvh tests/test_BVHKernel.cpp)
    target_link_libraries(test_bvh PRIVATE qidi_compute)
    add_test(NAME BVH_smoke COMMAND test_bvh)

    add_executable(test_slice tests/test_SliceKernel.cpp)
    target_link_libraries(test_slice PRIVATE qidi_compute)
    add_test(NAME Slice_smoke COMMAND test_slice)

    message(STATUS "[qidi_compute] Tests enabled")
endif()
