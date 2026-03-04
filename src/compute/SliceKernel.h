/**
 * SliceKernel.h — Phase 5 SYCL Slice Plane Intersection API
 */
#pragma once
#include <cstdint>
#include <vector>

namespace qidi_compute {

/// One slice layer: set of 2D contour edges (pairs of XY floats)
struct SliceLayer {
    float          z;             // slice height
    std::vector<float> edges;     // interleaved x0,y0,x1,y1 per edge
    uint32_t       edgeCount = 0;
};

/**
 * Compute slice plane intersections for an array of Z heights.
 *
 * @param vertices    Interleaved float xyz per vertex
 * @param vertexCount Number of vertices
 * @param indices     Triangle indices, 3 per face
 * @param faceCount   Number of triangles
 * @param zHeights    Array of Z slice positions
 * @param layerCount  Number of Z slices
 * @return per-layer edge lists
 *
 * SYCL: work-group-per-triangle strategy (work-group size 64).
 *        Falls back to CPU scalar when -DQIDI_ENABLE_SYCL=OFF.
 * Speedup: 16–32× on RTX 3060 vs CPU scalar (per MASTER_PLAN §5.2).
 */
std::vector<SliceLayer> computeSlices(
    const float*    vertices,
    uint32_t        vertexCount,
    const uint32_t* indices,
    uint32_t        faceCount,
    const float*    zHeights,
    uint32_t        layerCount);

} // namespace qidi_compute
