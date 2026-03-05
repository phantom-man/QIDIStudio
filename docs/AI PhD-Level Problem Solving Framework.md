# AI PhD-Level Problem Solving Framework

A formal cognitive architecture for AI-assisted doctoral-level problem solving — combining structured decomposition, uncertainty-aware reasoning, and multi-hypothesis synthesis to replace stochastic response generation with grounded inference.

---

## I. Theoretical Foundations

### 1.1 From Pattern Matching to Structural Reasoning

Standard LLM inference approximates $P(w_{t+1}|w_{1:t})$ — a conditional distribution over next tokens. This captures surface regularities but lacks:

- **Causal closure**: the ability to distinguish correlation from mechanism
- **Model-based search**: constructing and evaluating hypotheses in a structured world model
- **Epistemic humility**: tracking uncertainty over problem states

A PhD-level problem-solving agent replaces raw token prediction with structured inference over a belief state $b_t = P(s | o_{1:t}, a_{1:t})$.

### 1.2 OODA Loop as Agentic Substrate

The **Observe–Orient–Decide–Act** cycle maps directly to agent orchestration:

$$\text{Observe} \to \text{Orient} \to \text{Decide} \to \text{Act}$$

| Phase | Cognitive Operation | Agent Capability |
|-------|-------------------|-----------------|
| Observe | Gather evidence $o_t$ | Tool calls (search, read, compute) |
| Orient | Update belief $b_t$ | Bayesian revision + memory retrieval |
| Decide | Select action $a^*$ | Utility maximization under uncertainty |
| Act | Execute + monitor | Sub-agent dispatch + metric validation |

---

## II. Problem Decomposition Protocol

### 2.1 Axiomatic Decomposition

Every non-trivial problem $P$ is decomposed into a directed acyclic graph (DAG) of sub-problems:

$$P \to \{P_1, P_2, \dots, P_n\}$$

such that:
1. $\forall i: P_i \subset P$ (sub-problem is strictly smaller)
2. $\bigcup P_i = P$ (completeness)
3. $P_i \cap P_j = \varnothing$ for $i \neq j$ (minimal overlap)
4. Each $P_i$ is **independently falsifiable**

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class SubProblem:
    description: str
    dependencies: list[str] = field(default_factory=list)
    resolved: bool = False
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0

class ProblemDAG:
    def __init__(self, root: str):
        self.root = root
        self.nodes: dict[str, SubProblem] = {root: SubProblem(root)}

    def add(self, parent: str, child: str) -> None:
        self.nodes[child] = SubProblem(child, dependencies=[parent])

    def next_unresolved(self) -> Optional[str]:
        """Return the highest-priority unresolved node with all deps met."""
        candidates = [
            k for k, v in self.nodes.items()
            if not v.resolved
            and all(self.nodes[d].resolved for d in v.dependencies)
        ]
        return candidates[0] if candidates else None

    def resolve(self, name: str, confidence: float, evidence: list[str]) -> None:
        self.nodes[name].resolved = True
        self.nodes[name].confidence = confidence
        self.nodes[name].evidence = evidence
```

---

## III. Hypothesis Management

### 3.1 Multi-Hypothesis Tracking

Rather than committing to a single explanation, the agent maintains a **hypothesis set** $\mathcal{H} = \{H_1, H_2, \dots, H_k\}$ with Bayesian posterior:

$$P(H_i | e) = \frac{P(e | H_i) P(H_i)}{\sum_j P(e | H_j) P(H_j)}$$

Hypotheses are pruned when $P(H_i | e) < \epsilon_{min} = 0.05$.

### 3.2 Evidence Integration

Each piece of evidence $e_j$ updates all hypothesis posteriors. The **likelihood** $P(e_j | H_i)$ is estimated by querying a tool (code execution, search, file read) and comparing the observed outcome to the prediction made by $H_i$:

```python
import math

class HypothesisTracker:
    def __init__(self):
        self.hypotheses: dict[str, float] = {}  # hypothesis -> log-prob

    def add(self, label: str, prior: float = 0.5):
        self.hypotheses[label] = math.log(prior)

    def update(self, likelihoods: dict[str, float]):
        """likelihoods: {hypothesis_label: P(evidence | H)}"""
        for h, log_p in self.hypotheses.items():
            self.hypotheses[h] = log_p + math.log(likelihoods.get(h, 1e-9))
        self._normalize()

    def _normalize(self):
        max_log = max(self.hypotheses.values())
        total = sum(math.exp(v - max_log) for v in self.hypotheses.values())
        log_z = max_log + math.log(total)
        self.hypotheses = {k: v - log_z for k, v in self.hypotheses.items()}

    def top(self, n: int = 3) -> list[tuple[str, float]]:
        return sorted(
            [(k, math.exp(v)) for k, v in self.hypotheses.items()],
            key=lambda x: -x[1]
        )[:n]
```

---

## IV. Graduated Reasoning Levels

| Level | Description | Method |
|-------|------------|--------|
| L0 | Recall | Direct LLM completion from training data |
| L1 | Retrieval-augmented | RAG over LanceDB knowledge base |
| L2 | Deductive | Symbolic rule application from first principles |
| L3 | Abductive | Best-explanation inference over hypothesis set |
| L4 | Experimental | Tool execution → observation → belief update |
| L5 | Creative synthesis | Cross-domain analogy + novel architecture |

A problem is escalated to the next level when the current level returns confidence $< 0.7$.

---

## V. Output Quality Criteria

A PhD-level answer $A$ must satisfy:

1. **Claim precision**: every claim is quantified or formally stated, not vague
2. **Evidential support**: each non-trivial claim cites a source or a computation result
3. **Scope acknowledgment**: limitations and open questions are explicitly listed
4. **Reproducibility**: code examples are self-contained, typed, and runnable
5. **Novelty**: at least one non-obvious insight that advances beyond existing documentation

---

## References

- Peirce, C.S. (1931). *Collected Papers*, Vol. 2, §135–141 (abductive inference).
- Boyd, J. (1986). Patterns of Conflict. USAF unpublished briefing (OODA loop).
- Kahneman, D. (2011). *Thinking, Fast and Slow*. Farrar, Straus and Giroux.
- Russell, S. & Norvig, P. (2020). *Artificial Intelligence: A Modern Approach*, 4th ed. §13 (Bayesian networks) and §5 (adversarial search).
