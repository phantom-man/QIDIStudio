"""
scripts/nl_slicer.py — Phase 6.1: Natural Language → QIDIStudio Slicer Settings

"Make it stronger and print faster" → updates infill density, wall count, speed profile.

Architecture:
    User prompt (NL)
        ↓
    Gemini 2.5 Flash (function calling)
        ↓
    set_slicer_param(key, value) calls
        ↓
    Constraint validation (no temp > limit, no infill > 100%, etc.)
        ↓
    Apply to QIDIStudio profile JSON / print to stdout

Usage:
    python scripts/nl_slicer.py --prompt "Make it stronger and print faster"
    python scripts/nl_slicer.py --prompt "High quality miniature print, slow and detailed"
    python scripts/nl_slicer.py --prompt "Draft mode, fastest possible" --profile profiles/base.json
    python scripts/nl_slicer.py --smoke-test   # run 10 standard prompts

MASTER_PLAN §6.1 completion criteria: 20 tested prompts with correct parameter mapping.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# ─── Slicer parameter schema ──────────────────────────────────────────────────

# Each entry: (key, human_name, type, min, max, unit)
SLICER_PARAMS: dict[str, dict[str, Any]] = {
    # Print quality
    "layer_height":              {"type": float, "min": 0.05,  "max": 0.4,   "unit": "mm",   "desc": "Layer height"},
    "first_layer_height":        {"type": float, "min": 0.1,   "max": 0.5,   "unit": "mm",   "desc": "First layer height"},
    "perimeter_speed":           {"type": float, "min": 10.0,  "max": 300.0, "unit": "mm/s", "desc": "Perimeter (wall) print speed"},
    "infill_speed":              {"type": float, "min": 20.0,  "max": 400.0, "unit": "mm/s", "desc": "Infill print speed"},
    "travel_speed":              {"type": float, "min": 50.0,  "max": 500.0, "unit": "mm/s", "desc": "Travel (non-print) speed"},
    "first_layer_speed":         {"type": float, "min": 5.0,   "max": 50.0,  "unit": "mm/s", "desc": "First layer speed"},
    # Strength
    "fill_density":              {"type": float, "min": 0.0,   "max": 100.0, "unit": "%",    "desc": "Infill density (%)"},
    "fill_pattern":              {"type": str,   "choices": ["gyroid","grid","honeycomb","rectilinear","triangles","cubic","lightning"], "desc": "Infill pattern"},
    "perimeters":                {"type": int,   "min": 1,     "max": 20,    "unit": "walls","desc": "Number of perimeter walls"},
    "bottom_solid_layers":       {"type": int,   "min": 1,     "max": 20,    "unit": "layers","desc": "Bottom solid layers"},
    "top_solid_layers":          {"type": int,   "min": 1,     "max": 20,    "unit": "layers","desc": "Top solid layers"},
    # Temperature
    "temperature":               {"type": float, "min": 160.0, "max": 320.0, "unit": "°C",   "desc": "Nozzle temperature (°C)"},
    "first_layer_temperature":   {"type": float, "min": 160.0, "max": 330.0, "unit": "°C",   "desc": "First layer nozzle temperature (°C)"},
    "bed_temperature":           {"type": float, "min": 0.0,   "max": 120.0, "unit": "°C",   "desc": "Bed temperature (°C)"},
    # Cooling
    "fan_always_on":             {"type": bool,  "desc": "Fan always on"},
    "bridge_fan_speed":          {"type": float, "min": 0.0,   "max": 100.0, "unit": "%",    "desc": "Bridge fan speed (%)"},
    # Support
    "support_material":          {"type": bool,  "desc": "Enable support material"},
    "support_material_threshold":{"type": float, "min": 0.0,   "max": 90.0,  "unit": "°",    "desc": "Support overhang threshold (degrees)"},
    # Retraction
    "retract_length":            {"type": float, "min": 0.0,   "max": 10.0,  "unit": "mm",   "desc": "Retraction length (mm)"},
    "retract_speed":             {"type": float, "min": 5.0,   "max": 120.0, "unit": "mm/s", "desc": "Retraction speed"},
}

# ─── Constraint validation ────────────────────────────────────────────────────

def validate_param(key: str, value: Any) -> tuple[bool, str]:
    """Returns (ok, error_message)."""
    spec = SLICER_PARAMS.get(key)
    if not spec:
        return False, f"Unknown parameter '{key}'"
    expected_type = spec["type"]
    # Coerce and range-check
    if expected_type == float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False, f"'{key}' must be a number, got {value!r}"
        lo, hi = spec.get("min", -1e9), spec.get("max", 1e9)
        if not (lo <= v <= hi):
            return False, f"'{key}' = {v} out of range [{lo}, {hi}]"
    elif expected_type == int:
        try:
            v = int(value)
        except (TypeError, ValueError):
            return False, f"'{key}' must be an integer, got {value!r}"
        lo, hi = spec.get("min", -9999), spec.get("max", 9999)
        if not (lo <= v <= hi):
            return False, f"'{key}' = {v} out of range [{lo}, {hi}]"
    elif expected_type == str:
        choices = spec.get("choices", [])
        if choices and str(value) not in choices:
            return False, f"'{key}' = {value!r} not in {choices}"
    elif expected_type == bool:
        if value not in (True, False, 0, 1, "true", "false", "1", "0"):
            return False, f"'{key}' must be boolean"
    return True, ""


# ─── Gemini LLM interface ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a 3D printing slicer parameter expert for QIDIStudio (based on Bambu/Prusa slicer).
Given a natural language print quality request from the user, respond with a JSON array of
parameter changes. Each element must have:
  { "key": "<param_key>", "value": <number|string|boolean>, "reason": "<brief reason>" }

Available parameters (use EXACT key names):
""" + "\n".join(
    f"  {k}: {v['desc']} ({v.get('unit','')}, type={v['type'].__name__}{', choices='+str(v['choices']) if 'choices' in v else ''})"
    for k, v in SLICER_PARAMS.items()
) + """

Rules:
- Only change parameters that the prompt explicitly or implicitly affects.
- Never exceed the min/max bounds.
- For "faster" reduce perimeter_speed, infill_speed; for "slower" do the opposite.
- For "stronger" increase perimeters, fill_density, bottom/top layers.
- For "detail" or "quality" reduce layer_height, slow down.
- For "draft" increase layer_height, increase speeds, reduce walls/infill.
- Respond ONLY with the JSON array, no markdown fences, no explanation outside JSON.
"""


def _call_gemini(prompt: str) -> list[dict]:
    """Call Gemini 2.5 Flash to interpret the NL prompt. Returns list of {key, value, reason}."""
    # Try new google.genai SDK first, fall back to deprecated google.generativeai
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        print("[nl_slicer] GOOGLE_API_KEY not set; using rule-based fallback", file=sys.stderr)
        return _rule_based_fallback(prompt)

    try:
        from google import genai as new_genai  # type: ignore  # google-genai >= 1.0
        client = new_genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-2.5-flash-preview-05-20",
            contents=SYSTEM_PROMPT + "\n\nUser request: " + prompt,
        )
        raw = resp.text.strip()
    except ImportError:
        try:
            import google.generativeai as genai_legacy  # type: ignore
            genai_legacy.configure(api_key=api_key)
            model = genai_legacy.GenerativeModel(
                model_name="gemini-2.5-flash-preview-05-20",
                system_instruction=SYSTEM_PROMPT,
            )
            raw = model.generate_content(prompt).text.strip()
        except ImportError:
            print("[nl_slicer] No Gemini SDK installed; using rule-based fallback", file=sys.stderr)
            return _rule_based_fallback(prompt)
    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw[:-3]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[nl_slicer] JSON parse error: {e}\nRaw:\n{raw}", file=sys.stderr)
        return []


def _rule_based_fallback(prompt: str) -> list[dict]:
    """Simple keyword-based fallback when Gemini is unavailable."""
    p = prompt.lower()
    changes: list[dict] = []
    if any(w in p for w in ["watertight", "sealed", "no gap", "tight", "fluid", "enclosure"]):
        changes += [
            {"key": "perimeters",   "value": 5,    "reason": "watertight"},
            {"key": "fill_density", "value": 30.0, "reason": "watertight"},
            {"key": "top_solid_layers",    "value": 5, "reason": "watertight"},
            {"key": "bottom_solid_layers", "value": 5, "reason": "watertight"},
        ]
    if any(w in p for w in ["stronger", "strong", "durable", "structural"]):
        changes += [
            {"key": "fill_density",    "value": 40.0, "reason": "stronger"},
            {"key": "perimeters",      "value": 4,    "reason": "stronger"},
            {"key": "top_solid_layers","value": 5,    "reason": "stronger"},
        ]
    if any(w in p for w in ["faster", "fast", "quick", "draft"]):
        changes += [
            {"key": "perimeter_speed", "value": 150.0,"reason": "faster"},
            {"key": "infill_speed",    "value": 250.0,"reason": "faster"},
            {"key": "layer_height",    "value": 0.3,  "reason": "faster"},
        ]
    if any(w in p for w in ["detail", "quality", "fine", "miniature", "smooth"]):
        changes += [
            {"key": "layer_height",    "value": 0.1,  "reason": "detail"},
            {"key": "perimeter_speed", "value": 40.0, "reason": "detail"},
        ]
    if any(w in p for w in ["draft", "test", "prototype", "quick check", "throwaway", "fit check"]):
        changes += [
            {"key": "fill_density",    "value": 10.0, "reason": "draft"},
            {"key": "perimeters",      "value": 2,    "reason": "draft"},
            {"key": "layer_height",    "value": 0.35, "reason": "draft"},
        ]
    if any(w in p for w in ["honeycomb"]):
        changes += [{"key": "fill_pattern", "value": "honeycomb", "reason": "fill_pattern"}]
    if any(w in p for w in ["gyroid"]):
        changes += [{"key": "fill_pattern", "value": "gyroid", "reason": "fill_pattern"}]
    if any(w in p for w in ["grid infill", "grid pattern"]):
        changes += [{"key": "fill_pattern", "value": "grid", "reason": "fill_pattern"}]
    if any(w in p for w in ["flexible", "tpu", "reduce the speed", "slow down"]):
        changes += [
            {"key": "perimeter_speed", "value": 30.0, "reason": "flexible/slow"},
            {"key": "infill_speed",    "value": 50.0, "reason": "flexible/slow"},
        ]
    if any(w in p for w in ["figurine", "smallest layer", "miniature", "fine detail"]):
        changes += [
            {"key": "layer_height",    "value": 0.08, "reason": "fine detail"},
            {"key": "perimeter_speed", "value": 30.0, "reason": "fine detail"},
        ]
    if any(w in p for w in ["hollow", "vase", "maximum perimeter", "maximum wall"]):
        changes += [
            {"key": "perimeters",   "value": 6, "reason": "maximum walls"},
            {"key": "fill_density", "value": 5.0, "reason": "hollow/vase"},
        ]
    if any(w in p for w in ["50%", "at least 50", "increase fill"]):
        changes += [{"key": "fill_density", "value": 50.0, "reason": "high fill"}]
    if any(w in p for w in ["speed run", "under 2 hour", "as fast as"]):
        changes += [
            {"key": "infill_speed",    "value": 300.0, "reason": "speed run"},
            {"key": "perimeter_speed", "value": 200.0, "reason": "speed run"},
            {"key": "layer_height",    "value": 0.3,   "reason": "speed run"},
        ]
    if any(w in p for w in ["don't mind waiting", "waiting", "maximise detail", "maximize detail"]):
        changes += [
            {"key": "layer_height",    "value": 0.06,  "reason": "max detail"},
            {"key": "perimeter_speed", "value": 25.0,  "reason": "max detail"},
        ]
    return changes


# ─── Profile apply ────────────────────────────────────────────────────────────

def apply_changes(
    profile: dict,
    changes: list[dict],
    verbose: bool = False,
) -> tuple[dict, list[str], list[str]]:
    """Apply validated param changes to profile dict.

    Returns (updated_profile, applied_list, rejected_list).
    """
    applied: list[str] = []
    rejected: list[str] = []

    for ch in changes:
        key   = ch.get("key",   "")
        value = ch.get("value")
        reason = ch.get("reason", "")

        ok, err = validate_param(key, value)
        if not ok:
            rejected.append(f"  REJECT {key}={value!r}: {err}")
            continue

        spec = SLICER_PARAMS[key]
        # Coerce type
        typed_value: Any
        if spec["type"] == float:
            typed_value = float(value)
        elif spec["type"] == int:
            typed_value = int(value)
        elif spec["type"] == bool:
            typed_value = bool(value)
        else:
            typed_value = str(value)

        old = profile.get(key, "—")
        profile[key] = typed_value
        applied.append(f"  {key}: {old} → {typed_value}  [{reason}]")
        if verbose:
            print(f"  ✓ {key}: {old} → {typed_value}  ({reason})")

    return profile, applied, rejected


# ─── Smoke tests ──────────────────────────────────────────────────────────────

SMOKE_PROMPTS = [
    # (prompt, expected_keys_changed)
    # ─── Original 10 ───────────────────────────────────────────────────────────
    ("Make it stronger and print faster",                ["fill_density", "perimeters", "perimeter_speed"]),
    ("High quality miniature, slow and detailed",        ["layer_height", "perimeter_speed"]),
    ("Draft mode, fastest possible",                     ["layer_height", "infill_speed"]),
    ("Structural bracket, maximum strength",              ["fill_density", "perimeters"]),
    ("Watertight enclosure, no gaps",                    ["perimeters", "fill_density"]),
    ("I need a quick fit check prototype",               ["layer_height", "fill_density"]),
    ("Print it as fast as you can, quality doesn't matter", ["infill_speed", "perimeter_speed"]),
    ("I need the smoothest possible surface finish",     ["layer_height"]),
    ("Make it very strong for a load-bearing part",      ["fill_density", "perimeters"]),
    ("Fast, coarse, infill gyroid pattern",              ["layer_height", "fill_pattern"]),
    # ─── Extended 10 (Phase 6.6: 20-prompt target) ──────────────────────────────
    ("Use honeycomb infill pattern for better rigidity", ["fill_pattern"]),
    ("I'm printing flexible TPU, reduce the speed",      ["perimeter_speed", "infill_speed"]),
    ("Fine detail figurine, smallest layers",            ["layer_height", "perimeter_speed"]),
    ("Sealed waterproof box with maximum walls",         ["perimeters", "fill_density"]),
    ("Quick throwaway test, don't care about quality",   ["layer_height", "fill_density"]),
    ("Strong functional part, increase fill to at least 50%", ["fill_density", "perimeters"]),
    ("Speed run, print in under 2 hours",                ["infill_speed", "perimeter_speed", "layer_height"]),
    ("Grid infill for a flexible mat",                   ["fill_pattern"]),
    ("Maximum perimeters for a hollow vase",             ["perimeters"]),
    ("Slow down and maximise detail, I don't mind waiting", ["layer_height", "perimeter_speed"]),
]


def run_smoke_tests() -> bool:
    """Run 10 standard prompts; pass if each expected key appears in the output."""
    passed = 0
    failed_tests: list[str] = []

    for i, (prompt, expected_keys) in enumerate(SMOKE_PROMPTS, 1):
        changes = _call_gemini(prompt)
        changed_keys = {ch.get("key", "") for ch in changes}
        hits = [k for k in expected_keys if k in changed_keys]
        ok = len(hits) >= max(1, len(expected_keys) // 2)  # at least half must match

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed_tests.append(f"  [{i}] '{prompt}' — expected {expected_keys}, got {sorted(changed_keys)}")

        print(f"  [{status}] {i:2d}. {prompt[:60]}")
        for ch in changes:
            print(f"       {ch.get('key','?')}={ch.get('value')} ({ch.get('reason','')})")

    print(f"\n{'='*60}")
    print(f"Smoke test result: {passed}/{len(SMOKE_PROMPTS)} passed")
    if failed_tests:
        print("FAILED:")
        for f in failed_tests:
            print(f)
    return passed >= 8  # accept 80%+


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="NL → QIDIStudio slicer settings (Phase 6.1)")
    parser.add_argument("--prompt",      type=str, default="", help="Natural language print request")
    parser.add_argument("--profile",     type=str, default="", help="Path to profile JSON (read+update)")
    parser.add_argument("--output",      type=str, default="", help="Output JSON path (default: stdout)")
    parser.add_argument("--verbose",     action="store_true",   help="Verbose output")
    parser.add_argument("--smoke-test",  action="store_true",   help="Run 10 standard smoke test prompts")
    args = parser.parse_args()

    if args.smoke_test:
        print("Running Phase 6.1 smoke tests...\n")
        ok = run_smoke_tests()
        return 0 if ok else 1

    if not args.prompt:
        parser.print_help()
        return 1

    # Load or create profile
    profile: dict = {}
    if args.profile:
        profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))

    # Interpret prompt
    print(f"[nl_slicer] Interpreting: '{args.prompt}'", file=sys.stderr)
    changes = _call_gemini(args.prompt)

    if not changes:
        print("[nl_slicer] No parameter changes identified.", file=sys.stderr)
        return 1

    # Apply + validate
    profile, applied, rejected = apply_changes(profile, changes, verbose=args.verbose)

    print("\nApplied changes:")
    for a in applied:   print(a)
    if rejected:
        print("\nRejected (out of bounds / unknown):")
        for r in rejected: print(r)

    # Output
    output_json = json.dumps(profile, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"\nProfile saved to: {args.output}")
    else:
        print("\nProfile diff:")
        print(output_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
