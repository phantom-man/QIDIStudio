# Multi-GPU Build Configuration for Machine Learning Workloads

A comprehensive guide to configuring heterogeneous multi-GPU builds — covering CUDA/ROCm toolchain setup, CMake multi-target compilation, inter-GPU communication (NCCL/RCCL), and memory topology optimization.

---

## I. GPU Architecture Review

### 1.1 CUDA vs ROCm Compilation Models

| Attribute | NVIDIA CUDA | AMD ROCm/HIP |
|-----------|------------|-------------|
| Compiler | `nvcc` | `hipcc` (clang-based) |
| ISA target | PTX → SASS | GCN LLVM IR → ISA |
| Parallel thread model | CUDA thread hierarchy | HIP thread hierarchy (identical API) |
| Peer-to-peer | NVLink / PCIe | xGMI / Infinity Fabric |
| Multi-target | Fatbinary (sm_80+sm_90) | `--offload-arch=gfx1100,gfx906` |

### 1.2 CUDA Compute Capability Targets

For a multi-GPU build targeting A100 (sm_80) + RTX 3090 (sm_86) + H100 (sm_90):

```cmake
set(CMAKE_CUDA_ARCHITECTURES "80;86;90")
```

This generates PTX for all three and embeds SASS for targeted cards.

---

## II. CMake Multi-GPU Configuration

### 2.1 FindCUDAToolkit Integration

```cmake
cmake_minimum_required(VERSION 3.24)
project(MultiGPUProject LANGUAGES CXX CUDA)

# Require CUDA 12.x
find_package(CUDAToolkit 12.0 REQUIRED)

set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_ARCHITECTURES "80;86;90")

# Enable separable compilation for device-side linking
set_property(TARGET my_lib PROPERTY CUDA_SEPARABLE_COMPILATION ON)

add_library(my_lib STATIC
    src/kernels/attention.cu
    src/kernels/conv3d.cu
    src/device_vector.cu
)

target_link_libraries(my_lib
    CUDA::cudart
    CUDA::cublas
    CUDA::nccl          # Multi-GPU collective operations
)
```

### 2.2 NCCL All-Reduce for Gradient Sync

```cpp
#include <nccl.h>
#include <cuda_runtime.h>
#include <vector>
#include <stdexcept>

void multi_gpu_allreduce(
    std::vector<float*>& device_grads,
    size_t count,
    std::vector<int>& gpu_ids
) {
    int n_gpus = gpu_ids.size();
    std::vector<ncclComm_t> comms(n_gpus);
    std::vector<cudaStream_t> streams(n_gpus);

    // Initialize communicators
    ncclCommInitAll(comms.data(), n_gpus, gpu_ids.data());

    for (int i = 0; i < n_gpus; ++i) {
        cudaSetDevice(gpu_ids[i]);
        cudaStreamCreate(&streams[i]);
    }

    // All-reduce gradient buffers across GPUs
    ncclGroupStart();
    for (int i = 0; i < n_gpus; ++i) {
        ncclAllReduce(
            device_grads[i], device_grads[i],
            count, ncclFloat, ncclSum,
            comms[i], streams[i]
        );
    }
    ncclGroupEnd();

    // Synchronize
    for (int i = 0; i < n_gpus; ++i) {
        cudaSetDevice(gpu_ids[i]);
        cudaStreamSynchronize(streams[i]);
    }

    // Scale gradients by 1/n_gpus
    for (int i = 0; i < n_gpus; ++i) {
        cudaSetDevice(gpu_ids[i]);
        // ... scale kernel ...
    }

    // Cleanup
    for (auto& c : comms) ncclCommDestroy(c);
    for (auto& s : streams) cudaStreamDestroy(s);
}
```

---

## III. Memory Topology Optimization

### 3.1 NVLink vs PCIe Bandwidth

| Connection | Bandwidth (bidirectional) | Latency |
|-----------|--------------------------|---------|
| PCIe 4.0 ×16 | 32 GB/s | ~2 µs |
| PCIe 5.0 ×16 | 64 GB/s | ~1.5 µs |
| NVLink 3.0 (A100) | 600 GB/s | ~5 µs |
| NVLink 4.0 (H100) | 900 GB/s | ~4 µs |

For NCCL ring all-reduce with $n$ GPUs and $d$ bytes per GPU:
$$\text{Transfer time} = \frac{2(n-1)}{n} \cdot \frac{d}{B}$$

### 3.2 Pinned Memory Strategy

```cpp
// Use pinned (page-locked) host memory for async transfers
float* pinned_buf;
cudaMallocHost(&pinned_buf, n_bytes);  // page-locked

// Async transfer to multiple GPUs simultaneously
for (int g = 0; g < n_gpus; ++g) {
    cudaSetDevice(g);
    cudaMemcpyAsync(dev_ptrs[g], pinned_buf, n_bytes,
                    cudaMemcpyHostToDevice, streams[g]);
}
```

Pinned memory enables DMA directly from host DRAM to GPU HBM, bypassing the CPU cache — critical for $>10$ GB/s effective throughput.

---

## IV. PyTorch Multi-GPU Build Configuration

```python
import torch
import torch.distributed as dist
import torch.nn.parallel

def setup_ddp(rank: int, world_size: int, backend: str = "nccl") -> None:
    """Initialize distributed training on rank `rank`."""
    dist.init_process_group(
        backend=backend,
        init_method="env://",
        rank=rank,
        world_size=world_size,
    )
    torch.cuda.set_device(rank)

def wrap_model(model: torch.nn.Module, rank: int) -> torch.nn.Module:
    """Wrap model for DDP with local GPU rank."""
    return torch.nn.parallel.DistributedDataParallel(
        model.cuda(rank),
        device_ids=[rank],
        output_device=rank,
        find_unused_parameters=False,  # Set True only if needed — 30% overhead
    )
```

---

## V. Build Performance Benchmarks

| Config | GPU | Batch/s (ResNet-50) | Notes |
|--------|-----|---------------------|-------|
| Single A100 | 1× A100 80GB | 3200 | Baseline |
| 4× A100 NVLink | 4× A100 | 12400 | 97% scaling |
| 8× A100 NVLink | 8× A100 | 24100 | 94% scaling |
| 4× RTX 3090 PCIe | 4× RTX 3090 | 9800 | 77% scaling (PCIe bottleneck) |

---

## References

- NVIDIA (2023). NCCL Developer Guide. developer.nvidia.com/nccl.
- Li, S. et al. (2020). PyTorch Distributed: Experiences on Accelerating Data Parallel Training. *VLDB 2020*.
- NVIDIA (2023). CUDA C++ Programming Guide, §3.2 (Device Memory). docs.nvidia.com.
- Hoefler, T. & Belli, R. (2015). Scientific Benchmarking of Parallel Computing Systems. *SC 2015*.
