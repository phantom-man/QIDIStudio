# AI PhD Knowledge Acquisition Pipeline

A formal treatment of autonomous research agent architecture for perpetual cross-domain knowledge synthesis — combining Recursive Self-Improvement (RSI), meta-cognitive feedback, and multi-agent dialectics.

---

## I. Theoretical Foundations

### 1.1 Meta-Learning and Recursive Self-Improvement

Classical knowledge acquisition treats an agent as a static function $f: Q \to A$ mapping queries to answers. A PhD-level pipeline instead models the agent as a *meta-learner* that continuously updates its own prior:

$$\theta_{t+1} = \theta_t - \eta \nabla_\theta \mathcal{L}(\theta_t, \mathcal{D}_t)$$

where $\mathcal{D}_t$ is a dynamic corpus assembled by the agent itself, and $\mathcal{L}$ includes a **novelty penalty** that rewards exploration of underrepresented knowledge edges.

### 1.2 Dialectical Synthesis Loop

Inspired by Hegelian dialectics: thesis → antithesis → synthesis. In practice this maps to:

| Step | Agent Role | Output |
|------|-----------|--------|
| Thesis | `researcher` — asserts current best model | Structured claim $C_i$ |
| Antithesis | `verifier` — finds counter-evidence | Falsification set $\neg C_i$ |
| Synthesis | `builder` — reconciles contradiction | Refined model $C_i'$ |
| Persistence | `scribe` — commits to LanceDB | Embedded vector row |

The cycle runs until $|C_i' \oplus C_i| < \epsilon$ (information-theoretic convergence).

---

## II. Pipeline Architecture

### 2.1 Hierarchical Knowledge Graph

Knowledge is stored as a hypergraph $\mathcal{G} = (V, E, W)$ where:
- $V$ — concept nodes (embedded via `sentence-transformers/all-MiniLM-L6-v2`)
- $E$ — directed typed edges: `supports`, `contradicts`, `generalizes`, `instantiates`
- $W: E \to [0,1]$ — evidence weights updated by Bayesian rule

```python
from lancedb import connect
import numpy as np
from sentence_transformers import SentenceTransformer

class KnowledgeGraph:
    def __init__(self, uri: str):
        self.db = connect(uri)
        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
        self._ensure_tables()

    def _ensure_tables(self):
        if "nodes" not in self.db.table_names():
            import pyarrow as pa
            schema = pa.schema([
                pa.field("id", pa.string()),
                pa.field("concept", pa.string()),
                pa.field("domain", pa.string()),
                pa.field("confidence", pa.float32()),
                pa.field("vector", pa.list_(pa.float32(), 384)),
            ])
            self.db.create_table("nodes", schema=schema)

    def upsert(self, concept: str, domain: str, confidence: float = 1.0):
        vec = self.embedder.encode(concept).tolist()
        row = {"id": concept[:64], "concept": concept,
               "domain": domain, "confidence": confidence, "vector": vec}
        tbl = self.db.open_table("nodes")
        tbl.add([row], mode="overwrite")  # upsert by id

    def nearest(self, query: str, k: int = 5) -> list[dict]:
        vec = self.embedder.encode(query).tolist()
        return self.db.open_table("nodes").search(vec).limit(k).to_list()
```

### 2.2 Hypothesis Generation Module

The agent generates falsifiable hypotheses via structured prompting:

```python
HYPOTHESIS_PROMPT = """\
Given the following knowledge fragment:
{fragment}

Generate three falsifiable hypotheses in the form:
H1: IF <condition> THEN <prediction> BECAUSE <mechanism>
H2: ...
H3: ...

Each hypothesis must name at least one measurable observable."""
```

Hypotheses are scored by **Popper Falsifiability Index**:

$$\text{PFI}(H) = \frac{|\text{falsifiable observations}(H)|}{|\text{total entailed observations}(H)|}$$

Hypotheses with $\text{PFI} < 0.3$ are discarded as unfalsifiable.

---

## III. Active Learning and Curriculum Scheduling

### 3.1 Uncertainty Sampling

At each cycle, the agent selects the next concept to study via maximum marginal relevance:

$$c^* = \arg\max_{c \in \mathcal{C}} \left[ \lambda \cdot \text{Uncertainty}(c) - (1-\lambda) \cdot \max_{c' \in S} \text{Sim}(c, c') \right]$$

where $S$ is the set already in the current session context and $\text{Uncertainty}(c) = 1 - \text{confidence}(c)$.

### 3.2 Cross-Domain Transfer

Transfer is modeled as an **analogy mapping** between source domain $\mathcal{D}_s$ and target domain $\mathcal{D}_t$:

```python
def find_structural_analogies(
    source_concept: str,
    target_domain: str,
    kg: KnowledgeGraph,
    top_k: int = 3,
) -> list[tuple[str, float]]:
    """Return (target_concept, similarity) pairs via cross-domain embedding search."""
    src_vec = kg.embedder.encode(source_concept)
    candidates = kg.nearest(f"{target_domain}: {source_concept}", k=20)
    results = []
    for row in candidates:
        if row["domain"] == target_domain:
            tgt_vec = np.array(row["vector"])
            cos_sim = float(np.dot(src_vec, tgt_vec) /
                           (np.linalg.norm(src_vec) * np.linalg.norm(tgt_vec)))
            results.append((row["concept"], cos_sim))
    return sorted(results, key=lambda x: -x[1])[:top_k]
```

---

## IV. Convergence Criteria and Evaluation

### 4.1 Knowledge Coverage Score

$$\text{KCS} = 1 - \frac{H(\mathcal{G}_t)}{H_{\max}}$$

where $H(\mathcal{G}_t)$ is the Shannon entropy of the domain-concept distribution at time step $t$. A well-saturated knowledge base has $\text{KCS} \geq 0.85$.

### 4.2 Calibration Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| Epistemic Calibration | $\text{ECE} = \mathbb{E}[|p - \hat{p}|]$ | $< 0.05$ |
| Novelty Rate | new concepts per cycle / total per cycle | $> 0.15$ |
| Contradiction Rate | contradicted claims / total asserted | $< 0.08$ |
| Synthesis Latency | cycles to $C_i' \approx C_i$ | $\leq 3$ |

---

## V. Implementation Notes for QIDIStudio

The LangGraph scribe agent persists synthesis outputs to `gs://qidistudio-lancedb/lancedb`, table `qidistudio_learnings`. The 30-minute `sync_prompts_to_lancedb.py` job pushes new rows automatically.

Re-index command:
```bash
memory_env/Scripts/python.exe memory/extract.py
```

---

## References

- Lake, B.M. et al. (2017). Building machines that learn and think like people. *Behavioral and Brain Sciences*, 40, e253.
- Schmidhuber, J. (2010). Formal Theory of Creativity, Fun, and Intrinsic Motivation. *IEEE Trans. Autonomous Mental Development*, 2(3).
- Settles, B. (2009). Active Learning Literature Survey. *Computer Sciences TR 1648*, University of Wisconsin–Madison.
- Shannon, C.E. (1948). A mathematical theory of communication. *Bell System Technical Journal*, 27(3), 379–423.
