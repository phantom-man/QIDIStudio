# AI-Powered Cyber-Physical Feedback Loop

A formal treatment of integrating PyTorch differentiable models with LangChain/LangGraph orchestration to form a closed-loop Cyber-Physical System (CPS) controller for manufacturing processes.

---

## I. Theoretical Foundations

### 1.1 Cyber-Physical Systems

A **Cyber-Physical System** couples a discrete computational controller $\mathcal{C}$ with a continuous physical plant $\mathcal{P}$:

$$\dot{\mathbf{x}} = f(\mathbf{x}, \mathbf{u}), \quad \mathbf{y} = g(\mathbf{x})$$
$$\mathbf{u}_{k+1} = \pi(\mathbf{y}_k, \theta)$$

where $\mathbf{x}$ is the plant state, $\mathbf{u}$ is the control input, $\mathbf{y}$ is the observed output, and $\pi(\cdot, \theta)$ is the AI controller parameterized by $\theta$.

### 1.2 LLM as Symbolic High-Level Controller

The LangChain/LangGraph agent acts as a **meta-controller** that:
1. Maintains a symbolic belief state over the process
2. Selects which PyTorch module to invoke
3. Interprets numerical outputs back into semantic decisions

The PyTorch modules act as **differentiable execution kernels** — producing both predictions and gradients for parameter adaptation.

---

## II. PyTorch Differentiable Plant Model

### 2.1 Neural ODE for Process Dynamics

A neural ODE models the continuous plant dynamics:

```python
import torch
import torch.nn as nn
from torchdiffeq import odeint_adjoint as odeint

class PlantDynamicsNet(nn.Module):
    """Neural ODE approximating FDM extrusion state dynamics."""
    def __init__(self, state_dim: int = 6, control_dim: int = 4, hidden: int = 64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim + control_dim, hidden),
            nn.Tanh(),
            nn.Linear(hidden, hidden),
            nn.Tanh(),
            nn.Linear(hidden, state_dim),
        )

    def forward(self, t: torch.Tensor, x: torch.Tensor) -> torch.Tensor:
        # Control is passed as extra dimensions via closure
        return self.net(x)

class PlantSimulator:
    def __init__(self, model: PlantDynamicsNet):
        self.model = model

    def rollout(
        self,
        x0: torch.Tensor,      # (state_dim,) initial state
        u: torch.Tensor,       # (T, control_dim) control sequence
        t_span: torch.Tensor,  # (T,) time points
    ) -> torch.Tensor:
        """Simulate plant for T steps. Returns (T, state_dim) state trajectory."""
        def dynamics(t, x):
            k = int((t / t_span[-1]) * (len(u) - 1))
            xu = torch.cat([x, u[k]])
            return self.model.net(xu)
        return odeint(dynamics, x0, t_span, method="dopri5")
```

---

## III. LangGraph Orchestration

### 3.1 CPS Agent Graph

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class CPSState(TypedDict):
    step: int
    plant_state: list[float]
    sensor_reading: dict
    control_action: dict
    llm_verdict: str

def sense(state: CPSState) -> CPSState:
    """Read physical sensor (camera, encoder, thermocouple)."""
    # ... hardware read ...
    return state

def llm_plan(state: CPSState) -> CPSState:
    """LLM meta-controller: interprets sensor reading, selects action category."""
    # LangChain call
    return state

def pytorch_compute(state: CPSState) -> CPSState:
    """PyTorch kernel: compute optimal control from current state."""
    return state

def actuate(state: CPSState) -> CPSState:
    """Write control commands to physical actuator."""
    return state

def should_continue(state: CPSState) -> str:
    return "continue" if state["step"] < 100 else END

builder = StateGraph(CPSState)
builder.add_node("sense", sense)
builder.add_node("llm_plan", llm_plan)
builder.add_node("pytorch_compute", pytorch_compute)
builder.add_node("actuate", actuate)
builder.set_entry_point("sense")
builder.add_edge("sense", "llm_plan")
builder.add_edge("llm_plan", "pytorch_compute")
builder.add_edge("pytorch_compute", "actuate")
builder.add_conditional_edges("actuate", should_continue, {"continue": "sense", END: END})
graph = builder.compile()
```

---

## IV. Differentiable Policy Optimization

### 4.1 Policy Gradient via Adjoint Method

The LangGraph loop generates a trajectory $\tau = (\mathbf{x}_0, \mathbf{u}_0, \dots, \mathbf{x}_T)$. The total cost:

$$J(\theta) = \sum_{t=0}^{T} c(\mathbf{x}_t, \mathbf{u}_t)$$

The **adjoint method** (Pontryagin) computes $\nabla_\theta J$ without backpropagating through the entire trajectory:

$$\frac{dJ}{d\theta} = -\int_0^T \lambda^T(t) \frac{\partial f}{\partial \theta} dt$$

where $\lambda(t)$ satisfies the co-state equation $\dot{\lambda} = -(\partial f/\partial \mathbf{x})^T \lambda - \partial c/\partial \mathbf{x}$.

```python
def online_policy_update(
    simulator: PlantSimulator,
    policy: nn.Module,
    x0: torch.Tensor,
    optimizer: torch.optim.Optimizer,
    T: int = 20,
) -> float:
    t_span = torch.linspace(0, T, T + 1)
    u = policy(x0.unsqueeze(0).expand(T, -1))
    traj = simulator.rollout(x0, u, t_span)
    # Quadratic cost: keep state near zero, minimize control effort
    cost = (traj ** 2).mean() + 0.01 * (u ** 2).mean()
    optimizer.zero_grad()
    cost.backward()
    optimizer.step()
    return float(cost)
```

---

## V. Integration Checklist

| Step | Tool | Purpose |
|------|------|---------|
| Process monitoring | `cv2` + camera | Real-time state observation |
| State encoding | `torch.Tensor` (6D) | Numerical state for neural inference |
| High-level decision | LangGraph + LLM | Semantic action selection |
| Low-level control | PyTorch neural ODE | Differentiable control computation |
| Actuator write | `moonraker_api` / Klipper | Physical command execution |
| Policy adaptation | `torchdiffeq` adjoint | Online parameter update |

---

## References

- Lee, E.A. (2008). Cyber Physical Systems: Design Challenges. *ISORC 2008*.
- Chen, R.T.Q. et al. (2018). Neural Ordinary Differential Equations. *NeurIPS 2018*.
- Pontryagin, L.S. et al. (1962). *The Mathematical Theory of Optimal Processes*. Interscience.
- LangGraph Documentation. (2024). Building stateful multi-actor applications. LangChain.com.
