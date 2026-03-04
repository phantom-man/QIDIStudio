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
    // ─── SYCL path: nd_range<2>(faceCount × layerCount) ──────────────────────
    //
    // Grid layout:
    //   Global:  faceCount × ceil(layerCount / 64) × 64
    //   Local:   1 × 64   (aligns with AMD wavefront; portable to NVIDIA/Intel)
    //
    // Each work-item (f, l) intersects one triangle against one Z-plane.
    // Intersecting segments are written into a flat output buffer using
    // a per-layer atomic counter.  After the kernel, we compact to SliceLayer.

    constexpr uint32_t WG_Y = 64;

    try {
        sycl::queue q{ sycl::default_selector_v };

        // Flatten vertex data into float4 (x,y,z,unused)
        std::vector<sycl::float4> verts(vertexCount);
        for (uint32_t v = 0; v < vertexCount; ++v) {
            verts[v] = sycl::float4(vertices[3 * v + 0],
                                    vertices[3 * v + 1],
                                    vertices[3 * v + 2],
                                    0.f);
        }

        const uint32_t maxPerLayer = faceCount; // upper bound on segments per layer

        sycl::buffer<sycl::float4> vertBuf(verts.data(),  sycl::range<1>(vertexCount));
        sycl::buffer<uint32_t>     idxBuf (indices,        sycl::range<1>(faceCount * 3));
        sycl::buffer<float>        zBuf   (zHeights,       sycl::range<1>(layerCount));
        sycl::buffer<sycl::float4> outBuf (sycl::range<1>(2 * layerCount * maxPerLayer));
        sycl::buffer<uint32_t>     cntBuf (sycl::range<1>(layerCount));
        {
            auto h = cntBuf.get_host_access(sycl::write_only);
            for (uint32_t i = 0; i < layerCount; ++i) h[i] = 0u;
        }

        const uint32_t globalY = ((layerCount + WG_Y - 1) / WG_Y) * WG_Y;

        q.submit([&](sycl::handler& h) {
            auto vA   = vertBuf.get_access<sycl::access::mode::read>(h);
            auto iA   = idxBuf .get_access<sycl::access::mode::read>(h);
            auto zA   = zBuf   .get_access<sycl::access::mode::read>(h);
            auto outA = outBuf .get_access<sycl::access::mode::discard_write>(h);
            auto cntA = cntBuf .get_access<sycl::access::mode::atomic>(h);

            h.parallel_for(
                sycl::nd_range<2>(sycl::range<2>(faceCount, globalY),
                                  sycl::range<2>(1, WG_Y)),
                [=](sycl::nd_item<2> item) {
                    uint32_t f = item.get_global_id(0);
                    uint32_t l = item.get_global_id(1);
                    if (l >= layerCount) return;

                    uint32_t i0 = iA[f * 3 + 0];
                    uint32_t i1 = iA[f * 3 + 1];
                    uint32_t i2 = iA[f * 3 + 2];
                    sycl::float4 p0 = vA[i0];
                    sycl::float4 p1 = vA[i1];
                    sycl::float4 p2 = vA[i2];
                    float z = zA[l];

                    float zLo = sycl::fmin(sycl::fmin(p0.z(), p1.z()), p2.z());
                    float zHi = sycl::fmax(sycl::fmax(p0.z(), p1.z()), p2.z());
                    if (z < zLo || z >= zHi) return;

                    sycl::float4 pts[2];
                    int cnt = 0;
                    auto edge = [&](sycl::float4 a, sycl::float4 b) {
                        if ((a.z() <= z && b.z() > z) || (b.z() <= z && a.z() > z)) {
                            float t = (z - a.z()) / (b.z() - a.z());
                            if (cnt < 2) {
                                pts[cnt++] = sycl::float4(
                                    sycl::fma(t, b.x() - a.x(), a.x()),
                                    sycl::fma(t, b.y() - a.y(), a.y()),
                                    z, 0.f);
                            }
                        }
                    };
                    edge(p0, p1);
                    edge(p1, p2);
                    edge(p2, p0);
                    if (cnt < 2) return;

                    sycl::atomic<uint32_t> counter(cntA[l]);
                    uint32_t slot = counter.fetch_add(1u);
                    if (slot >= maxPerLayer) return;

                    uint32_t base = 2 * (l * maxPerLayer + slot);
                    outA[base + 0] = pts[0];
                    outA[base + 1] = pts[1];
                });
        });
        q.wait();

        // Compact device output into SliceLayer host vectors
        std::vector<SliceLayer> layers(layerCount);
        auto hostCnt = cntBuf.get_host_access(sycl::read_only);
        auto hostOut = outBuf.get_host_access(sycl::read_only);
        for (uint32_t l = 0; l < layerCount; ++l) {
            uint32_t n = std::min(hostCnt[l], maxPerLayer);
            layers[l].z = zHeights[l];
            layers[l].edges.reserve(n * 4);
            for (uint32_t s = 0; s < n; ++s) {
                uint32_t base = 2 * (l * maxPerLayer + s);
                sycl::float4 a = hostOut[base + 0];
                sycl::float4 b = hostOut[base + 1];
                layers[l].edges.push_back(a.x());
                layers[l].edges.push_back(a.y());
                layers[l].edges.push_back(b.x());
                layers[l].edges.push_back(b.y());
            }
        }
        return layers;

    } catch (const sycl::exception& e) {
        (void)e; // SYCL device unavailable → fall through to CPU
    }
#endif

    return computeSlicesCPU(vertices, vertexCount, indices, faceCount, zHeights, layerCount);
}

} // namespace qidi_compute
