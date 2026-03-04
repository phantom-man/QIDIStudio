/**
 * SliceKernel.cpp — Phase 5 SYCL Slice Plane Intersection Kernel
 *
 * For each triangle in the mesh, test intersection against each Z layer.
 * Emits edge pairs for Marching Squares contour extraction.
 *
 * SYCL strategy (§5.2): work-group per triangle, each thread handles one Z layer.
 * Work-group size: 64 (portable across AMD wavefront=64, NVIDIA warp=32, Intel EU).
 *
 * CPU fallback: scalar loop over triangles × layers.
 *
 * Phase 5 completion criteria (§5.6):
 *   - Total slice time on Benchy: < 10s (from ~45s CPU baseline)
 *   - Graceful degradation when SYCL device unavailable
 */

#include "SliceKernel.h"

#include <algorithm>
#include <cstring>

#ifdef QIDI_ENABLE_SYCL
#include <sycl/sycl.hpp>
#endif

namespace qidi_compute {

// ─── Geometry helpers ──────────────────────────────────────────────────────────

/// Interpolate a point on edge (v0,v1) at z=zTarget.
/// Returns {x,y} or fills dst[0..1].
static void interpEdge(const float* v0, const float* v1, float zTarget,
                       float& outX, float& outY)
{
    float t = (zTarget - v0[2]) / (v1[2] - v0[2]);
    outX = v0[0] + t * (v1[0] - v0[0]);
    outY = v0[1] + t * (v1[1] - v0[1]);
}

/// Test one triangle against one Z plane.  Returns true + two intersection points if crossing.
static bool triangleSlice(
    const float* v0, const float* v1, const float* v2, float z,
    float& ax, float& ay, float& bx, float& by)
{
    const float* verts[3] = {v0, v1, v2};
    bool above[3] = { v0[2] >= z, v1[2] >= z, v2[2] >= z };
    int crossingEdges[2]; int nc = 0;
    for (int e = 0; e < 3 && nc < 2; ++e) {
        int next = (e + 1) % 3;
        if (above[e] != above[next]) crossingEdges[nc++] = e;
    }
    if (nc != 2) return false;
    int e0 = crossingEdges[0], e1 = crossingEdges[1];
    interpEdge(verts[e0], verts[(e0+1)%3], z, ax, ay);
    interpEdge(verts[e1], verts[(e1+1)%3], z, bx, by);
    return true;
}

// ─── CPU fallback ──────────────────────────────────────────────────────────────

static std::vector<SliceLayer> computeSlicesCPU(
    const float*    vertices,
    uint32_t        /*vertexCount*/,
    const uint32_t* indices,
    uint32_t        faceCount,
    const float*    zHeights,
    uint32_t        layerCount)
{
    std::vector<SliceLayer> result(layerCount);
    for (uint32_t l = 0; l < layerCount; ++l) result[l].z = zHeights[l];

    for (uint32_t f = 0; f < faceCount; ++f) {
        const float* v0 = vertices + indices[f*3+0] * 3;
        const float* v1 = vertices + indices[f*3+1] * 3;
        const float* v2 = vertices + indices[f*3+2] * 3;

        float zMin = std::min({v0[2], v1[2], v2[2]});
        float zMax = std::max({v0[2], v1[2], v2[2]});

        for (uint32_t l = 0; l < layerCount; ++l) {
            float z = zHeights[l];
            if (z < zMin || z > zMax) continue;
            float ax, ay, bx, by;
            if (triangleSlice(v0, v1, v2, z, ax, ay, bx, by)) {
                auto& layer = result[l];
                layer.edges.insert(layer.edges.end(), {ax, ay, bx, by});
                ++layer.edgeCount;
            }
        }
    }
    return result;
}

// ─── Public API ───────────────────────────────────────────────────────────────

std::vector<SliceLayer> computeSlices(
    const float*    vertices,
    uint32_t        vertexCount,
    const uint32_t* indices,
    uint32_t        faceCount,
    const float*    zHeights,
    uint32_t        layerCount)
{
#ifdef QIDI_ENABLE_SYCL
    // ─── SYCL path (Phase 5 full implementation) ────────────────────────────
    // TODO Phase 5 full impl strategy:
    //   1. Allocate sycl::buffer<float4> for edge output (faceCount * layerCount slots)
    //   2. Submit kernel: nd_range<2>(faceCount, layerCount), work-group size {1, 64}
    //      Each work-item: triangleSlice(v0,v1,v2, z) → atomic append to layer buffer
    //   3. Compact output (thrust::remove_if equivalent via SYCL std::copy_if)
    //   4. Copy back to host SliceLayer vector
    //
    // Prerequisite: find_package(IntelSYCL REQUIRED) in CMakeLists.txt
    //
    // Fall through to CPU until full SYCL impl
    (void)vertexCount;
#endif

    return computeSlicesCPU(vertices, vertexCount, indices, faceCount, zHeights, layerCount);
}

} // namespace qidi_compute
