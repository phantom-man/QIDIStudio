#!/usr/bin/env python3
"""
GCode Refiner — Feature-Aware Parameter Injector for 3D Printing
================================================================

Reads a .gcode file, detects feature types from slicer comments (QIDIStudio /
OrcaSlicer / PrusaSlicer), applies profile + rule overrides per feature, and
writes modified .gcode back to the same path (in-place, as required by
QIDISlicer post-processing script protocol).

Architecture:
  - Feature detection: GcodeTools (parses ;TYPE:... slicer comments)
  - Parameter injection: raw string injection (M104, M106, G1 F) — stable vs GcodeTools API
  - Fallback: raw comment parser if GcodeTools is unavailable

Integration:
  - As QIDISlicer post-processing script:
      "C:\\...\\python.exe" "C:\\...\\refiner.py" --rules m2_gear
    QIDISlicer appends the gcode file path as the last argument automatically.

  - Standalone CLI:
      python refiner.py input.gcode [--rules m2_gear] [--profile asa_gf_04mm] [--dry-run]

Usage / research context:
  See gcode_research.md in this directory.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants — slicer comment format (QIDIStudio / OrcaSlicer)
# ---------------------------------------------------------------------------

COMMENT_TYPE_RE    = re.compile(r"^;\s*TYPE\s*:\s*(.+)$",  re.IGNORECASE)
COMMENT_LAYER_RE   = re.compile(r"^;\s*LAYER_CHANGE\s*$",  re.IGNORECASE)
COMMENT_LAYER2_RE  = re.compile(r"^;\s*layer\s+(\d+)\s*$", re.IGNORECASE)  # PrusaSlicer
COMMENT_OBJECT_RE  = re.compile(r"^;\s*MESH\s*:\s*(.+)$",  re.IGNORECASE)

# G1 move with optional F parameter
G1_MOVE_RE         = re.compile(
    r"^(G[01]\s+)([XYZE][0-9.+-]+\s*)*"
    r"(?P<feedrate>F(?P<fval>[0-9.]+))?"
    r"(\s*;.*)?$",
    re.IGNORECASE,
)
FEEDRATE_SWAP_RE   = re.compile(r"\bF\d+(?:\.\d+)?\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Context tracking during file scan
# ---------------------------------------------------------------------------

@dataclass
class BlockContext:
    """Running state while scanning the gcode line-by-line."""
    current_type:   str          = "UNKNOWN"
    current_layer:  int          = 0
    current_object: str          = ""
    current_temp:   int          = 0
    current_fan:    int          = 0
    current_speed:  float        = 0.0   # mm/s (F/60)
    last_injected:  dict         = field(default_factory=dict)  # what was last injected


# ---------------------------------------------------------------------------
# Raw comment-based feature detector (fallback, no dependencies)
# ---------------------------------------------------------------------------

def detect_feature_from_comment(line: str, ctx: BlockContext) -> bool:
    """
    Parse slicer metadata comments from a single gcode line.
    Updates ctx in place. Returns True if the line was a metadata comment.

    Supports QIDIStudio/OrcaSlicer comment format:
      ;TYPE:OUTER_WALL
      ;LAYER_CHANGE
      ;MESH:object_name
    And PrusaSlicer format:
      ;TYPE:External perimeter
      ; layer 42
    """
    line = line.strip()

    # Feature type
    m = COMMENT_TYPE_RE.match(line)
    if m:
        ctx.current_type = _normalize_type(m.group(1).strip())
        return True

    # Layer change (OrcaSlicer/QIDIStudio)
    if COMMENT_LAYER_RE.match(line):
        ctx.current_layer += 1
        return True

    # Layer number (PrusaSlicer: "; layer 42")
    m = COMMENT_LAYER2_RE.match(line)
    if m:
        ctx.current_layer = int(m.group(1))
        return True

    # Object name
    m = COMMENT_OBJECT_RE.match(line)
    if m:
        ctx.current_object = m.group(1).strip()
        return True

    return False


def _normalize_type(raw: str) -> str:
    """
    Normalize slicer-specific feature names to canonical type strings.
    OrcaSlicer uses short names; PrusaSlicer uses long names.
    """
    raw_upper = raw.upper().replace(" ", "_")

    ALIAS = {
        "EXTERNAL_PERIMETER": "OUTER_WALL",
        "PERIMETER":          "INNER_WALL",
        "INTERNAL_PERIMETER": "INNER_WALL",
        "SOLID_INFILL":       "SOLID_INFILL",
        "INTERNAL_INFILL":    "SPARSE_INFILL",
        "INFILL":             "SPARSE_INFILL",
        "BRIDGE":             "BRIDGE",
        "SUPPORT_MATERIAL":   "SUPPORT",
        "SUPPORT_INTERFACE":  "SUPPORT",
        "SKIRT":              "SKIRT_BRIM",
        "BRIM":               "SKIRT_BRIM",
        "PRIME_TOWER":        "PRIME_TOWER",
        "WIPE_TOWER":         "PRIME_TOWER",
        "TOP_SURFACE":        "SOLID_INFILL",
        "BOTTOM_SURFACE":     "SOLID_INFILL",
        "IRONING":            "SOLID_INFILL",
        # OrcaSlicer native names (already canonical)
        "OUTER_WALL":         "OUTER_WALL",
        "INNER_WALL":         "INNER_WALL",
        "SPARSE_INFILL":      "SPARSE_INFILL",
        "SOLID_INFILL":       "SOLID_INFILL",
        "BRIDGE":             "BRIDGE",          # note: OrcaSlicer uses BRIDGE_INFILL
        "BRIDGE_INFILL":      "BRIDGE",
        "SUPPORT":            "SUPPORT",
        "SKIRT_BRIM":         "SKIRT_BRIM",
        "PRIME_TOWER":        "PRIME_TOWER",
    }

    return ALIAS.get(raw_upper, raw_upper)


# ---------------------------------------------------------------------------
# Parameter injection builders
# ---------------------------------------------------------------------------

def _make_temp_line(temp: int, comment: str) -> str:
    """M104 S{temp} (set temperature without waiting)."""
    return f"M104 S{temp} ; refiner: {comment}"


def _make_fan_line(fan_0_255: int, comment: str) -> str:
    """M106 S{value} or M107 (fan off)."""
    if fan_0_255 <= 0:
        return f"M107 ; refiner: {comment}"
    return f"M106 S{fan_0_255} ; refiner: {comment}"


def _make_accel_line(accel: int, comment: str) -> str:
    """M204 P{accel} — set acceleration for print moves."""
    return f"M204 P{accel} ; refiner: {comment}"


def _apply_speed_to_g1(line: str, speed_mm_s: float) -> str:
    """
    Replace the F parameter in a G1/G0 line with the target speed (mm/s → mm/min).
    If no F present in the line, does not add one (speed carries over from previous line).
    """
    feedrate_mm_min = round(speed_mm_s * 60)
    if FEEDRATE_SWAP_RE.search(line):
        return FEEDRATE_SWAP_RE.sub(f"F{feedrate_mm_min}", line, count=1)
    return line


# ---------------------------------------------------------------------------
# Core refiner logic
# ---------------------------------------------------------------------------

class Refiner:
    """
    Reads a gcode file, applies rule-based parameter overrides per feature type,
    and writes the modified gcode.
    """

    def __init__(self, profile_name: str = "asa_gf_04mm", rules_name: str = "m2_gear",
                 verbose: bool = False):
        self.profile_name = profile_name
        self.rules_name   = rules_name
        self.verbose      = verbose

        self.profile = self._load_module("profiles", profile_name)
        self.rules   = self._load_module("rules", rules_name)

        if self.verbose:
            print(f"[refiner] Loaded profile: {profile_name}")
            print(f"[refiner] Loaded rules:   {rules_name}")
            if hasattr(self.rules, 'describe'):
                print(self.rules.describe())

    def _load_module(self, subdir: str, name: str):
        """Load a profile or rules module from the refiner's own directory."""
        here = Path(__file__).parent
        target = here / subdir / f"{name}.py"
        if not target.exists():
            raise FileNotFoundError(
                f"Module not found: {target}\n"
                f"Available: {[p.stem for p in (here / subdir).glob('*.py') if p.stem != '__init__']}"
            )
        spec   = importlib.util.spec_from_file_location(f"{subdir}.{name}", target)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def process_file(self, gcode_path: str) -> dict:
        """
        Process a gcode file in-place (read → transform → write back).

        Returns a stats dict: {lines_in, lines_out, injections, features_seen}.
        """
        src = Path(gcode_path)
        if not src.exists():
            raise FileNotFoundError(f"GCode file not found: {gcode_path}")

        if self.verbose:
            print(f"[refiner] Processing: {src}")

        # Read all lines
        with open(src, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        # Transform
        out_lines, stats = self._transform(lines)

        # Write to temp file first, then replace (atomic-ish)
        tmp = src.with_suffix(".refiner_tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(out_lines)
            shutil.move(str(tmp), str(src))
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise

        if self.verbose:
            print(
                f"[refiner] Done — {stats['lines_in']} in, {stats['lines_out']} out, "
                f"{stats['injections']} injections, "
                f"features seen: {sorted(stats['features_seen'])}"
            )

        return stats

    def _transform(self, lines: list[str]) -> tuple[list[str], dict]:
        """Core line-by-line transform. Returns (output_lines, stats)."""
        ctx   = BlockContext()
        out   = []
        stats = {"lines_in": len(lines), "lines_out": 0, "injections": 0, "features_seen": set()}

        for line in lines:
            stripped = line.rstrip("\n\r")

            # ── Detect feature changes from slicer comments ──────────────
            is_meta = detect_feature_from_comment(stripped, ctx)
            out.append(line)   # always emit original line

            if is_meta:
                # After a type change, inject the new parameter set
                inject = self._build_injection(ctx)
                if inject:
                    out.extend(inject_line + "\n" for inject_line in inject)
                    stats["injections"] += len(inject)
                stats["features_seen"].add(ctx.current_type)
                continue

            # ── Apply speed override to G0/G1 move lines ─────────────────
            override = self.rules.get_override(ctx.current_type, ctx.current_layer, self.profile)
            if override and re.match(r"^G[01]\b", stripped, re.IGNORECASE):
                # Replace the last line with speed-adjusted version
                speed = override.get("speed_mm_s")
                if speed:
                    modified = _apply_speed_to_g1(stripped, speed)
                    if modified != stripped:
                        out[-1] = modified + "\n"

        stats["lines_out"] = len(out)
        return out, stats

    def _build_injection(self, ctx: BlockContext) -> list[str]:
        """
        Build a list of GCode command lines to inject before the first move
        of the new feature type.
        Returns [] if nothing changed vs what was last injected.
        """
        override = self.rules.get_override(ctx.current_type, ctx.current_layer, self.profile)
        if not override:
            return []

        injections = []
        comment  = override.get("comment", f"type={ctx.current_type} layer={ctx.current_layer}")
        last     = ctx.last_injected

        # Temperature
        temp = override.get("nozzle_temp")
        if temp and temp != last.get("nozzle_temp"):
            injections.append(_make_temp_line(temp, comment))
            ctx.last_injected["nozzle_temp"] = temp

        # Fan
        fan = override.get("fan")
        if fan is not None and fan != last.get("fan"):
            injections.append(_make_fan_line(fan, comment))
            ctx.last_injected["fan"] = fan

        # Acceleration
        accel = override.get("accel")
        if accel and accel != last.get("accel"):
            injections.append(_make_accel_line(accel, comment))
            ctx.last_injected["accel"] = accel

        return injections


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "GCode Refiner — feature-aware parameter injector.\n"
            "Run as QIDISlicer post-processing script or standalone CLI.\n\n"
            "QIDISlicer usage (configured in Print Settings → Post-processing scripts):\n"
            '  "C:\\...\\python.exe" "C:\\...\\refiner.py" --rules m2_gear\n'
            "QIDISlicer appends the gcode path as the final argument automatically."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "gcode_file", nargs="?",
        help="Path to input .gcode file (modified in-place). "
             "When run as post-processing script, QIDISlicer passes this automatically.",
    )
    parser.add_argument(
        "--profile", default="asa_gf_04mm",
        help="Filament+nozzle profile name (default: asa_gf_04mm). "
             "Must match a file in profiles/",
    )
    parser.add_argument(
        "--rules", default="m2_gear",
        help="Rule set name (default: m2_gear). Must match a file in rules/",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse and report without writing changes.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print progress and stats.",
    )
    parser.add_argument(
        "--list-profiles", action="store_true",
        help="List available profiles and exit.",
    )
    parser.add_argument(
        "--list-rules", action="store_true",
        help="List available rule sets and exit.",
    )
    return parser.parse_args()


def _list_modules(subdir: str):
    here = Path(__file__).parent / subdir
    if not here.exists():
        print(f"  (directory '{subdir}/' not found)")
        return
    for p in sorted(here.glob("*.py")):
        if p.stem.startswith("_"):
            continue
        mod = importlib.util.spec_from_file_location(p.stem, p)
        print(f"  {p.stem}")


def main():
    args = _parse_args()

    if args.list_profiles:
        print("Available profiles:")
        _list_modules("profiles")
        return 0

    if args.list_rules:
        print("Available rule sets:")
        _list_modules("rules")
        return 0

    # Resolve gcode file path.
    # When called as a post-processing script by QIDISlicer, the gcode path is
    # the last positional argument passed automatically. When called standalone,
    # it's provided explicitly.
    gcode_file = args.gcode_file
    if not gcode_file:
        # QIDISlicer may pass gcode path without the flag if it appears as bare arg
        # Check sys.argv for a .gcode or .g file path we might have missed
        for a in sys.argv[1:]:
            if a.endswith((".gcode", ".g", ".gc")) and os.path.isfile(a):
                gcode_file = a
                break

    if not gcode_file:
        print(
            "Error: No gcode file specified.\n"
            "Usage: refiner.py <file.gcode> [--rules m2_gear] [--profile asa_gf_04mm]\n"
            "Or configure as QIDISlicer post-processing script.",
            file=sys.stderr,
        )
        return 1

    refiner = Refiner(
        profile_name=args.profile,
        rules_name=args.rules,
        verbose=args.verbose or args.dry_run,
    )

    if args.dry_run:
        # Read file, transform in memory, report stats, don't write
        with open(gcode_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        _, stats = refiner._transform(lines)
        print(f"[dry-run] Would inject {stats['injections']} lines into {stats['lines_in']} total lines.")
        print(f"[dry-run] Features detected: {sorted(stats['features_seen'])}")
        return 0

    try:
        stats = refiner.process_file(gcode_file)
        if not args.verbose:
            # Always print minimal summary even in quiet mode
            print(
                f"[refiner] {Path(gcode_file).name}: "
                f"{stats['injections']} injections, "
                f"features: {sorted(stats['features_seen'])}"
            )
        return 0
    except Exception as e:
        print(f"[refiner] ERROR: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
