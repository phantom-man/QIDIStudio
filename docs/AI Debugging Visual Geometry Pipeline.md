# AI Debugging Visual Geometry Pipeline

A formal methodology for deploying an AI agent as the primary controller in a cyber-physical debugging loop over 3D geometry pipelines — replacing ad-hoc inspection with metric-driven, automated visual verification.

---

## I. System Architecture: Cyber-Physical Feedback Loop

The pipeline treats the geometry renderer as a continuous-time plant $G(s)$ controlled by an AI agent $C$:

$$u(t) = C\bigl(e(t)\bigr), \quad e(t) = r(t) - y(t)$$

where $r(t)$ is the reference mesh state, $y(t)$ is the rendered output, and $u(t)$ is the corrective action (parameter update, mesh repair, shader reload).

### 1.1 Agent Roles

| Component | Role | Interface |
|-----------|------|-----------|
| Observer | Captures render snapshots at breakpoints | OpenGL readPixels / headless EGL |
| Analyzer | Classifies error type from snapshot | Vision LLM (Claude Sonnet with image) |
| Planner | Generates repair action | Tool-calling LLM (structured JSON) |
| Executor | Applies mesh/shader/UV patch | Python `bpy` or `trimesh` API |
| Validator | Confirms repair reduced error metric | delta($M_{stretch}$) or delta($M_{normal}$) |

---

## II. Error Taxonomy and Metrics

### 2.1 Geometric Error Classes

**Class G1 — Projection Distortion**: occurs when the map $\pi: \mathbb{R}^3 \to \mathbb{R}^2$ introduces anisotropic stretch. Detected by comparing the singular values $\sigma_1, \sigma_2$ of the Jacobian $\mathbf{J}_\pi$:

$$E_D = \frac{\sigma_1}{\sigma_2}, \quad E_D > 2 \Rightarrow \text{anisotropic flag}$$

**Class G2 — Normal Discontinuity**: surface normal field $\mathbf{n}(\mathbf{p})$ has discontinuities across seam edges. Metric:

$$E_N = \frac{1}{|E_{seam}|} \sum_{e \in E_{seam}} \left(1 - \mathbf{n}_L(e) \cdot \mathbf{n}_R(e)\right)$$

$E_N > 0.1$ indicates visible seam artifacts.

**Class G3 — Winding Order Violation**: triangle normals $\hat{\mathbf{n}}_i$ are inconsistent with the outward convention. Detected by:

```python
import numpy as np
import trimesh

def find_winding_errors(mesh: trimesh.Trimesh) -> np.ndarray:
    """Return face indices where normal opposes vertex-order convention."""
    v0 = mesh.vertices[mesh.faces[:, 0]]
    v1 = mesh.vertices[mesh.faces[:, 1]]
    v2 = mesh.vertices[mesh.faces[:, 2]]
    cross = np.cross(v1 - v0, v2 - v0)
    dot = np.einsum("ij,ij->i", cross, mesh.face_normals)
    return np.where(dot < 0)[0]
```

---

## III. Visual Breakpoint Protocol

### 3.1 Snapshot Capture at Breakpoints

Each pipeline stage emits a render snapshot encoded as base64 PNG:

```python
import bpy, base64, pathlib

def capture_viewport_snapshot(out_path: pathlib.Path, resolution: tuple[int,int] = (512, 512)) -> str:
    """Render current Blender viewport to file, return base64 PNG string."""
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.opengl(write_still=True)
    bpy.data.images["Render Result"].save_render(str(out_path))
    return base64.b64encode(out_path.read_bytes()).decode()
```

### 3.2 AI Critic Invocation

The snapshot is passed to the vision model with a structured diagnostic packet:

```python
VISUAL_DEBUG_PROMPT = """\
You are a 3D geometry debugging expert. Analyze the render snapshot for errors.

Mesh: {mesh_name}
Stage: {stage}
Current metrics: stretch_E_D={stretch:.3f}, seam_E_N={seam:.4f}, winding_errors={winding}

Classify the primary error and prescribe a concrete repair action.
Output JSON: {{"error_class": "G1|G2|G3|NONE",
               "severity": "low|medium|high",
               "repair_action": "<specific function call or parameter change>",
               "expected_delta_metric": <float>}}"""
```

---

## IV. Automated Repair Dispatcher

```python
from dataclasses import dataclass
from typing import Callable
import trimesh

@dataclass
class RepairAction:
    error_class: str
    severity: str
    repair_fn: Callable[[trimesh.Trimesh], trimesh.Trimesh]

REPAIR_REGISTRY: dict[str, Callable] = {
    "G1": lambda m: _reparameterize_lscm(m),
    "G2": lambda m: _smooth_seam_normals(m),
    "G3": lambda m: trimesh.repair.fix_winding(m),
}

def dispatch_repair(mesh: trimesh.Trimesh, error_class: str) -> trimesh.Trimesh:
    fn = REPAIR_REGISTRY.get(error_class)
    if fn is None:
        raise ValueError(f"Unknown error class: {error_class}")
    return fn(mesh)
```

---

## V. Convergence Loop

The full debugging loop runs until all metrics fall below threshold:

```python
MAX_ITERATIONS = 10
THRESHOLDS = {"E_D": 2.0, "E_N": 0.1, "winding": 0}

def debug_loop(mesh: trimesh.Trimesh, capture_fn, critic_fn) -> trimesh.Trimesh:
    for i in range(MAX_ITERATIONS):
        metrics = compute_metrics(mesh)
        if all(metrics[k] <= THRESHOLDS[k] for k in THRESHOLDS):
            break
        snapshot_b64 = capture_fn(mesh)
        action = critic_fn(snapshot_b64, metrics)
        mesh = dispatch_repair(mesh, action["error_class"])
    return mesh
```

---

## References

- Akenine-Möller, T. et al. (2018). *Real-Time Rendering*, 4th ed. CRC Press.
- Lévy, B. et al. (2002). Least Squares Conformal Maps for Automatic Texture Atlas Generation. *SIGGRAPH 2002*.
- Sanderson, G. (3Blue1Brown). Linear transformations and matrices. *YouTube* (visual intuition for Jacobians).
- Sorkine, O. et al. (2004). Laplacian Surface Editing. *SGP 2004*.
