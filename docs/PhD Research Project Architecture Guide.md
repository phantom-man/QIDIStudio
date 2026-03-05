# PhD Research Project Architecture Guide

A structural blueprint for organizing long-horizon AI-augmented research projects — covering knowledge graph architecture, agent coordination patterns, experiment tracking, and reproducibility infrastructure.

---

## I. Research Project Architecture

### 1.1 Directory Structure

A well-structured research project separates concerns across six layers:

```
project/
├── docs/           # Knowledge base (markdown, spec)
├── src/            # Core library code
│   ├── models/     # ML/physics models
│   ├── data/       # Dataset loaders, preprocessing
│   └── eval/       # Evaluation metrics
├── scripts/        # Experiment drivers, one-off analyses
├── tests/          # Unit + integration tests
├── notebooks/      # EDA, result visualization (READ-ONLY results)
├── agents/         # AI agent orchestration
│   ├── orchestrator.py
│   ├── dev_fleet.py
│   └── memory/     # LanceDB + PostgreSQL persistence
├── configs/        # YAML experiment configs (Hydra)
└── results/        # Versioned output (DVC-tracked)
```

### 1.2 Reproducibility Stack

| Layer | Tool | Role |
|-------|------|------|
| Code versioning | Git | Source control |
| Data versioning | DVC | Dataset + model artifact tracking |
| Experiment tracking | MLflow / W&B | Metrics, hyperparameters, runs |
| Environment | Docker + conda-lock | Exact dep pinning |
| Config management | Hydra | Hierarchical config + sweeps |
| Knowledge base | LanceDB | Vectorized doc store |
| Agent memory | PostgreSQL | Prompt/response history |

---

## II. Experiment Configuration (Hydra)

```yaml
# configs/experiment/base.yaml
defaults:
  - model: neural_sdf
  - dataset: shapenet_chairs
  - optimizer: adam

training:
  lr: 5.0e-4
  batch_size: 32
  max_epochs: 500
  grad_clip: 1.0

model:
  hidden_dim: 256
  n_layers: 8
  skip_connection_at: [4]

dataset:
  root: ${oc.env:DATA_ROOT}/shapenet
  n_views: 24
  resolution: 128
  augment: true
```

```python
import hydra
from omegaconf import DictConfig

@hydra.main(config_path="../configs", config_name="experiment/base", version_base="1.3")
def train(cfg: DictConfig) -> float:
    """Main training entry point with full reproducibility."""
    import mlflow

    with mlflow.start_run():
        mlflow.log_params(dict(cfg.training))
        model = hydra.utils.instantiate(cfg.model)
        # ... training loop ...
        val_loss = run_training(model, cfg)
        mlflow.log_metric("val_loss", val_loss)
    return val_loss
```

---

## III. Knowledge Graph Architecture

### 3.1 LanceDB Schema

```python
import lancedb
import pyarrow as pa

def create_knowledge_table(db_uri: str) -> lancedb.table.Table:
    """Create typed knowledge base table."""
    db = lancedb.connect(db_uri)
    schema = pa.schema([
        pa.field("id", pa.string()),
        pa.field("topic", pa.string()),
        pa.field("content", pa.string()),
        pa.field("source", pa.string()),
        pa.field("confidence", pa.float32()),
        pa.field("created_at", pa.timestamp("us")),
        pa.field("tags", pa.list_(pa.string())),
        pa.field("vector", pa.list_(pa.float32(), 384)),
    ])
    return db.create_table("knowledge", schema=schema, exist_ok=True)
```

### 3.2 Semantic Retrieval Pipeline

```python
from sentence_transformers import SentenceTransformer

MODEL = SentenceTransformer("all-MiniLM-L6-v2")

def retrieve(
    table: lancedb.table.Table,
    query: str,
    top_k: int = 8,
    topic_filter: str | None = None,
) -> list[dict]:
    """Semantic search with optional topic pre-filter."""
    q_emb = MODEL.encode(query).tolist()
    q = table.search(q_emb).limit(top_k)
    if topic_filter:
        q = q.where(f"topic = '{topic_filter}'")
    return q.to_list()
```

---

## IV. Agent Coordination Pattern

### 4.1 Director–Worker Pattern

Research tasks are decomposed by a director LLM (Gemini 2.5 Flash) into typed `AgentTask` objects and dispatched to specialized workers:

```python
from enum import Enum
from dataclasses import dataclass
from typing import Any

class AgentRole(Enum):
    RESEARCHER = "researcher"     # Web search, doc reading
    BUILDER    = "builder"        # Code writing, implementation
    VERIFIER   = "verifier"       # Code review, fact-check
    SCRIBE     = "scribe"         # Knowledge base persistence

@dataclass
class AgentTask:
    role: AgentRole
    prompt: str
    context: dict[str, Any]
    priority: int = 1
    max_tokens: int = 8192
```

### 4.2 Task Routing Strategy

Tasks are routed based on:
- `researcher`: requires `web_search` tool or has `needs_citation=True`
- `builder`: has explicit file path targets or code output requirements
- `verifier`: references an existing code artifact for review
- `scribe`: has `persist=True` and a structured fact payload

---

## V. Research Quality Gate

Before any finding is persisted to the knowledge base, it passes a 4-stage gate:

| Gate | Check | Tool |
|------|-------|------|
| Accuracy | Cross-source verification | `researcher` agent |
| Completeness | Required fields present | Schema validation |
| Novelty | Embedding distance > 0.15 | LanceDB similarity |
| Reproducibility | Code runs without error | `verifier` agent |

---

## References

- Sculley, D. et al. (2015). Hidden Technical Debt in Machine Learning Systems. *NeurIPS 2015*.
- Amershi, S. et al. (2019). Software Engineering for Machine Learning. *ICSE-SEIP 2019*.
- Sievert, C. (2020). *Interactive Web-Based Data Visualization with R, Plotly, and Shiny*. CRC Press.
- Mitchell, M. et al. (2019). Model Cards for Model Reporting. *FAccT 2019*.
