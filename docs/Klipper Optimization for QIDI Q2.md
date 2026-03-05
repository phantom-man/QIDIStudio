# Klipper Optimization for QIDI Q2 Pro

Technical reference for Klipper firmware optimization on CoreXY printers with dual-extrusion — covering input shaping, pressure advance, resonance testing, and IDEX-specific motion planning.

---

## I. QIDI Q2 Pro Hardware Profile

| Parameter | Specification |
|-----------|--------------|
| Kinematics | CoreXY (IDEX — Independent Dual Extrusion) |
| Build volume | 350 × 350 × 350 mm |
| Extruder | Dual direct-drive (BMG-clone) |
| Hotend | High-flow all-metal, 0.4 mm nozzle |
| Bed | PEI-coated heated bed, 110 °C max |
| MCU | STM32F407 |
| Steppers | X/Y: 2A NEMA 17 (2× per axis, parallel), Z: 3× NEMA 17 |

---

## II. Input Shaping

### 2.1 Theory — Vibration Suppression

CoreXY printers exhibit two dominant resonance modes:
- **X-mode**: Head oscillates along X at frequency $f_X = \frac{1}{2\pi}\sqrt{k_X / m_{head}}$
- **Y-mode**: Gantry oscillates along Y at $f_Y = \frac{1}{2\pi}\sqrt{k_Y / m_{gantry}}$

Input shaping replaces the sharp velocity step profile with a shaped impulse sequence that nulls these resonances. The ZV (Zero-Vibration) shaper applies two impulses at delay $\Delta t = 1/(2f_n)$:

$$A_1 = \frac{1}{1+K}, \quad A_2 = \frac{K}{1+K}, \quad K = e^{-\zeta \pi / \sqrt{1-\zeta^2}}$$

EI (Extra Insensitive) shaper adds a third impulse for robustness to frequency uncertainty.

### 2.2 Resonance Measurement with ADXL345

```ini
# printer.cfg
[adxl345]
cs_pin: rpi:None
spi_bus: spidev0.0

[resonance_tester]
accel_chip: adxl345
probe_points:
    175, 175, 20  # center of bed
```

```bash
# Run from SSH:
RESONANCES_TEST AXIS=X
RESONANCES_TEST AXIS=Y
# Then:
~/klipper/scripts/calibrate_shaper.py /tmp/resonances_x.csv -o /tmp/shaper_x.png
```

Typical QIDI Q2 Pro frequencies: $f_X = 42-52$ Hz, $f_Y = 38-47$ Hz.

### 2.3 Applying the Optimal Shaper

```ini
# printer.cfg
[input_shaper]
shaper_freq_x: 47.2
shaper_freq_y: 42.8
shaper_type: mzv   # Modified ZV — best balance for CoreXY
```

MZV (Modified Zero-Vibration) recommended for CoreXY: suppresses X/Y resonances simultaneously. Unlocks accelerations up to 10,000 mm/s² without ringing.

---

## III. Pressure Advance Calibration

### 3.1 Pressure Advance Physics

At velocity changes, the melt pressure in the nozzle lags behind command. The Klipper pressure advance parameter $K_{PA}$ introduces a predictive extruder advance:

$$E_{advance} = K_{PA} \cdot \frac{dv}{dt}$$

### 3.2 Calibration Procedure

```ini
[extruder]
pressure_advance: 0.045      # Tuned value for 0.6mm/s PLA
pressure_advance_smooth_time: 0.040
```

Calibration tower slicer variable:
- Layer 1: PA = 0.000
- Layer 2: PA = 0.010
- ...step 0.010 per layer up to 0.100

Read optimal layer: first layer where corners are sharp with no blob.

---

## IV. IDEX-Specific Configuration

### 4.1 X-Axis Offset Calibration

The right toolhead X-offset must be calibrated to sub-millimetre accuracy:

```ini
[dual_carriage]
axis: x
step_pin: PE2
dir_pin: PE3
enable_pin: !PE5
microsteps: 16
rotation_distance: 40
endstop_pin: ^PE12
position_endstop: 351
position_max: 351

[gcode_macro T1]
gcode:
    SET_DUAL_CARRIAGE CARRIAGE=1
    RESTORE_GCODE_STATE NAME=dual_carriage_state
```

X-offset fine tuning: print two adjacent 0.4 mm walls with T0 and T1, measure gap optically.

---

## V. Performance Benchmark

| Setting | Speed | Acceleration | Ringing | Notes |
|---------|-------|-------------|---------|-------|
| Stock firmware | 150 mm/s | 500 mm/s² | Visible | No input shaping |
| Klipper default | 200 mm/s | 3000 mm/s² | Moderate | Basic config |
| + Input shaping | 300 mm/s | 8000 mm/s² | Negligible | MZV tuned |
| + Pressure advance | 300 mm/s | 8000 mm/s² | Negligible | Sharp corners |
| Full tuned | 400 mm/s | 10000 mm/s² | Negligible | Optimal quality |

---

## References

- Singer, N. & Seering, W. (1990). Preshaping Command Inputs to Reduce System Vibration. *ASME J. Dyn. Sys.* 112(1), 76-82.
- Klipper Documentation: Resonance Compensation. klipper3d.org/Resonance_Compensation.html.
- Klipper Documentation: Pressure Advance. klipper3d.org/Pressure_Advance.html.
- Bellini, A. & Guceri, S. (2003). Mechanical characterization of parts fabricated using FDM. *Rapid Prototyping J.* 9(4).
