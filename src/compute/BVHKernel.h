/**
 * BVHKernel.h — Phase 5 SYCL BVH public API
 */
#pragma once
#include <cstdint>
#include <memory>
#include <vector>

namespace qidi_compute {

/// Opaque result from buildBVH()
struct BVHResult {
    uint32_t              nodeCount  = 0;
    std::unique_ptr<uint8_t[]> nodes;         // flat BVHNode array (sizeof = nodeCount * sizeof(BVHNode))
    std::vector<int>      primIndices;         // reordered primitive indices
};

/**
 * Build a BVH over a triangle mesh.
 *
 * @param vertices    Interleaved float xyz per vertex
 * @param vertexCount Number of vertices
 * @param indices     Triangle indices, 3 per face
 * @param faceCount   Number of triangles
 * @return BVHResult  Flat node array + reordered prim indices
 *
 * Thread-safe: yes (no global state).
 * SYCL: enabled when compiled with -DQIDI_ENABLE_SYCL=ON.
 *       Falls back to CPU SAH-BVH otherwise.
 */
BVHResult buildBVH(
    const float*    vertices,
    uint32_t        vertexCount,
    const uint32_t* indices,
    uint32_t        faceCount);

} // namespace qidi_compute
