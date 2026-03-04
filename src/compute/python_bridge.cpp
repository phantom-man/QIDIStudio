/**
 * python_bridge.cpp — Phase 5 pybind11 bridge for qidi_compute SYCL kernels
 *
 * Exposes BVHKernel and SliceKernel to the Python texture/slicing pipeline
 * without copying data (numpy buffer protocol ↔ SYCL USM pointers).
 *
 * Build:
 *   find_package(pybind11 REQUIRED)
 *   pybind11_add_module(qidi_compute_py python_bridge.cpp)
 *   target_link_libraries(qidi_compute_py PRIVATE qidi_compute)
 *
 * Usage (Python):
 *   import qidi_compute_py as qc
 *   # BVH
 *   result = qc.build_bvh(vertices_np, indices_np)   # returns dict
 *   # Slice
 *   layers  = qc.compute_slices(vertices_np, indices_np, z_array_np)
 *
 * MASTER_PLAN §5.5 pybind11 bridge — UV Jacobian and BVH exposed to Python pipeline.
 */

#include "BVHKernel.h"
#include "SliceKernel.h"

#include <stdexcept>
#include <string>

#ifdef QIDI_ENABLE_PYTHON_BRIDGE
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

// ─── BVH bridge ───────────────────────────────────────────────────────────────

static py::dict py_build_bvh(py::array_t<float>    vertices_in,
                              py::array_t<uint32_t> indices_in)
{
    auto vbuf = vertices_in.request();
    auto ibuf = indices_in.request();

    if (vbuf.ndim != 1 && vbuf.ndim != 2)
        throw std::invalid_argument("vertices must be 1-D or 2-D float array");
    if (ibuf.ndim != 1 && ibuf.ndim != 2)
        throw std::invalid_argument("indices must be 1-D or 2-D uint32 array");

    const auto* vptr = static_cast<const float*>(vbuf.ptr);
    const auto* iptr = static_cast<const uint32_t*>(ibuf.ptr);

    uint32_t vertexCount = static_cast<uint32_t>(vbuf.size / 3);
    uint32_t faceCount   = static_cast<uint32_t>(ibuf.size / 3);

    auto result = qidi_compute::buildBVH(vptr, vertexCount, iptr, faceCount);

    py::dict d;
    d["node_count"]   = result.nodeCount;
    d["prim_indices"] = py::array_t<int>(
        { static_cast<py::ssize_t>(result.primIndices.size()) },
        result.primIndices.data());
    return d;
}

// ─── Slice bridge ─────────────────────────────────────────────────────────────

static py::list py_compute_slices(py::array_t<float>    vertices_in,
                                   py::array_t<uint32_t> indices_in,
                                   py::array_t<float>    z_heights_in)
{
    auto vbuf = vertices_in.request();
    auto ibuf = indices_in.request();
    auto zbuf = z_heights_in.request();

    const auto* vptr = static_cast<const float*>(vbuf.ptr);
    const auto* iptr = static_cast<const uint32_t*>(ibuf.ptr);
    const auto* zptr = static_cast<const float*>(zbuf.ptr);

    uint32_t vertexCount = static_cast<uint32_t>(vbuf.size / 3);
    uint32_t faceCount   = static_cast<uint32_t>(ibuf.size / 3);
    uint32_t layerCount  = static_cast<uint32_t>(zbuf.size);

    auto layers = qidi_compute::computeSlices(vptr, vertexCount, iptr, faceCount, zptr, layerCount);

    py::list result;
    for (auto& layer : layers) {
        py::dict d;
        d["z"]          = layer.z;
        d["edge_count"] = layer.edgeCount;
        d["edges"]      = py::array_t<float>(
            { static_cast<py::ssize_t>(layer.edges.size()) },
            layer.edges.data());
        result.append(d);
    }
    return result;
}

// ─── Module ───────────────────────────────────────────────────────────────────

PYBIND11_MODULE(qidi_compute_py, m)
{
    m.doc() = "qidi_compute — SYCL-accelerated BVH and slice kernels (Phase 5)";

    m.def("build_bvh",
        &py_build_bvh,
        py::arg("vertices"),
        py::arg("indices"),
        R"doc(
Build a BVH over a triangle mesh.

Args:
    vertices (np.ndarray float32): interleaved x,y,z per vertex, shape (N*3,) or (N,3)
    indices  (np.ndarray uint32):  triangle indices, shape (F*3,) or (F,3)

Returns:
    dict with keys:
        node_count   (int)
        prim_indices (np.ndarray int32)
        )doc");

    m.def("compute_slices",
        &py_compute_slices,
        py::arg("vertices"),
        py::arg("indices"),
        py::arg("z_heights"),
        R"doc(
Compute slice plane intersections.

Args:
    vertices  (np.ndarray float32): interleaved x,y,z per vertex
    indices   (np.ndarray uint32):  triangle indices, 3 per face
    z_heights (np.ndarray float32): Z positions of each slice plane

Returns:
    list of dicts, one per layer:
        z          (float)
        edge_count (int)
        edges      (np.ndarray float32) — interleaved x0,y0,x1,y1 per edge
        )doc");
}

#endif // QIDI_ENABLE_PYTHON_BRIDGE
