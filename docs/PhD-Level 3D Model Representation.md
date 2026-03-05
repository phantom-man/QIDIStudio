# PhD-Level 3D Model Representation Theory

A rigorous survey of 3D model representations — implicit, explicit, and learned — covering mathematical foundations, computational complexities, and optimal selection criteria for geometry processing, simulation, and ML pipelines.

---

## I. Taxonomy of 3D Representations

| Representation | Mathematical Object | Storage | Differentiable | Topology-Free |
|---------------|-------------------|---------|---------------|---------------|
| Mesh (triangle) | Simplicial 2-complex | $O(F)$ | Via cotangent | No |
| Signed Distance Field | $\phi: \mathbb{R}^3 \to \mathbb{R}$ | $O(N^3)$ | Yes | Yes |
| Point cloud | $P \subset \mathbb{R}^3$ | $O(N)$ | Via PointNet | Yes |
| Octree / BSP | Spatial tree | $O(N \log N)$ | No | Yes |
| Neural (NeRF, NeSF) | $f_\theta: \mathbb{R}^3 \to (\sigma, c)$ | $O(|\theta|)$ | Yes | Yes |
| B-Rep (CAD) | Half-edge DCEL | $O(E)$ | No | No |

---

## II. Implicit Representations

### 2.1 Signed Distance Functions

A Signed Distance Function (SDF) $\phi(\mathbf{x})$ is defined as:

$$\phi(\mathbf{x}) = s \cdot \min_{\mathbf{p} \in \partial \mathcal{M}} \|\mathbf{x} - \mathbf{p}\|_2, \quad s = \text{sign}(\mathbf{x} \text{ inside/outside})$$

The zero level set $\{\mathbf{x} : \phi(\mathbf{x}) = 0\}$ is the surface $\partial \mathcal{M}$.

Key properties:
- Eikonal equation: $\|\nabla \phi\| = 1$ everywhere (exact SDF)
- **Marching Cubes** extracts a mesh from $\phi$ at $O(N^3)$ cost
- **Sphere tracing** ray-marches along $\hat{\mathbf{r}}$ using step size $\phi(\mathbf{x})$: converges in $O(\log(1/\epsilon))$ steps

### 2.2 CSG with SDFs

Constructive Solid Geometry operations map trivially to SDF arithmetic:

| CSG Operation | SDF Formula |
|--------------|------------|
| Union | $\phi_A \cup \phi_B = \min(\phi_A, \phi_B)$ |
| Intersection | $\phi_A \cap \phi_B = \max(\phi_A, \phi_B)$ |
| Difference | $\phi_A \setminus \phi_B = \max(\phi_A, -\phi_B)$ |
| Smooth Union | $\phi_{SU} = -\log(e^{-\phi_A/k} + e^{-\phi_B/k}) \cdot k$ |

Smooth union with $k$ controls blend radius at the seam.

---

## III. Mesh Representations

### 3.1 Half-Edge Data Structure

The **DCEL (Doubly Connected Edge List)** stores three parallel arrays:

```python
from dataclasses import dataclass
import numpy as np

@dataclass
class HalfEdge:
    vertex: int       # origin vertex index
    face: int         # incident face
    twin: int         # opposite half-edge
    next: int         # next half-edge in face loop
    prev: int         # previous half-edge in face loop

class HalfEdgeMesh:
    def __init__(self, vertices: np.ndarray, faces: np.ndarray):
        self.V = vertices          # (V, 3) float64
        self.F = faces             # (F, 3) int32
        self.half_edges: list[HalfEdge] = []
        self._build()

    def _build(self) -> None:
        edge_map: dict[tuple[int, int], int] = {}
        for f_idx, face in enumerate(self.F):
            tri_hes = []
            for i in range(3):
                v0, v1 = int(face[i]), int(face[(i+1) % 3])
                he_idx = len(self.half_edges)
                self.half_edges.append(HalfEdge(vertex=v0, face=f_idx, twin=-1, next=-1, prev=-1))
                edge_map[(v0, v1)] = he_idx
                tri_hes.append(he_idx)
            for i in range(3):
                self.half_edges[tri_hes[i]].next = tri_hes[(i+1) % 3]
                self.half_edges[tri_hes[i]].prev = tri_hes[(i-1) % 3]
        # Link twins
        for (v0, v1), he_idx in edge_map.items():
            twin_idx = edge_map.get((v1, v0), -1)
            self.half_edges[he_idx].twin = twin_idx
```

### 3.2 Mesh Complexity Analysis

| Operation | DCEL | Adjacency List | Indexed Mesh |
|-----------|------|----------------|-------------|
| Vertex neighbours | $O(k)$ | $O(k)$ | $O(F)$ |
| Face traversal | $O(F)$ | $O(F)$ | $O(F)$ |
| Edge collapse | $O(k)$ | $O(k^2)$ | $O(F)$ |
| Memory | $6E$ ptrs | $2E + V$ | $3F$ indices |

where $k$ is the vertex valence and $E = 3F/2$ for closed manifold.

---

## IV. Neural 3D Representations

### 4.1 Neural Radiance Fields (NeRF)

NeRF encodes a scene as an MLP $f_\theta: (\mathbf{x}, \hat{\mathbf{d}}) \mapsto (\sigma, \mathbf{c})$:

$$C(\mathbf{r}) = \int_{t_n}^{t_f} T(t) \sigma(\mathbf{r}(t)) \mathbf{c}(\mathbf{r}(t), \hat{\mathbf{d}}) \, dt$$

where $T(t) = \exp\left(-\int_{t_n}^t \sigma(\mathbf{r}(s)) \, ds\right)$ is the accumulated transmittance.

Training minimizes photometric loss: $\mathcal{L} = \sum_{\mathbf{r} \in \mathcal{R}} \|\hat{C}(\mathbf{r}) - C(\mathbf{r})\|_2^2$.

---

## V. Representation Selection Guide

| Use Case | Best Representation | Reason |
|---------|-------------------|--------|
| FDM slicing | Triangle mesh | Fast AABB-tree slicing |
| Topology optimization | SDF / voxel | Easy volume fraction |
| UV parameterization | Triangle mesh | cotangent Laplacian |
| Scene reconstruction | NeRF / 3DGS | View-consistent |
| CAD/machining | B-Rep | Exact geometry |
| ML shape learning | Point cloud + PointNet | Permutation-invariant |

---

## References

- Botsch, M. et al. (2010). *Polygon Mesh Processing*. A K Peters.
- Mildenhall, B. et al. (2020). NeRF: Representing Scenes as Neural Radiance Fields. *ECCV 2020*.
- Park, J.J. et al. (2019). DeepSDF: Learning Continuous Signed Distance Functions. *CVPR 2019*.
- Lorensen, W.E. & Cline, H.E. (1987). Marching Cubes: A High Resolution 3D Surface Construction Algorithm. *SIGGRAPH 1987*.
