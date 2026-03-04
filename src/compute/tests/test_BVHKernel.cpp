/**
 * test_BVHKernel.cpp — Phase 5 BVH smoke test (CPU fallback path)
 *
 * Validates buildBVH on a minimal 2-triangle mesh.
 * No SYCL device required — runs against the CPU scalar fallback.
 */

#include "BVHKernel.h"

#include <cassert>
#include <cstdio>
#include <cmath>

int main()
{
    // Two triangles forming an XY square at Z=0
    // Vertices:  0=(0,0,0), 1=(1,0,0), 2=(1,1,0), 3=(0,1,0)
    float vertices[] = {
        0.f, 0.f, 0.f,
        1.f, 0.f, 0.f,
        1.f, 1.f, 0.f,
        0.f, 1.f, 0.f,
    };
    uint32_t indices[] = { 0, 1, 2,   0, 2, 3 };
    constexpr uint32_t faceCount = 2;

    auto result = qidi_compute::buildBVH(vertices, 4, indices, faceCount);

    // A 2-triangle BVH must have ≥1 node
    assert(result.nodeCount >= 1 && "BVH must produce at least 1 node");
    assert(result.nodes    != nullptr && "Node array must not be null");
    assert(result.primIndices.size() == faceCount && "primIndices must cover all faces");

    // Validate all prim indices are in range [0, faceCount)
    for (uint32_t i = 0; i < faceCount; ++i) {
        int pid = result.primIndices[i];
        assert(pid >= 0 && static_cast<uint32_t>(pid) < faceCount && "prim index out of range");
    }

    std::printf("[test_BVHKernel] PASS — nodeCount=%u, primIndices=%zu\n",
                result.nodeCount, result.primIndices.size());
    return 0;
}
