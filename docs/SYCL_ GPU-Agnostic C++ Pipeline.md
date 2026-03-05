# SYCL 2020: GPU-Agnostic C++ Compute Pipeline

SYCL 2020 is a royalty-free, open-standard C++17 abstraction layer for heterogeneous computing — enabling the same kernel source to compile to PTX (NVIDIA), GCN (AMD), or SPIR-V (Intel) without code forking.

---

## I. Architecture

```
┌──────────────────────────────────────────────┐
│                SYCL Application               │
│     sycl::queue  |  sycl::buffer  |  USM      │
├──────────────────────────────────────────────┤
│          SYCL Runtime (libsycl)               │
├───────────┬──────────────┬───────────────────┤
│  Level Zero│  ROCm Backend│  CUDA Backend     │
│  (Intel)   │  (AMD)       │  (hipSYCL/AdaptCpp)│
├───────────┴──────────────┴───────────────────┤
│   GPU ISA: SPIR-V | GCN HSAIL | PTX           │
└──────────────────────────────────────────────┘
```

SYCL implementations:
- **DPC++ / Intel oneAPI** — reference implementation; best for Intel GPUs
- **AdaptiveCpp (hipSYCL)** — NVIDIA + AMD via HIP/CUDA backends
- **ComputeCpp** — legacy commercial (deprecated 2023)

---

## II. Core Programming Model

### 2.1 Queue and Device Setup

```cpp
#include <sycl/sycl.hpp>
#include <iostream>

sycl::device select_device(const std::string& vendor_hint = "") {
    for (const auto& dev : sycl::device::get_devices(sycl::info::device_type::gpu)) {
        auto name = dev.get_info<sycl::info::device::name>();
        if (vendor_hint.empty() ||
            name.find(vendor_hint) != std::string::npos) {
            std::cout << "[SYCL] Selected: " << name << "\n";
            return dev;
        }
    }
    return sycl::device{sycl::default_selector_v};
}

int main() {
    sycl::queue q{select_device()};
    std::cout << "Max work group: "
              << q.get_device().get_info<sycl::info::device::max_work_group_size>()
              << "\n";
}
```

### 2.2 Buffer-Accessor Model

```cpp
void matrix_add_sycl(
    sycl::queue& q,
    const std::vector<float>& a,
    const std::vector<float>& b,
    std::vector<float>& c,
    int N
) {
    sycl::buffer<float, 1> ba(a.data(), N);
    sycl::buffer<float, 1> bb(b.data(), N);
    sycl::buffer<float, 1> bc(c.data(), N);

    q.submit([&](sycl::handler& h) {
        auto ra = ba.get_access<sycl::access::mode::read>(h);
        auto rb = bb.get_access<sycl::access::mode::read>(h);
        auto rc = bc.get_access<sycl::access::mode::write>(h);

        h.parallel_for(sycl::range<1>(N), [=](sycl::id<1> i) {
            rc[i] = ra[i] + rb[i];
        });
    });
    q.wait();
}
```

### 2.3 Unified Shared Memory (USM) — Zero-Copy

USM eliminates explicit buffer copies:

```cpp
float* usm_malloc_shared(sycl::queue& q, int n) {
    return sycl::malloc_shared<float>(n, q);
}

void vector_scale_usm(sycl::queue& q, float* data, float alpha, int n) {
    q.parallel_for(sycl::range<1>(n), [=](sycl::id<1> i) {
        data[i] *= alpha;
    }).wait();
}

// Usage:
// float* v = usm_malloc_shared(q, 1024);
// [fill v from CPU]
// vector_scale_usm(q, v, 2.5f, 1024);
// [read v from CPU]
// sycl::free(v, q);
```

---

## III. 2D Convolution Kernel

```cpp
void conv2d_sycl(
    sycl::queue& q,
    const float* input,    // USM pointer (H x W)
    const float* kernel,   // (K x K)
    float* output,         // (H x W)
    int H, int W, int K
) {
    int pad = K / 2;
    q.parallel_for(sycl::range<2>(H, W), [=](sycl::id<2> idx) {
        int row = idx[0], col = idx[1];
        float acc = 0.0f;
        for (int ky = 0; ky < K; ++ky)
            for (int kx = 0; kx < K; ++kx) {
                int r = row + ky - pad;
                int c = col + kx - pad;
                if (r >= 0 && r < H && c >= 0 && c < W)
                    acc += input[r * W + c] * kernel[ky * K + kx];
            }
        output[row * W + col] = acc;
    }).wait();
}
```

---

## IV. Performance Notes

| Feature | SYCL 2020 | CUDA | Overhead |
|---------|----------|------|---------|
| Kernel launch latency | ~5–20 µs | ~2 µs | 3–10x higher |
| Memory bandwidth utilization | 85–95% of peak | 90–98% | Minor |
| FP32 GEMM efficiency | 80–90% | 90–95% | ~10% |
| Portability | All GPUs | NVIDIA only | — |

---

## References

- Khronos Group (2023). SYCL 2020 Specification rev 8. khronos.org/sycl.
- Intel (2023). Intel oneAPI DPC++/C++ Compiler Developer Guide.
- Deakin, T. et al. (2020). Performance portability of SYCL benchmarks. *IEEE P3HPC*.
- Alpay, A. & Heeg, V. (2022). AdaptiveCpp: A Production SYCL for Any GPU. *Euro-Par 2022*.
