/**
 * test_SliceKernel.cpp — Phase 5 Slice smoke test (CPU fallback path)
 *
 * Validates computeSlices on a minimal tetrahedron mesh.
 * No SYCL device required.
 */

#include "SliceKernel.h"

#include <cassert>
#include <cmath>
#include <cstdio>

int main()
{
    // Unit tetrahedron spanning Z=[0,1]
    // Vertices: apex at (0.5, 0.5, 1), base triangle at Z=0
    float vertices[] = {
        0.f,  0.f,  0.f,   // 0
        1.f,  0.f,  0.f,   // 1
        0.5f, 1.f,  0.f,   // 2
        0.5f, 0.5f, 1.f,   // 3 — apex
    };
    uint32_t indices[] = {
        0, 1, 2,   // base
        0, 1, 3,   // side
        1, 2, 3,   // side
        2, 0, 3,   // side
    };
    constexpr uint32_t faceCount = 4;

    // Slice at mid-height: expected cross-section at Z=0.5
    float zHeights[] = { 0.01f, 0.5f, 0.99f };
    constexpr uint32_t layerCount = 3;

    auto layers = qidi_compute::computeSlices(vertices, 4, indices, faceCount, zHeights, layerCount);

    assert(layers.size() == layerCount && "Must return one layer per Z height");

    // Z=0.01: base-adjacent slice — should have edges from the side faces
    // Z=0.5:  mid cross-section — should have edges
    // Z=0.99: near apex — should have edges

    for (uint32_t l = 0; l < layerCount; ++l) {
        // Z=0 and Z=1 exactly don't intersect (face lies in plane), but non-zero should
        bool expectEdges = (zHeights[l] > 0.0f && zHeights[l] < 1.0f);
        if (expectEdges) {
            assert(layers[l].edgeCount > 0 && "Non-degenerate slice must have edges");
        }
        assert(layers[l].edges.size() == layers[l].edgeCount * 4 &&
               "Each edge must contribute 4 floats (x0,y0,x1,y1)");
    }

    for (uint32_t l = 0; l < layerCount; ++l) {
        std::printf("[test_SliceKernel] layer %u  z=%.2f  edgeCount=%u\n",
                    l, static_cast<double>(layers[l].z), layers[l].edgeCount);
    }
    std::printf("[test_SliceKernel] PASS\n");
    return 0;
}
