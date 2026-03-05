# Directing Large Language Models: Advanced Prompting and Control Techniques

Systematic techniques for steering LLM behavior — covering chain-of-thought elicitation, structured output enforcement, tool-use orchestration, grounding strategies, and sampling parameter control — grounded in mechanistic understanding of transformer generation dynamics.

---

## I. Prompting Paradigms

### 1.1 Zero-Shot vs Few-Shot

Zero-shot prompting relies on the model's pretrained capabilities:

```
Extract all email addresses from the text.  Return as JSON list.
Text: "Contact alice@acme.com or bob@corp.io for details."
```

Few-shot prompting provides input-output demonstrations in-context:

```
Text: "Email admin@site.org"  → ["admin@site.org"]
Text: "No emails here."       → []
Text: "Contact us at x@y.com" → ???
```

Few-shot improves accuracy on rare formats by ~30–60% over zero-shot (Brown et al., 2020).

### 1.2 Chain-of-Thought (CoT)

CoT elicits step-by-step reasoning by adding "Let's think step by step" or explicit scaffolding:

```
Q: A factory runs 3 machines, each making 40 parts/hour. 
   Shift duration is 8 hours but 1 machine breaks after 3 hours.
   Total parts produced?

A: Let's reason:
   - Machine 1, 2: run full 8 h × 40 = 320 parts each → 640
   - Machine 3: runs 3 h × 40 = 120 parts
   - Total: 640 + 120 = 760 parts
```

CoT performance on GSM8K: 17% (standard) → 78% (CoT) for GPT-3-175B (Wei et al., 2022).

---

## II. Structured Output Enforcement

### 2.1 JSON Schema Forcing

Modern APIs (OpenAI, Anthropic) support constrained decoding via JSON schema:

```python
import anthropic, json

client = anthropic.Anthropic()

SCHEMA = {
    "type": "object",
    "properties": {
        "shape_type": {"type": "string", "enum": ["PLANAR","CYLINDRICAL","FREEFORM"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string"},
    },
    "required": ["shape_type", "confidence", "reasoning"],
}

def classify_shape_with_llm(description: str) -> dict:
    """Use Claude to classify a shape description into typed output."""
    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": f"Classify this 3D shape: {description}\n\nRespond with JSON matching the schema: {json.dumps(SCHEMA)}",
        }],
    )
    text = msg.content[0].text
    # Extract JSON from response
    import re
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group(0))
```

---

## III. ReAct: Reasoning + Acting

ReAct interleaves reasoning traces and tool calls:

```
Thought: I need to check the nozzle wear formula.
Action: lookup_formula("Archard wear model")
Observation: V_w = K * F_n * s / H

Thought: With K=1e-3, F=20N, s=1000mm, H=90HV, wear = 1e-3*20*1000/90 = 0.22 mm³
Action: compute(1e-3 * 20 * 1000 / 90)
Observation: 0.2222

Thought: 0.22 mm³ wear per kg filament for brass. Report this.
Answer: Brass nozzle wears approximately 0.22 mm³ per kg of abrasive filament.
```

Implementation pattern:

```python
from dataclasses import dataclass
from typing import Callable

@dataclass
class Tool:
    name: str
    description: str
    func: Callable[[str], str]

def react_loop(
    query: str,
    tools: list[Tool],
    llm_call: Callable[[str], str],
    max_steps: int = 8,
) -> str:
    """Run ReAct reasoning loop."""
    tool_map = {t.name: t for t in tools}
    context = f"Question: {query}\n\nAvailable tools: {[t.name for t in tools]}\n\n"

    for _ in range(max_steps):
        response = llm_call(context + "Thought:")
        if "Answer:" in response:
            return response.split("Answer:")[-1].strip()
        # Parse Action/Observation
        if "Action:" in response:
            action_line = [l for l in response.splitlines() if "Action:" in l][0]
            tool_name, arg = action_line.replace("Action:", "").strip().split("(", 1)
            arg = arg.rstrip(")")
            tool = tool_map.get(tool_name.strip())
            obs = tool.func(arg) if tool else f"Tool {tool_name} not found"
            context += response + f"\nObservation: {obs}\n"
        else:
            break
    return "Max steps reached without answer."
```

---

## IV. Sampling Parameter Control

| Parameter | Effect | Typical range |
|-----------|--------|--------------|
| `temperature` | Sharpness of token distribution | 0 (greedy) – 2.0 |
| `top_p` | Nucleus sampling cutoff | 0.5 – 1.0 |
| `top_k` | Limit to k most likely | 1 – 100 |
| `frequency_penalty` | Penalize repetition | 0.0 – 2.0 |
| `max_tokens` | Hard output length limit | 64 – 32768 |

For deterministic structured outputs: `temperature=0.0, top_p=1.0`.  
For creative generation: `temperature=0.7–1.0, top_p=0.95`.

---

## References

- Brown, T. et al. (2020). Language models are few-shot learners. *NeurIPS* 33.
- Wei, J. et al. (2022). Chain-of-thought prompting elicits reasoning. *NeurIPS* 35.
- Yao, S. et al. (2022). ReAct: Synergizing reasoning and acting in language models. *ICLR 2023*.
- Ouyang, L. et al. (2022). Training language models to follow instructions with RLHF. *NeurIPS* 35.
