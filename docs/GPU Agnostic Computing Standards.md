# GPU-Agnostic Computing: Standards, Abstractions, and Portability

A technical reference for writing compute shaders and GPU kernels that execute correctly across NVIDIA (CUDA/PTX), AMD (ROCm/GCN), and Intel (oneAPI/SPIRV) architectures — using hardware-abstraction layers and standards-based programming models.

---

## I. GPU Compute Standards Landscape

### 1.1 Portability Hierarchy

```
┌───────────────────────────────────────────────────────────────┐
│                    Application Layer                          │
├──────────────────┬────────────────────┬──────────────────────┤
│   PyTorch / JAX  │    OpenCL / SYCL   │   Vulkan Compute     │
├──────────────────┴────────────────────┴──────────────────────┤
│                 Hardware Abstraction Layer (HAL)              │
│         HIP  |  CUDA  |  Metal  |  Level Zero (Intel)        │
├──────────────┬────────────────┬──────────────────────────────┤
│  NVIDIA PTX  │   AMD GCN ISA  │  Intel SPIRV / Xe ISA        │
└──────────────┴────────────────┴──────────────────────────────┘
```

### 1.2 API Comparison

| Feature | CUDA | HIP (ROCm) | SYCL | OpenCL |
|---------|------|-----------|------|--------|
| Language | C++ | C++ | C++17 | C99/C++ |
| Vendor | NVIDIA | AMD | Khronos | Khronos |
| Compile | nvcc | hipcc | icpx/dpcpp | clBuildProgram |
| Portability | NVIDIA only | NVIDIA+AMD | All | All |
| Performance ceiling | Highest | ~95% | ~85% | ~80% |

---

## II. HIP: CUDA-Compatible Portability Layer

### 2.1 HIP Kernel Translation

HIP uses identical syntax to CUDA — `hipify-perl` auto-translates CUDA source:

```bash
hipify-perl kernel.cu > kernel.hip.cpp
```

Manual HIP kernel (mathematically identical to CUDA):

```cpp
#include <hip/hip_runtime.h>

__global__ void saxpy(
    int n, float alpha,
    const float* __restrict__ x,
    float* __restrict__ y
) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) y[i] = alpha * x[i] + y[i];
}

void run_saxpy(int n, float alpha, float* d_x, float* d_y) {
    const int block = 256;
    const int grid = (n + block - 1) / block;
    hipLaunchKernelGGL(saxpy, dim3(grid), dim3(block), 0, 0,
                       n, alpha, d_x, d_y);
    hipDeviceSynchronize();
}
```

### 2.2 Runtime Device Detection

```cpp
#include <hip/hip_runtime.h>
#include <iostream>

void print_gpu_info() {
    int n_devices;
    hipGetDeviceCount(&n_devices);
    for (int i = 0; i < n_devices; ++i) {
        hipDeviceProp_t prop;
        hipGetDeviceProperties(&prop, i);
        std::cout << "Device " << i << ": " << prop.name
                  << "  arch=" << prop.gcnArch
                  << "  VRAM=" << (prop.totalGlobalMem >> 20) << " MB\n";
    }
}
```

---

## III. SYCL: True Cross-Vendor Portability

### 3.1 SYCL Kernel Syntax

SYCL provides a standards-based C++17 API that compiles to PTX, GCN, or SPIR-V:

```cpp
#include <sycl/sycl.hpp>
#include <vector>

void saxpy_sycl(
    sycl::queue& q,
    int n, float alpha,
    const std::vector<float>& x,
    std::vector<float>& y
) {
    sycl::buffer<float, 1> buf_x(x.data(), n);
    sycl::buffer<float, 1> buf_y(y.data(), n);

    q.submit([&](sycl::handler& h) {
        auto ax = buf_x.get_access<sycl::access::mode::read>(h);
        auto ay = buf_y.get_access<sycl::access::mode::read_write>(h);
        h.parallel_for(sycl::range<1>(n), [=](sycl::id<1> i) {
            ay[i] = alpha * ax[i] + ay[i];
        });
    });
}
```

### 3.2 Device Selection

```cpp
// Select GPU over CPU
sycl::queue q{sycl::gpu_selector_v};

// Or specific vendor
auto intel_selector = [](const sycl::device& d) {
    return d.get_info<sycl::info::device::vendor>().find("Intel") != std::string::npos ? 1 : -1;
};
sycl::queue q_intel{sycl::device{intel_selector}};
```

---

## IV. Performance Portability

### 4.1 Roofline Model

The roofline model bounds GPU performance by:

$$\text{Performance} \leq \min\left(\text{Peak FLOPS}, \text{Peak BW} \times \text{AI}\right)$$

where $\text{AI} = \text{FLOPS} / \text{Bytes}$ is the arithmetic intensity.

| Kernel | AI (FLOP/byte) | Bound | Portable Target |
|--------|---------------|-------|----------------|
| SAXPY | 0.25 | Memory | Maximize vectorization |
| SGEMM | 16–256 | Compute | Target 60% peak FLOPS |
| Attention | 4–8 | Memory | Fuse QKV in one pass |

---

## References

- AMD (2023). HIP Programming Guide. rocmdocs.amd.com/projects/HIP.
- Khronos Group (2023). SYCL 2020 Specification. khronos.org/sycl.
- Williams, S. et al. (2009). Roofline: An Insightful Visual Performance Model. *CACM*, 52(4), 65-76.
- Intel (2023). oneAPI DPC++ Compiler Documentation. intel.com/oneapi.
