# AI-Driven Visual Debugging Orchestration

A formal architecture for AI-orchestrated automated visual debugging of 3D geometry pipelines — combining formal verification principles, cyber-physical control loops, and multi-modal LLM inspection.

---

## I. Control-Theoretic Architecture

### 1.1 The Debugging Agent as PID Controller

The AI agent acts as a discrete-time controller in a feedback loop over the rendering pipeline:

$$e_t = \mathbf{s}_{ref} - \mathbf{s}_t$$
$$\mathbf{u}_t = K_P e_t + K_I \sum_{k=0}^{t} e_k + K_D (e_t - e_{t-1})$$

where $\mathbf{s}_t$ is the current pipeline state (metric vector), $\mathbf{u}_t$ is the corrective action, and the PID gains are meta-learned across sessions.

In practice $K_I$ and $K_D$ are often zero for discrete repair cycles, reducing to proportional control with per-action cost estimation.

### 1.2 State Representation

The pipeline state $\mathbf{s}_t \in \mathbb{R}^6$ encodes:

| Index | Metric | Range | Threshold |
|-------|--------|-------|---------|
| 0 | Mean stretch $\bar{E}_D$ | $[1, \infty)$ | $< 2.0$ |
| 1 | Max stretch $E_{D,\max}$ | $[1, \infty)$ | $< 5.0$ |
| 2 | Seam normal jump $E_N$ | $[0, 2]$ | $< 0.1$ |
| 3 | Texel density CV | $[0, 1]$ | $< 0.3$ |
| 4 | Winding error count | $[0, F]$ | $= 0$ |
| 5 | Island margin (px) | $[0, 64]$ | $\geq 4$ |

---

## II. Symbolic Breakpoint Injection

### 2.1 Pipeline Instrumentation

Each stage of the pipeline is wrapped with a breakpoint emitter:

```python
from contextlib import contextmanager
from typing import Generator
import trimesh

class PipelineInspector:
    def __init__(self, ai_critic):
        self.critic = ai_critic
        self.history: list[dict] = []

    @contextmanager
    def stage(self, name: str, mesh: trimesh.Trimesh) -> Generator:
        yield mesh  # caller mutates mesh inside context
        metrics = self._measure(mesh)
        snapshot = self._capture(mesh)
        verdict = self.critic(name, metrics, snapshot)
        self.history.append({"stage": name, "metrics": metrics, "verdict": verdict})
        if verdict["severity"] == "high":
            raise PipelineHalt(f"Stage {name!r} emitted critical error: {verdict}")

    def _measure(self, mesh: trimesh.Trimesh) -> dict:
        from scripts.apply_texture_bpy import compute_uv_metrics
        return compute_uv_metrics(mesh)

    def _capture(self, mesh: trimesh.Trimesh) -> str:
        import base64, io
        scene = mesh.scene()
        png = scene.save_image(resolution=(512, 512))
        return base64.b64encode(png).decode()
```

---

## III. Multi-Modal LLM Inspector

### 3.1 Structured Inspection Protocol

The AI critic receives: (a) the render snapshot, (b) the metric vector, (c) the stage name. It returns a structured JSON verdict:

```python
import json
import anthropic

SYSTEM = """\
You are an expert 3D geometry debugging agent.
Given a render snapshot and pipeline metrics, classify the primary error class and prescribe a
concrete repair action. Respond ONLY with valid JSON matching the schema:
{"error_class": "G1|G2|G3|G4|NONE",
 "severity": "low|medium|high",
 "repair_call": "<Python function call string>",
 "confidence": <0.0-1.0>}"""

def inspect_stage(
    stage: str,
    metrics: dict,
    snapshot_b64: str,
    client: anthropic.Anthropic,
) -> dict:
    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=256,
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/png", "data": snapshot_b64}},
                {"type": "text", "text": f"Stage: {stage}\nMetrics: {json.dumps(metrics)}"},
            ],
        }],
    )
    return json.loads(msg.content[0].text)
```

---

## IV. Formal Verification Layer

### 4.1 Invariant Assertions

Each pipeline stage has formally specified invariants checked post-mutation:

```python
from typing import NamedTuple

class StageInvariant(NamedTuple):
    metric: str
    op: str         # "<", "<=", "==", ">=", ">"
    threshold: float

STAGE_INVARIANTS: dict[str, list[StageInvariant]] = {
    "unwrap": [
        StageInvariant("mean_E_D", "<", 2.5),
        StageInvariant("winding_errors", "==", 0.0),
    ],
    "pack": [
        StageInvariant("texel_density_CV", "<", 0.3),
        StageInvariant("island_margin_px", ">=", 4.0),
    ],
    "export": [
        StageInvariant("mean_E_D", "<", 2.0),
        StageInvariant("seam_E_N", "<", 0.1),
    ],
}

def verify_invariants(stage: str, metrics: dict) -> list[str]:
    """Return list of violated invariant descriptions."""
    violations = []
    for inv in STAGE_INVARIANTS.get(stage, []):
        v = metrics.get(inv.metric, 0.0)
        ops = {"<": v < inv.threshold, "<=": v <= inv.threshold,
               "==": v == inv.threshold, ">=": v >= inv.threshold, ">": v > inv.threshold}
        if not ops[inv.op]:
            violations.append(f"{inv.metric} {inv.op} {inv.threshold} (got {v:.4f})")
    return violations
```

---

## V. Orchestration Loop

```python
def orchestrated_debug_run(
    mesh: trimesh.Trimesh,
    pipeline_stages: list[tuple[str, callable]],
    critic,
    max_retries: int = 3,
) -> trimesh.Trimesh:
    inspector = PipelineInspector(critic)
    for stage_name, stage_fn in pipeline_stages:
        for attempt in range(max_retries):
            with inspector.stage(stage_name, mesh):
                mesh = stage_fn(mesh)
            violations = verify_invariants(stage_name, inspector.history[-1]["metrics"])
            if not violations:
                break
            repair = inspector.history[-1]["verdict"].get("repair_call", "")
            if repair:
                eval(repair, {"mesh": mesh})  # execute repair in mesh scope
    return mesh
```

---

## References

- Seshia, S.A. et al. (2018). Formal Specification for Deep Neural Networks. *ATVA 2018.*
- Doyle, J.C., Francis, B.A. & Tannenbaum, A.R. (1992). *Feedback Control Theory*. Macmillan.
- Anthropic. (2024). Claude Model Card. Anthropic.com.
- Sorkine, O. & Alexa, M. (2007). As-Rigid-As-Possible Surface Modeling. *SGP 2007*.
