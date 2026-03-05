# AI PhD-Level Problem Solving Framework: Meta-Cognition and Novelty Generation

A second-order treatment of AI problem-solving architecture, extending the foundational OODA framework with meta-cognitive monitoring, creativity models, and generative synthesis.

---

## I. Meta-Cognitive Monitoring

### 1.1 Confidence Calibration

An agent is well-calibrated if its stated confidence $\hat{p}$ matches the empirical accuracy $p$ over many predictions. The **Expected Calibration Error**:

$$\text{ECE} = \sum_{b=1}^{B} \frac{|B_b|}{n} \left| \text{acc}(B_b) - \text{conf}(B_b) \right|$$

where $B_b$ are confidence bins and $\text{acc}(B_b)$ is the fraction correct within each bin. A well-calibrated agent achieves $\text{ECE} < 0.05$.

### 1.2 Epistemic vs. Aleatoric Uncertainty

When an agent produces a low-confidence answer, it must distinguish:

- **Epistemic uncertainty**: reducible by acquiring more information (lack of knowledge)
- **Aleatoric uncertainty**: irreducible, inherent to the problem (inherent randomness)

The correct response to epistemic uncertainty is a tool call (search/read/compute); to aleatoric uncertainty it is a probability distribution over outcomes.

```python
from enum import Enum

class UncertaintyType(Enum):
    EPISTEMIC = "epistemic"   # → trigger information gathering
    ALEATORIC = "aleatoric"   # → report distribution, not point estimate
    CONFLATED = "conflated"   # → decompose further before resolving

def classify_uncertainty(claim: str, evidence: list[str]) -> UncertaintyType:
    """
    Heuristic: if no evidence exists yet → EPISTEMIC.
    If evidence conflicts → CONFLATED.
    If evidence is consistent but variance is intrinsic → ALEATORIC.
    """
    if not evidence:
        return UncertaintyType.EPISTEMIC
    contradictions = sum(1 for e in evidence if "not" in e or "however" in e)
    if contradictions > len(evidence) // 3:
        return UncertaintyType.CONFLATED
    return UncertaintyType.ALEATORIC
```

---

## II. Analogical Reasoning Engine

### 2.1 Structure Mapping Theory

Gentner's **Structure Mapping Theory** (1983) defines analogy as a structural alignment between a source domain $\mathcal{S}$ and target domain $\mathcal{T}$ preserving **relational structure**, not surface attributes:

$$\text{Analogy}(\mathcal{S}, \mathcal{T}) = \arg\max_{\psi: \mathcal{S} \to \mathcal{T}} \left[1 - d_{struct}(\mathcal{S}, \psi(\mathcal{T}))\right]$$

The alignment score $d_{struct}$ penalizes attribute mappings and rewards isomorphic relational mappings.

### 2.2 Implementation via Embedding Proximity

In practice, structural similarity is approximated via aligned embeddings:

```python
import numpy as np
from sentence_transformers import SentenceTransformer

EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")

def structural_analogy_score(
    src_relation: str,   # e.g., "heat flows from hot to cold"
    tgt_relation: str,   # e.g., "current flows from high to low potential"
) -> float:
    """Cosine similarity between relational descriptions (structural proxy)."""
    v1 = EMBEDDER.encode(src_relation)
    v2 = EMBEDDER.encode(tgt_relation)
    return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))
```

---

## III. Divergent-Convergent Generation Cycle

### 3.1 The D-C Framework

Creativity research (Guilford, 1967; Torrance, 1974) distinguishes:

- **Divergent phase**: generate many candidate solutions without evaluation
- **Convergent phase**: evaluate and synthesize the best elements

An AI problem-solving agent mimics this by:

1. Generating $N$ candidate approaches via temperature-shifted sampling ($T = 1.2$)
2. Scoring each with a deterministic validator ($T = 0.0$)
3. Synthesizing the Pareto-optimal set weighted by `quality × novelty`

```python
from dataclasses import dataclass

@dataclass
class Candidate:
    description: str
    quality_score: float      # 0–1, from validator
    novelty_score: float      # 0–1, distance from known prior solutions
    composite: float = 0.0

    def __post_init__(self):
        alpha = 0.7  # weight quality more than novelty
        self.composite = alpha * self.quality_score + (1 - alpha) * self.novelty_score

def select_synthesis_set(candidates: list[Candidate], k: int = 3) -> list[Candidate]:
    """Return k candidates maximising composite score with diversity constraint."""
    candidates.sort(key=lambda c: -c.composite)
    selected, selected_vecs = [], []
    for c in candidates:
        if len(selected) >= k:
            break
        # Simple diversity: reject if too similar to already-selected
        is_diverse = all(structural_analogy_score(c.description, s.description) < 0.85
                        for s in selected)
        if is_diverse:
            selected.append(c)
    return selected
```

---

## IV. Novel Contribution Criteria

A response achieves genuine novelty when it satisfies at least one of:

| Criterion | Description | Test |
|-----------|------------|------|
| Observation novelty | Identifies a fact not in training data | Perplexity $> P_{base}$ under held-out model |
| Structural novelty | Proposes a new relationship between known concepts | Analogy score $< 0.6$ to all known pairs |
| Methodological novelty | Introduces a technique not previously applied to this domain | No prior citation matching the combination |
| Predictive novelty | Makes a falsifiable prediction that existing literature does not | PFI $> 0.7$ and no prior prediction coverage |

---

## V. Grounding Constraint: Avoiding Hallucination

The agent must apply a **grounding gate** before committing any factual claim:

$$\text{Gate}(claim) = \begin{cases} \text{accept} & P(claim | \mathcal{KB}) \geq 0.7 \\ \text{tool-call} & 0.3 \leq P(claim | \mathcal{KB}) < 0.7 \\ \text{reject} & P(claim | \mathcal{KB}) < 0.3 \end{cases}$$

Tool calls (search, compute, file read) close the grounding loop before the claim is emitted.

---

## References

- Gentner, D. (1983). Structure-Mapping: A Theoretical Framework for Analogy. *Cognitive Science*, 7(2), 155–170.
- Guilford, J.P. (1967). *The Nature of Human Intelligence*. McGraw-Hill.
- Gao, T. et al. (2023). Measuring and Improving Calibration in Large Language Models. *arXiv:2212.09251*.
- Kendall, A. & Gal, Y. (2017). What Uncertainties Do We Need in Bayesian Deep Learning? *NeurIPS 2017*.
