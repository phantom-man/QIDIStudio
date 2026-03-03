"""
agents/torch_tools.py — PyTorch ↔ LangChain Tool Bridge.

Architectural pattern (from "Neural-Symbolic Integration" design):
  LLM  = High-Level Symbolic Controller  (decides WHY to act)
  PyTorch = Low-Level Differentiable Kernel  (executes the physics)
  LangSmith = Observability / Feedback / Dataset Generation Plane

Each @tool here acts as the "Tensor-to-Text Interface":
  Tensor output → Structured JSON (semantic) → LLM-readable insight

Graceful degradation: All tools work without CUDA; without PyTorch they fall
back to geometry-based heuristics so the manufacturing graph never hard-fails.

Models:
  MeshStressGNN     — Graph Neural Network predicting von Mises stress hotspots
  NozzlePressureLSTM — LSTM predicting clog probability from pressure time-series
  TextureQualityMLP  — Multi-layer perceptron scoring texture uniformity from UV stats

Training data is generated automatically by hardware_feedback.py from LangSmith
"FAIL" traces — closing the self-healing factory loop.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# ── LangChain tool decorator ──────────────────────────────────────────────────
from langchain_core.tools import tool

# ── Optional PyTorch import ───────────────────────────────────────────────────
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TORCH_AVAILABLE = False
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]

# ── Weights directory (checkpoint files live here when trained) ───────────────
_WEIGHTS_DIR = Path(__file__).parents[1] / "resources" / "ml_weights"
_WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# I.  Model Architectures
# ═══════════════════════════════════════════════════════════════════════════════


def _build_mesh_stress_gnn() -> "nn.Module | None":
    """
    Lightweight Message-Passing GNN (PointNet++ style) for mesh stress prediction.

    Input:  (N, 6) — per-vertex [x, y, z, nx, ny, nz]
    Output: (N, 1) — per-vertex von Mises stress probability [0, 1]

    Architecture follows the "Execution Bridge" pattern — the model is a pure
    tensor function; the @tool wrapper translates its output to semantic JSON.
    """
    if not _TORCH_AVAILABLE:
        return None

    class MeshStressGNN(nn.Module):
        """3-layer PointNet-inspired MLP with skip connections."""

        def __init__(self) -> None:
            super().__init__()
            self.fc1 = nn.Linear(6, 64)
            self.fc2 = nn.Linear(64, 128)
            self.fc3 = nn.Linear(128, 64)
            self.fc4 = nn.Linear(64, 1)
            self.bn1 = nn.BatchNorm1d(64)
            self.bn2 = nn.BatchNorm1d(128)
            self.bn3 = nn.BatchNorm1d(64)
            self.dropout = nn.Dropout(0.3)

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            x = F.relu(self.bn1(self.fc1(x)))
            x = F.relu(self.bn2(self.fc2(x)))
            x = self.dropout(x)
            x = F.relu(self.bn3(self.fc3(x)))
            return torch.sigmoid(self.fc4(x))  # per-vertex stress score

    model = MeshStressGNN()
    weights_path = _WEIGHTS_DIR / "mesh_stress_gnn.pth"
    if weights_path.exists():
        state = torch.load(weights_path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
    model.eval()
    return model


def _build_nozzle_lstm() -> "nn.Module | None":
    """
    LSTM for nozzle clog prediction from pressure time-series.

    Input:  (batch, seq_len, 3)  — [pressure, temp, flow_rate] per timestep
    Output: (batch, 1)           — clog probability
    """
    if not _TORCH_AVAILABLE:
        return None

    class NozzlePressureLSTM(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=3,
                hidden_size=64,
                num_layers=2,
                batch_first=True,
                dropout=0.2,
            )
            self.fc = nn.Linear(64, 1)

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            out, _ = self.lstm(x)
            return torch.sigmoid(self.fc(out[:, -1, :]))  # last timestep

    model = NozzlePressureLSTM()
    weights_path = _WEIGHTS_DIR / "nozzle_lstm.pth"
    if weights_path.exists():
        state = torch.load(weights_path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
    model.eval()
    return model


def _build_texture_mlp() -> "nn.Module | None":
    """
    MLP scoring texture quality from UV statistics.

    Input:  (1, 7) — [mean_stretch, max_stretch, std_stretch, high_energy_frac,
                       dirichlet_energy, n_faces_norm, aspect_ratio]
    Output: (1, 3) — [uniformity_score, seam_score, beauty_score]
    """
    if not _TORCH_AVAILABLE:
        return None

    class TextureQualityMLP(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(7, 32),
                nn.ReLU(),
                nn.Linear(32, 16),
                nn.ReLU(),
                nn.Linear(16, 3),
                nn.Sigmoid(),
            )

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            return self.net(x)

    model = TextureQualityMLP()
    weights_path = _WEIGHTS_DIR / "texture_quality_mlp.pth"
    if weights_path.exists():
        state = torch.load(weights_path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
    model.eval()
    return model


# ── Lazy-loaded singletons ────────────────────────────────────────────────────
_stress_gnn: Any = None
_nozzle_lstm: Any = None
_texture_mlp: Any = None


def _get_stress_gnn():
    global _stress_gnn
    if _stress_gnn is None:
        _stress_gnn = _build_mesh_stress_gnn()
    return _stress_gnn


def _get_nozzle_lstm():
    global _nozzle_lstm
    if _nozzle_lstm is None:
        _nozzle_lstm = _build_nozzle_lstm()
    return _nozzle_lstm


def _get_texture_mlp():
    global _texture_mlp
    if _texture_mlp is None:
        _texture_mlp = _build_texture_mlp()
    return _texture_mlp


# ═══════════════════════════════════════════════════════════════════════════════
# II.  Support-region cluster helper
# ═══════════════════════════════════════════════════════════════════════════════


def _cluster_stress_regions(
    verts: list[list[float]],
    scores: list[float],
    threshold: float = 0.7,
    grid_resolution: int = 20,
    max_regions: int = 8,
    min_verts_per_region: int = 3,
    bbox_padding_mm: float = 2.0,
) -> list[dict]:
    """
    Cluster high-stress vertices into candidate support regions using a
    voxel-grid flood-fill (no scipy/sklearn dependency).

    Algorithm:
      1. Filter vertices whose stress score exceeds *threshold*.
      2. Map each vertex to a voxel index on a grid_resolution^3 grid.
      3. BFS/flood-fill with 26-voxel connectivity to label components.
      4. For each component compute centroid, bbox_min/max, mean stress,
         then add *bbox_padding_mm* clearance around each side.
      5. Sort by stress_density × sqrt(n_vertices); return top max_regions.

    Returns a list of region dicts, each with:
      centroid      — [x, y, z] mm (mean of member vertices)
      bbox_min      — [x, y, z] mm  (padded bounding box minimum)
      bbox_max      — [x, y, z] mm  (padded bounding box maximum)
      stress_density — float  (mean score of member vertices)
      n_vertices     — int
      priority       — "HIGH" | "MEDIUM"
    """
    # Step 1 — filter
    hotspots = [(v, s) for v, s in zip(verts, scores) if s >= threshold]
    if not hotspots:
        return []

    hs_verts, hs_scores = zip(*hotspots)
    hs_verts = list(hs_verts)
    hs_scores = list(hs_scores)

    # Step 2 — build voxel grid (based on FULL mesh bbox for stable coordinates)
    all_x = [v[0] for v in verts]
    all_y = [v[1] for v in verts]
    all_z = [v[2] for v in verts]
    bx_min, bx_max = min(all_x), max(all_x)
    by_min, by_max = min(all_y), max(all_y)
    bz_min, bz_max = min(all_z), max(all_z)

    def _to_voxel(v: list[float]) -> tuple[int, int, int]:
        gi = int((v[0] - bx_min) / max(bx_max - bx_min, 1e-6) * (grid_resolution - 1))
        gj = int((v[1] - by_min) / max(by_max - by_min, 1e-6) * (grid_resolution - 1))
        gk = int((v[2] - bz_min) / max(bz_max - bz_min, 1e-6) * (grid_resolution - 1))
        return (gi, gj, gk)

    # Map voxel → [vertex_indices]
    voxel_map: dict[tuple[int, int, int], list[int]] = {}
    for idx, v in enumerate(hs_verts):
        key = _to_voxel(v)
        voxel_map.setdefault(key, []).append(idx)

    # Step 3 — BFS flood-fill (26-connectivity)
    visited: set[tuple[int, int, int]] = set()
    components: list[list[int]] = []

    def _neighbours(cell: tuple[int, int, int]):
        ci, cj, ck = cell
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for dk in (-1, 0, 1):
                    if di == dj == dk == 0:
                        continue
                    nb = (ci + di, cj + dj, ck + dk)
                    if nb in voxel_map:
                        yield nb

    for start in voxel_map:
        if start in visited:
            continue
        # BFS
        queue = [start]
        visited.add(start)
        component_verts: list[int] = []
        while queue:
            cell = queue.pop()
            component_verts.extend(voxel_map[cell])
            for nb in _neighbours(cell):
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)
        components.append(component_verts)

    # Step 4 — compute region stats
    regions = []
    for member_indices in components:
        if len(member_indices) < min_verts_per_region:
            continue
        mverts = [hs_verts[i] for i in member_indices]
        mscores = [hs_scores[i] for i in member_indices]
        cx = sum(v[0] for v in mverts) / len(mverts)
        cy = sum(v[1] for v in mverts) / len(mverts)
        cz = sum(v[2] for v in mverts) / len(mverts)
        rx_min = min(v[0] for v in mverts) - bbox_padding_mm
        ry_min = min(v[1] for v in mverts) - bbox_padding_mm
        rz_min = min(v[2] for v in mverts) - bbox_padding_mm
        rx_max = max(v[0] for v in mverts) + bbox_padding_mm
        ry_max = max(v[1] for v in mverts) + bbox_padding_mm
        rz_max = max(v[2] for v in mverts) + bbox_padding_mm
        density = sum(mscores) / len(mscores)
        regions.append(
            {
                "centroid": [round(cx, 3), round(cy, 3), round(cz, 3)],
                "bbox_min": [round(rx_min, 3), round(ry_min, 3), round(rz_min, 3)],
                "bbox_max": [round(rx_max, 3), round(ry_max, 3), round(rz_max, 3)],
                "stress_density": round(density, 4),
                "n_vertices": len(member_indices),
                "priority": "HIGH" if density >= 0.85 else "MEDIUM",
            }
        )

    # Step 5 — sort: stress_density × sqrt(n_vertices) descending
    regions.sort(
        key=lambda r: r["stress_density"] * r["n_vertices"] ** 0.5, reverse=True
    )
    return regions[:max_regions]


# ═══════════════════════════════════════════════════════════════════════════════
# III.  LangChain @tool wrappers — "Tensor-to-Text Interface"
# ═══════════════════════════════════════════════════════════════════════════════


@tool
def evaluate_mesh_structural_integrity(
    vertices: list[list[float]],
    normals: list[list[float]] | None = None,
    material_pla_hs: bool = True,
) -> dict:
    """
    Use a PyTorch GNN (MeshStressGNN) to predict structural stress hotspots in
    a 3D mesh before printing.

    Args:
        vertices:           List of [x, y, z] vertex positions (max 50,000 for perf).
        normals:            Optional list of [nx, ny, nz] vertex normals.
        material_pla_hs:    True = High-Speed PLA (yield strength ~50 MPa assumption).

    Returns:
        Semantic JSON with:
          failure_probability   : float  0-1 — overall structural risk
          high_stress_vertex_pct: float  % of vertices above 0.7 stress threshold
          hotspot_centroid      : [x,y,z] — geometric centre of stress concentration
          recommendation        : str — human-readable action for the LLM
          torch_metadata        : dict — inference_latency_ms, gpu_memory_delta_mb
    """
    t0 = time.perf_counter()
    gpu_before = 0.0

    # Clamp input size
    verts = vertices[:50_000]
    norms = (normals or [[0, 0, 1]] * len(verts))[:50_000]

    if _TORCH_AVAILABLE:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if device.type == "cuda":
            gpu_before = torch.cuda.memory_allocated(device) / 1e6

        # Build (N, 6) feature matrix
        feat = [[*v, *n] for v, n in zip(verts, norms)]
        x = torch.tensor(feat, dtype=torch.float32, device=device)

        model = _get_stress_gnn()
        if model is not None:
            model = model.to(device)
            with torch.no_grad():
                scores = model(x).squeeze(-1).cpu().numpy()
        else:
            # Model architecture ready but no weights — use geometry heuristic
            scores = _geometry_stress_heuristic(verts)
    else:
        scores = _geometry_stress_heuristic(verts)

    latency_ms = (time.perf_counter() - t0) * 1000
    gpu_after = 0.0
    if _TORCH_AVAILABLE and torch.cuda.is_available():
        gpu_after = torch.cuda.memory_allocated() / 1e6

    high_stress_mask = [s > 0.7 for s in scores]
    hs_pct = float(sum(high_stress_mask)) / max(len(scores), 1) * 100.0
    failure_prob = float(max(scores)) * 0.6 + (hs_pct / 100.0) * 0.4

    # Compute centroid of high-stress vertices
    hs_verts = [v for v, m in zip(verts, high_stress_mask) if m]
    if hs_verts:
        cx = sum(v[0] for v in hs_verts) / len(hs_verts)
        cy = sum(v[1] for v in hs_verts) / len(hs_verts)
        cz = sum(v[2] for v in hs_verts) / len(hs_verts)
        centroid = [round(cx, 3), round(cy, 3), round(cz, 3)]
    else:
        centroid = [0.0, 0.0, 0.0]

    # Yield strength correction for material
    yield_mpa = 50.0 if material_pla_hs else 35.0
    risk_label = (
        "CRITICAL"
        if failure_prob > 0.85
        else "WARNING" if failure_prob > 0.55 else "SAFE"
    )
    recommendation = {
        "CRITICAL": (
            f"Failure probability {failure_prob:.2f} exceeds 0.85 threshold. "
            f"{hs_pct:.1f}% of vertices show von Mises stress above 0.7. "
            f"Route to REDESIGN: increase wall thickness near hotspot {centroid}, "
            f"add organic ribs, or reduce unsupported span. "
            f"Material: PLA-HS yield ≈{yield_mpa} MPa — consider ABS/ASA for structural loads."
        ),
        "WARNING": (
            f"Moderate stress concentration ({hs_pct:.1f}% high-stress vertices). "
            f"Consider adding supports or fillets near {centroid}. "
            f"Proceed to texture with caution."
        ),
        "SAFE": (
            f"Structural integrity OK (failure_prob={failure_prob:.2f}). "
            f"Proceed to texture pipeline."
        ),
    }[risk_label]

    # Cluster high-stress vertices into support habitat bounding boxes
    support_regions = _cluster_stress_regions(
        verts=verts,
        scores=[float(s) for s in scores],
        threshold=0.70,
        grid_resolution=20,
        max_regions=8,
        bbox_padding_mm=2.0,
    )

    return {
        "failure_probability": round(failure_prob, 4),
        "high_stress_vertex_pct": round(hs_pct, 2),
        "hotspot_centroid": centroid,
        "risk_label": risk_label,
        "recommendation": recommendation,
        "support_regions": support_regions,
        "torch_metadata": {
            "backend": "pytorch" if _TORCH_AVAILABLE else "heuristic",
            "device": (
                "cuda" if (_TORCH_AVAILABLE and torch.cuda.is_available()) else "cpu"
            ),
            "inference_latency_ms": round(latency_ms, 1),
            "gpu_memory_delta_mb": round(gpu_after - gpu_before, 2),
            "weights_loaded": (_WEIGHTS_DIR / "mesh_stress_gnn.pth").exists(),
            "n_vertices": len(verts),
        },
    }


@tool
def analyze_nozzle_pressure(
    pressure_series: list[float],
    temperature_series: list[float],
    flow_rate_series: list[float],
) -> dict:
    """
    Use a PyTorch LSTM to predict nozzle clogs from real-time sensor data.

    Args:
        pressure_series:   N timesteps of nozzle back-pressure (PSI).
        temperature_series: N timesteps of hotend temperature (°C).
        flow_rate_series:  N timesteps of volumetric flow rate (mm³/s).

    Returns:
        clog_probability   : float 0-1
        predicted_clog_in  : str — "imminent (<5 min)" / "warning (5-20 min)" / "nominal"
        action             : str — recommended action for the LLM agent
        torch_metadata     : dict
    """
    t0 = time.perf_counter()
    n = max(len(pressure_series), 1)
    seq_len = min(n, 64)  # use last 64 timesteps

    p = pressure_series[-seq_len:]
    t = temperature_series[-seq_len:]
    f = flow_rate_series[-seq_len:]

    if _TORCH_AVAILABLE:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        x = torch.tensor(
            [[pp, tt, ff] for pp, tt, ff in zip(p, t, f)],
            dtype=torch.float32,
            device=device,
        ).unsqueeze(0)
        model = _get_nozzle_lstm()
        if model is not None:
            model = model.to(device)
            with torch.no_grad():
                clog_prob = float(model(x).item())
        else:
            clog_prob = _pressure_heuristic(p, t)
    else:
        clog_prob = _pressure_heuristic(p, t)

    latency_ms = (time.perf_counter() - t0) * 1000

    if clog_prob > 0.80:
        prediction = "imminent (<5 min)"
        action = (
            f"STOP PRINT — clog probability {clog_prob:.2f}. "
            "Perform cold-pull, inspect PTFE tube, verify temp PID stability."
        )
    elif clog_prob > 0.50:
        prediction = "warning (5-20 min)"
        action = (
            f"ALERT — clog risk {clog_prob:.2f}. "
            "Reduce feed rate 15%, increase hotend temp +5°C, monitor next 10 layers."
        )
    else:
        prediction = "nominal"
        action = f"Nozzle health nominal (clog_prob={clog_prob:.2f}). Continue print."

    return {
        "clog_probability": round(clog_prob, 4),
        "predicted_clog_in": prediction,
        "action": action,
        "torch_metadata": {
            "backend": "pytorch" if _TORCH_AVAILABLE else "heuristic",
            "inference_latency_ms": round(latency_ms, 1),
            "seq_len_used": seq_len,
            "weights_loaded": (_WEIGHTS_DIR / "nozzle_lstm.pth").exists(),
        },
    }


@tool
def predict_texture_quality_from_uv_stats(
    mean_stretch: float,
    max_stretch: float,
    std_stretch: float,
    high_energy_frac: float,
    dirichlet_energy: float,
    n_faces: int,
    aspect_ratio: float = 1.0,
) -> dict:
    """
    Use a trained TextureQualityMLP to predict uniformity/seam/beauty scores
    from UV unwrap statistics, BEFORE running the full Blender render pass.
    Saves 2-3 minutes per iteration when confidence is high.

    Returns:
        predicted_uniformity : float 0-1
        predicted_seam       : float 0-1
        predicted_beauty     : float 0-1
        confidence           : "high" / "medium" / "low"
        skip_render_safe     : bool — True if confident enough to skip snapshot
        recommendation       : str
    """
    t0 = time.perf_counter()

    # Normalise inputs
    n_faces_norm = min(n_faces / 200_000.0, 1.0)
    feat = [
        mean_stretch,
        min(max_stretch / 50.0, 1.0),
        std_stretch,
        high_energy_frac,
        min(dirichlet_energy / 2.0, 1.0),
        n_faces_norm,
        min(aspect_ratio / 5.0, 1.0),
    ]

    if _TORCH_AVAILABLE:
        device = torch.device("cpu")
        x = torch.tensor([feat], dtype=torch.float32, device=device)
        model = _get_texture_mlp()
        if model is not None:
            with torch.no_grad():
                out = model(x).squeeze(0).cpu().tolist()
            u, s, b = out[0], out[1], out[2]
        else:
            u, s, b = _uv_heuristic(mean_stretch, high_energy_frac, dirichlet_energy)
    else:
        u, s, b = _uv_heuristic(mean_stretch, high_energy_frac, dirichlet_energy)

    latency_ms = (time.perf_counter() - t0) * 1000

    # Confidence: high if weights loaded, medium if heuristic
    weights_loaded = (_WEIGHTS_DIR / "texture_quality_mlp.pth").exists()
    confidence = "high" if weights_loaded else "medium"

    # Skip render if all three look good and confidence is high
    skip_render_safe = weights_loaded and u > 0.75 and s > 0.75 and b > 0.75

    recommendation = (
        f"Predicted: u={u:.2f} s={s:.2f} b={b:.2f} (confidence={confidence}). "
        + (
            "Skip snapshot — pre-flight scores look good."
            if skip_render_safe
            else "Run inspect_and_assess to confirm."
        )
    )

    return {
        "predicted_uniformity": round(u, 4),
        "predicted_seam": round(s, 4),
        "predicted_beauty": round(b, 4),
        "confidence": confidence,
        "skip_render_safe": skip_render_safe,
        "recommendation": recommendation,
        "torch_metadata": {
            "backend": "pytorch" if _TORCH_AVAILABLE else "heuristic",
            "inference_latency_ms": round(latency_ms, 1),
            "weights_loaded": weights_loaded,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# III.  Heuristic fallbacks (no PyTorch, no model weights)
# ═══════════════════════════════════════════════════════════════════════════════


def _geometry_stress_heuristic(vertices: list[list[float]]) -> list[float]:
    """Simple rule: vertices far from centroid get higher stress scores."""
    if not vertices:
        return []
    cx = sum(v[0] for v in vertices) / len(vertices)
    cy = sum(v[1] for v in vertices) / len(vertices)
    cz = sum(v[2] for v in vertices) / len(vertices)
    max_d = (
        max(
            (((v[0] - cx) ** 2 + (v[1] - cy) ** 2 + (v[2] - cz) ** 2) ** 0.5)
            for v in vertices
        )
        or 1.0
    )
    return [
        min(
            1.0, ((v[0] - cx) ** 2 + (v[1] - cy) ** 2 + (v[2] - cz) ** 2) ** 0.5 / max_d
        )
        for v in vertices
    ]


def _pressure_heuristic(pressure: list[float], temperature: list[float]) -> float:
    """Spike detection for pressure without LSTM."""
    if not pressure:
        return 0.0
    mean_p = sum(pressure) / len(pressure)
    spike_count = sum(1 for p in pressure[-8:] if p > mean_p * 1.5)
    drift_t = abs(temperature[-1] - temperature[0]) if len(temperature) > 1 else 0
    return min(1.0, spike_count / 8.0 + drift_t / 20.0)


def _uv_heuristic(
    mean_stretch: float, high_energy_frac: float, dirichlet_energy: float
) -> tuple[float, float, float]:
    """Rule-based texture quality estimation."""
    u = max(0.0, 1.0 - high_energy_frac * 0.8 - (mean_stretch - 1.0) * 0.3)
    s = max(0.0, 1.0 - dirichlet_energy * 0.4)
    b = (u + s) / 2.0
    return min(1.0, u), min(1.0, s), min(1.0, b)


# ═══════════════════════════════════════════════════════════════════════════════
# IV.  Training helpers — called by hardware_feedback.py after RLHF dataset built
# ═══════════════════════════════════════════════════════════════════════════════


def fine_tune_stress_gnn(jsonl_path: str, epochs: int = 20, lr: float = 1e-3) -> dict:
    """
    Fine-tune MeshStressGNN on a JSONL dataset exported from LangSmith failures.
    Dataset rows: {"vertices": [[x,y,z],...], "normals":[[nx,ny,nz],...], "label": float}

    Returns training summary dict. Call from hardware_feedback.py after dataset export.
    """
    if not _TORCH_AVAILABLE:
        return {"status": "skipped", "reason": "PyTorch not installed"}

    import json as _json

    rows = [
        _json.loads(l) for l in Path(jsonl_path).read_text().splitlines() if l.strip()
    ]
    if not rows:
        return {"status": "skipped", "reason": "empty dataset"}

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = _build_mesh_stress_gnn()
    if model is None:
        return {"status": "skipped", "reason": "model construction failed"}
    model = model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.BCELoss()

    losses = []
    model.train()
    for epoch in range(epochs):
        epoch_loss = 0.0
        for row in rows:
            verts = row["vertices"][:10_000]
            norms = (row.get("normals") or [[0, 0, 1]] * len(verts))[:10_000]
            feat = torch.tensor(
                [[*v, *n] for v, n in zip(verts, norms)],
                dtype=torch.float32,
                device=device,
            )
            label = torch.full(
                (len(verts), 1), row["label"], dtype=torch.float32, device=device
            )
            optimizer.zero_grad()
            pred = model(feat)
            loss = criterion(pred, label)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
        losses.append(epoch_loss / len(rows))

    # Save new weights
    out_path = _WEIGHTS_DIR / "mesh_stress_gnn.pth"
    torch.save(model.cpu().state_dict(), out_path)
    global _stress_gnn
    _stress_gnn = None  # force reload on next inference

    return {
        "status": "ok",
        "epochs": epochs,
        "final_loss": round(losses[-1], 6),
        "loss_curve": [round(v, 6) for v in losses],
        "saved_to": str(out_path),
    }


# ── Registry for manufacturing_graph.py ──────────────────────────────────────
ALL_TORCH_TOOLS = [
    evaluate_mesh_structural_integrity,
    analyze_nozzle_pressure,
    predict_texture_quality_from_uv_stats,
]
