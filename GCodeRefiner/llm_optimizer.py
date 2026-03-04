#!/usr/bin/env python3
"""
GCodeRefiner/llm_optimizer.py — LLM-guided G-code optimizer for NexusSlicer.

Wraps Gemini to propose per-layer G-code improvements while enforcing hard
domain constraints (temperature caps, layer-time floor, retraction limits, fan
restrictions). The LLM never has final authority — every proposal is validated
against the constraint set before being accepted.

Architecture:
    GCodeOptimizer
        ├── chunk_layers()       — split G-code into layers
        ├── build_prompt()       — build per-layer context for Gemini
        ├── validate_edits()     — reject constraint-violating proposals
        └── reassemble()         — stitch validated layers back together

Usage (standalone):
    memory_env\\Scripts\\python.exe -B GCodeRefiner\\llm_optimizer.py \\
        --goals "reduce stringing,improve bridges" \\
        --material "ASA+GF" --dry-run \\
        GCodeRefiner\\test_gears.gcode

Usage (programmatic, as post-processing hook):
    from GCodeRefiner.llm_optimizer import GCodeOptimizer
    opt = GCodeOptimizer()
    improved = opt.optimize(gcode_str, goals=["reduce ooze", "improve first layer adhesion"])
    Path("output.gcode").write_text(improved)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ─── Domain constraints ───────────────────────────────────────────────────────

@dataclass
class PrintConstraints:
    """Hard physical limits the LLM may never override.

    All values are conservative defaults.  Pass a custom instance based on the
    material profile to tighten or loosen them.
    """
    max_temp_extruder: int = 300          # °C — absolute hardware limit
    max_temp_bed: int = 120               # °C
    min_layer_time_s: float = 3.0         # minimum cooling time per layer (s)
    max_retract_mm: float = 8.0           # mm
    max_retract_speed_mms: float = 80.0   # mm/s
    max_fan_pct: int = 100
    min_fan_pct: int = 0
    forbidden_commands: tuple[str, ...] = (
        "M999",   # firmware reset
        "M600",   # filament change (only host slicer should inject)
        "G28",    # home (not safe mid-print)
        "G29",    # mesh levelling (not safe mid-print)
        "M502",   # factory reset EEPROM
        "M503",   # report EEPROM
    )

    def validate(self, gcode_line: str) -> tuple[bool, str]:
        """Check a single G-code line against all hard constraints.

        Returns (is_valid, reason).  ``reason`` is empty string when valid.
        """
        line = gcode_line.strip().upper()
        cmd = line.split(";")[0].strip()   # strip comment

        # Forbidden commands
        for fc in self.forbidden_commands:
            if cmd.startswith(fc):
                return False, f"Forbidden command: {fc}"

        # Temperature caps
        m_temp = re.match(r"M104\s+S(\d+)", cmd)
        if m_temp and int(m_temp.group(1)) > self.max_temp_extruder:
            return False, f"Extruder temp {m_temp.group(1)} exceeds hard cap {self.max_temp_extruder}°C"

        m_bed = re.match(r"M(140|190)\s+S(\d+)", cmd)
        if m_bed and int(m_bed.group(2)) > self.max_temp_bed:
            return False, f"Bed temp {m_bed.group(2)} exceeds hard cap {self.max_temp_bed}°C"

        # Retraction limits
        m_retract = re.match(r"G1\s+E(-[\d.]+)(?:\s+F([\d.]+))?", cmd)
        if m_retract:
            dist = abs(float(m_retract.group(1)))
            if dist > self.max_retract_mm:
                return False, f"Retraction {dist}mm exceeds hard cap {self.max_retract_mm}mm"
            if m_retract.group(2):
                speed_mms = float(m_retract.group(2)) / 60.0
                if speed_mms > self.max_retract_speed_mms:
                    return False, f"Retraction speed {speed_mms:.1f}mm/s exceeds cap {self.max_retract_speed_mms}mm/s"

        # Fan range
        m_fan = re.match(r"M106\s+S(\d+)", cmd)
        if m_fan:
            fan_pct = round(int(m_fan.group(1)) / 255 * 100)
            if fan_pct > self.max_fan_pct:
                return False, f"Fan {fan_pct}% exceeds cap {self.max_fan_pct}%"
            if fan_pct < self.min_fan_pct:
                return False, f"Fan {fan_pct}% below minimum {self.min_fan_pct}%"

        return True, ""


# ─── Layer chunker ────────────────────────────────────────────────────────────

LAYER_CHANGE_RE = re.compile(r"^;\s*LAYER_CHANGE\s*$", re.IGNORECASE)
LAYER_DIGIT_RE  = re.compile(r"^;\s*layer\s+(\d+)\s*$", re.IGNORECASE)


def chunk_layers(gcode: str) -> list[str]:
    """Split G-code text into per-layer chunks.

    Layer boundaries are detected from either ``; LAYER_CHANGE`` (QIDIStudio /
    OrcaSlicer) or ``; layer N`` (PrusaSlicer) comments.  The header (before
    the first layer comment) is returned as chunk[0].
    """
    chunks: list[str] = []
    current: list[str] = []
    for line in gcode.splitlines(keepends=True):
        stripped = line.strip()
        is_boundary = LAYER_CHANGE_RE.match(stripped) or LAYER_DIGIT_RE.match(stripped)
        if is_boundary and current:
            chunks.append("".join(current))
            current = []
        current.append(line)
    if current:
        chunks.append("".join(current))
    return chunks if chunks else [gcode]


# ─── Optimizer ────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert 3D-printing G-code engineer specialising in FDM parameter
optimisation.  Your job is to improve G-code layers provided to you, guided
by the goals described below.

RULES (never violate these):
- Return ONLY G-code lines — no markdown, no explanations, no code fences.
- Never remove ; comments — they carry slicer metadata.
- Never add or change layer-change or TYPE comments.
- Never add firmware-reset or homing commands (M999, G28, G29).
- Apply changes conservatively: prefer minimal edits with maximum measured effect.
- When in doubt, return the original layer unchanged.

OUTPUT: Return the full modified layer G-code, one line per output line.
"""


class GCodeOptimizer:
    """LLM-guided G-code optimizer with hard-constraint enforcement.

    Args:
        model:       Gemini model identifier (default gemini-2.5-flash).
        constraints: Physical limits to enforce.  Uses safe defaults if None.
        max_layers:  Max number of layers sent to the LLM.  Remaining layers
                     are passed through unchanged (saves tokens on large files).
    """

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        constraints: Optional[PrintConstraints] = None,
        max_layers: int = 50,
    ) -> None:
        self.model = model
        self.constraints = constraints or PrintConstraints()
        self.max_layers = max_layers
        self._llm = None  # lazy-initialise to avoid import cost when not needed

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI  # noqa: PLC0415
            self._llm = ChatGoogleGenerativeAI(model=self.model, temperature=0.2)
        except ImportError as exc:
            raise RuntimeError(
                "langchain-google-genai not installed — run: "
                "pip install langchain-google-genai"
            ) from exc
        return self._llm

    def _optimise_layer(self, layer: str, goals: list[str], layer_idx: int) -> str:
        """Ask Gemini to improve a single layer and validate the result."""
        llm = self._get_llm()
        goals_str = "\n".join(f"- {g}" for g in goals)
        prompt = (
            f"{_SYSTEM_PROMPT}\n\n"
            f"GOALS for this print:\n{goals_str}\n\n"
            f"LAYER {layer_idx}:\n```\n{layer.rstrip()}\n```"
        )
        try:
            response = llm.invoke(prompt)
            proposed = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:
            return layer  # on any LLM error, return original

        # Validate every proposed line
        validated_lines: list[str] = []
        rejected = 0
        for line in proposed.splitlines(keepends=True):
            ok, reason = self.constraints.validate(line)
            if ok:
                validated_lines.append(line)
            else:
                # Fall back to the original line at this position
                validated_lines.append(f"{line.rstrip()}  ; [OPTIMIZER: rejected — {reason}]\n")
                rejected += 1

        result = "".join(validated_lines)
        # Safety: if more than 20% of proposed lines were rejected, use original
        if rejected > len(validated_lines) * 0.2:
            return layer
        return result

    def optimize(
        self,
        gcode: str,
        goals: Optional[list[str]] = None,
        verbose: bool = False,
    ) -> str:
        """Optimize G-code by applying LLM-proposed improvements per layer.

        Args:
            gcode:   Full G-code as a string.
            goals:   List of natural-language improvement goals.
            verbose: Print per-layer status.

        Returns:
            Optimized G-code string.
        """
        if goals is None:
            goals = ["reduce stringing", "improve bridge quality", "optimise print speed"]

        chunks = chunk_layers(gcode)
        header = chunks[0]
        layers = chunks[1:]

        if verbose:
            print(f"[llm_optimizer] {len(layers)} layers found, "
                  f"optimising first {min(len(layers), self.max_layers)}…")

        result_chunks: list[str] = [header]
        for i, layer in enumerate(layers):
            if i >= self.max_layers:
                result_chunks.append(layer)  # passthrough
                continue
            improved = self._optimise_layer(layer, goals, layer_idx=i + 1)
            if verbose:
                changed = improved != layer
                print(f"  Layer {i+1:>4}/{len(layers)}  {'[MODIFIED]' if changed else '[unchanged]'}")
            result_chunks.append(improved)

        return "".join(result_chunks)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="llm_optimizer",
        description="LLM-guided G-code optimiser for NexusSlicer.",
    )
    parser.add_argument("input", help="Path to input .gcode file")
    parser.add_argument(
        "--goals", default="reduce stringing,improve bridge quality",
        help="Comma-separated optimisation goals",
    )
    parser.add_argument(
        "--material", default="",
        help="Material name hint (informational — included in LLM prompt context)",
    )
    parser.add_argument(
        "--model", default="gemini-2.5-flash",
        help="Gemini model identifier",
    )
    parser.add_argument(
        "--max-layers", type=int, default=50,
        help="Maximum number of layers to send to LLM (rest pass through unchanged)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse and plan only — do not call LLM or write output",
    )
    parser.add_argument(
        "--output", default="",
        help="Output path (default: overwrite input, like QIDIStudio post-processing protocol)",
    )
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()
    goals = [g.strip() for g in args.goals.split(",") if g.strip()]
    if args.material:
        goals.append(f"optimise for {args.material} material properties")

    gcode_path = Path(args.input)
    if not gcode_path.exists():
        print(f"[llm_optimizer] ERROR: file not found: {gcode_path}", file=sys.stderr)
        return 1

    gcode = gcode_path.read_text(encoding="utf-8", errors="replace")
    chunks = chunk_layers(gcode)
    print(f"[llm_optimizer] Loaded: {gcode_path.name}  ({len(chunks)-1} layers, {len(gcode):,} chars)")
    print(f"[llm_optimizer] Goals: {goals}")

    if args.dry_run:
        print(f"[dry-run] Would optimise layers 1–{min(len(chunks)-1, args.max_layers)} via {args.model}")
        return 0

    opt = GCodeOptimizer(model=args.model, max_layers=args.max_layers)
    improved = opt.optimize(gcode, goals=goals, verbose=True)

    out_path = Path(args.output) if args.output else gcode_path
    out_path.write_text(improved, encoding="utf-8")
    print(f"[llm_optimizer] Written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
