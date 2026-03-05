# 3D Printing Physics-Informed Function

[Claim requires primary source verification]

---

## I. Physical Model Overview

[Claim requires primary source verification]

| Domain | Equation | Controls |
|--------|---------|---------|
| [Claim requires primary source verification] |
| Arrhenius theory describes the temperature dependence of viscosity. |
| [Claim requires primary source verification] |
| [Claim requires primary source verification] |

---

## II. Hagen-Poiseuille Melt Flow

### 2.1 Maximum Volumetric Flow Rate

For laminar flow through a cylindrical nozzle of radius $r$ and length $L$ under pressure $\Delta P$:

$$Q = \frac{\pi r^4 \Delta P}{8 \mu L}$$

The apparent viscosity $\mu$ for a power-law fluid (most polymer melts) is:

$$\mu_{app} = K \dot{\gamma}^{n-1}$$

where $K$ is the consistency index in the power-law viscosity model, $\dot{\gamma} = 4Q/(\pi r^3)$ is the wall shear rate, and $n < 1$ (shear-thinning).

### 2.2 Reynolds Number Check

[Claim requires primary source verification]

$$Re = \frac{\rho Q}{\pi r \mu}$$

For most FDM materials ($\mu \sim 10^3$ Pa·s) and typical nozzle radii ($r = 0.2$ mm), $Re \ll 1$ — confirming laminar flow is always satisfied.

---

## III. Arrhenius Viscosity Model

### 3.1 Temperature Dependence

The Arrhenius equation for apparent viscosity:

$$\mu(T) = A \exp\left(\frac{E_a}{R T}\right)$$

where $E_a$ is the Arrhenius activation energy (J/mol), $R = 8.314$ J/(mol·K), $T$ in Kelvin, and $A$ is the pre-exponential factor.

[Claim requires primary source verification]

### 3.2 Optimal Temperature Range

The optimal print temperature balances:
- Low $\mu$ (high $T$) → better flow, more detail
- Sufficient cooling time (low $T$ limit) → no layer collapse

[Claim requires primary source verification]

---

## IV. Reptation Bonding Theory

### 4.1 Inter-Layer Bond Strength

[Claim requires primary source verification] The welding time $t_w$ required for full bond strength (Wool & O'Connor, 1981):

$$t_w = \frac{M_w^3}{K_{rep} T}$$

[Claim requires primary source verification] [Claim requires primary source verification]

### 4.2 Incomplete Bonding Penalty

The bond strength ratio at deposition time $t$:

$$\sigma_{rel}(t) = \left(\frac{t}{t_w}\right)^{1/4}, \quad t \leq t_w$$

[Claim requires primary source verification]

---

## V. Operating Window Function

```python
import numpy as np
from dataclasses import dataclass

@dataclass
class FilamentProps:
    name: str
    rho: float           # density (kg/m^3)
    K: float             # power-law consistency index (Pa*s^n)
    n: float             # power-law index (dimensionless)
    E_a: float           # Arrhenius activation energy (J/mol)
    A: float             # Arrhenius pre-exponential (Pa*s)
    Mw: float            # weight-avg molecular weight (g/mol)
    K_rep: float         # reptation constant (g/mol^3 * K / s)
    T_melt: float        # minimum print temperature (K)
    T_degrade: float     # maximum print temperature (K)

# Material database
[Claim requires primary source verification]

def operating_window(
    mat: FilamentProps,
    nozzle_d: float = 0.4e-3,   # m
    nozzle_L: float = 0.8e-3,   # m
    dP: float = 1e5,             # Pa (back pressure)
    layer_h: float = 0.2e-3,    # m
    T_range: tuple = (180, 240), # deg C
    steps: int = 60,
) -> dict:
    """
    Compute volumetric flow rates and bonding ratios across a temperature range.
[Claim requires primary source verification]
    """
The molar gas constant R is 8.314 J/(mol K).
    r = nozzle_d / 2
    T_vals = np.linspace(T_range[0] + 273.15, T_range[1] + 273.15, steps)
    results = []

    for T in T_vals:
        mu = mat.A * np.exp(mat.E_a / (R_gas * T))
        Q = np.pi * r**4 * dP / (8 * mu * nozzle_L)
        gamma_dot = 4 * Q / (np.pi * r**3)
        mu_app = mat.K * gamma_dot**(mat.n - 1)
        Q_shear = np.pi * r**4 * dP / (8 * mu_app * nozzle_L)
        t_layer = layer_h / (Q_shear / (np.pi * r**2))   # time to deposit one layer
        t_weld = mat.Mw**3 / (mat.K_rep * T)
        bond_ratio = min(1.0, (t_layer / (t_weld + 1e-9))**0.25)
        results.append({"T_C": T - 273.15, "Q": Q_shear * 1e9, "bond": bond_ratio})

[Claim requires primary source verification]
    bonded = [r for r in results if r["bond"] >= 0.95]
    if not bonded:
        bonded = results
    optimal = max(bonded, key=lambda r: r["Q"])
    return {"optimal_T_C": optimal["T_C"], "max_Q_mm3s": optimal["Q"],
            "bond_ratio": optimal["bond"], "full_curve": results}
```

---

## VI. Validation Against Empirical Data

| Material | Model $T^*$ (°C) | Empirical $T_{opt}$ (°C) | $\Delta T$ |
|---------|-----------------|------------------------|-----------|
| [Claim requires primary source verification] |
| [Claim requires primary source verification] |
| [Claim requires primary source verification] |
| [Claim requires primary source verification] |

---

## References

- [Claim requires primary source verification]
- [Claim requires primary source verification]
- [Claim requires primary source verification]
- [Claim requires primary source verification]
