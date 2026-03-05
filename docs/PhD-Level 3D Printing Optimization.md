# PhD-Level 3D Printing Process Optimization

Principled optimization of FDM printing parameters using polymer physics, Bayesian experimental design, and multi-objective control theory — targeting dimensional accuracy, mechanical isotropy, and surface finish simultaneously.

---

## I. Process Parameter Space

The FDM parameter space $\Theta$ is high-dimensional. The primary parameters and their physical roles:

| Parameter | Symbol | Range | Physical Effect |
|-----------|--------|-------|----------------|
| Nozzle temperature | $T_n$ | 190–280 °C | Melt viscosity, bond formation |
| Bed temperature | $T_b$ | 0–110 °C | First-layer adhesion, warp |
| Print speed | $v$ | 20–150 mm/s | Shear rate, under-extrusion risk |
| Layer height | $h$ | 0.05–0.4 mm | Anisotropy, z-resolution |
| Line width | $w$ | 0.3–0.8 mm | Overlap, surface smoothness |
| Infill density | $\rho_i$ | 10–100 % | Mechanical stiffness |
| Cooling fan | $f$ | 0–100 % | Crystallization, layer adhesion |

---

## II. Rheological Constraints

### 2.1 Melt Viscosity — Power Law Model

The apparent viscosity of the polymer melt follows a power-law model:

$$\mu_{app}(\dot{\gamma}) = K \left(\frac{T_{ref}}{T_n}\right)^b \dot{\gamma}^{n-1}$$

where $\dot{\gamma} = \frac{4 Q}{\pi r_n^3}$ is the shear rate at nozzle radius $r_n$, and $K$, $n$, $b$ are material constants.

| Material | $K$ (Pa·s$^n$) | $n$ | $b$ | $T_{ref}$ |
|----------|--------------|-----|-----|-----------|
| PLA | 8200 | 0.37 | 3.8 | 210 °C |
| PETG | 12400 | 0.42 | 4.1 | 230 °C |
| ABS | 9800 | 0.31 | 5.2 | 240 °C |
| PA12 | 15200 | 0.29 | 6.0 | 255 °C |

### 2.2 Maximum Volumetric Flow Rate

The maximum volumetric flow rate before under-extrusion triggers due to viscosity back-pressure:

$$Q_{max} = \frac{\Delta P_{max} \pi r_n^4}{8 \mu_{app} L_n} \cdot n^{1/n} \left(\frac{3n+1}{4n}\right)^{n/(n-1)}$$

This bounds the print speed: $v_{max} = Q_{max} / (h \cdot w)$.

---

## III. Bond Formation and Layer Adhesion

### 3.1 Reptation-Based Bond Strength

The inter-layer bond strength $\sigma_{bond}(t)$ as a function of contact time $t$ follows the de Gennes reptation model:

$$\sigma_{bond}(t) = \sigma_{\infty} \left(\frac{t}{t_{rep}}\right)^{1/4}, \quad t < t_{rep}$$

where $t_{rep} = M_w^3 / (K_{rep} T_n)$ is the reptation time (complete chain diffusion), and $\sigma_\infty$ is the bulk tensile strength.

For PLA at 210 °C: $t_{rep} \approx 1.2$ s, $\sigma_\infty = 65$ MPa.

The contact time is $t = h / v$ — increasing layer height or decreasing speed improves bonding.

---

## IV. Bayesian Optimization of Parameters

### 4.1 Gaussian Process Surrogate

The objective function $J(\boldsymbol{\theta})$ (e.g. 1-dimensional accuracy + bond strength composite) is approximated by a GP surrogate:

$$J(\boldsymbol{\theta}) \sim \mathcal{GP}(\mu(\boldsymbol{\theta}), k(\boldsymbol{\theta}, \boldsymbol{\theta}'))$$

with Matérn-5/2 kernel:

$$k(\boldsymbol{\theta}, \boldsymbol{\theta}') = \sigma^2 \left(1 + \frac{\sqrt{5} r}{\ell} + \frac{5 r^2}{3\ell^2}\right) \exp\left(-\frac{\sqrt{5} r}{\ell}\right), \quad r = \|\boldsymbol{\theta} - \boldsymbol{\theta}'\|$$

```python
from bayes_opt import BayesianOptimization

def print_objective(T_n: float, v: float, h: float, fan: float) -> float:
    """Black-box objective: returns composite quality score 0–1."""
    # Run print, measure dimensional error and bond strength
    ...

optimizer = BayesianOptimization(
    f=print_objective,
    pbounds={
        "T_n": (195.0, 250.0),
        "v":   (30.0, 120.0),
        "h":   (0.1, 0.3),
        "fan": (0.0, 100.0),
    },
    random_state=42,
)
optimizer.maximize(init_points=10, n_iter=50)
print(optimizer.max)
```

---

## V. Multi-Objective Pareto Front

For simultaneous optimization of surface roughness $R_a$, tensile strength $\sigma$, and print time $t_p$, the Pareto front is computed via NSGA-II.

The non-dominated solutions satisfy:

$$\text{Pareto}: \nexists \, \boldsymbol{\theta}' \text{ s.t. } J_1(\boldsymbol{\theta}') \leq J_1(\boldsymbol{\theta}) \land J_2(\boldsymbol{\theta}') \leq J_2(\boldsymbol{\theta}) \land J_3(\boldsymbol{\theta}') \leq J_3(\boldsymbol{\theta})$$

Typical Pareto tradeoff: reducing $R_a$ from 12 µm to 4 µm requires a 3× increase in print time via layer height reduction.

---

## VI. Closed-Loop Feedback Control

```python
from dataclasses import dataclass
import time

@dataclass
class PrintController:
    kp: float = 0.8
    ki: float = 0.1
    integral: float = 0.0

    def update(self, measured_width: float, target_width: float, dt: float) -> float:
        """PID controller: returns extrusion multiplier adjustment."""
        error = target_width - measured_width
        self.integral += error * dt
        return self.kp * error + self.ki * self.integral
```

---

## References

- Mackay, M.E. (2018). The dynamics of the extrusion process in FDM. *Journal of Applied Polymer Science*, 135(5).
- Coogan, T.J. & Kazmer, D.O. (2020). In-line rheological monitoring of FDM. *Polymer*, 205, 122798.
- Deb, K. et al. (2002). A fast and elitist multiobjective genetic algorithm: NSGA-II. *IEEE TEVC*, 6(2), 182-197.
- de Gennes, P.G. (1971). Reptation of a Polymer Chain in the Presence of Fixed Obstacles. *JCP*, 55(2).
