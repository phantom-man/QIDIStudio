"""Direct test of report-writing code using existing snapshot data.
Run: python scripts/_test_report_write.py
"""

import json, pathlib, sys, traceback, tempfile, os, datetime

os.chdir(r"C:\Users\User\source\repos\QIDIStudio")
sys.path.insert(0, ".")

# Use the latest complete run data
run_dirs = sorted(
    pathlib.Path(r"C:\Users\User\source\repos\QIDIStudio\scripts\debug_runs").glob(
        "20260228_1248*"
    )
)
run_dirs += sorted(
    pathlib.Path(r"C:\Users\User\source\repos\QIDIStudio\scripts\debug_runs").glob(
        "20260228_125424*"
    )
)
run_dirs += sorted(
    pathlib.Path(r"C:\Users\User\source\repos\QIDIStudio\scripts\debug_runs").glob(
        "20260228_130048*"
    )
)

if not run_dirs:
    # Try any dir with 4 cases
    all_dirs = sorted(
        pathlib.Path(
            r"C:\Users\User\source\repos\QIDIStudio\scripts\debug_runs"
        ).iterdir()
    )
    run_dirs = [d for d in all_dirs if (d / "vacuum_nozzle_lower").exists()]

if not run_dirs:
    print("No suitable run dir found")
    sys.exit(1)

run_dir = run_dirs[-1]
print(f"Using run dir: {run_dir}")

from scripts.ai_debug_pipeline import _validate_snapshots, _remediation_hint, TEST_CASES

all_results = []
any_failure = False
cases_by_name = {c["name"]: c for c in TEST_CASES}

for case_dir in sorted(run_dir.iterdir()):
    if not case_dir.is_dir():
        continue
    snap_dir = case_dir / "snapshots"
    if not snap_dir.exists():
        continue
    name = case_dir.name
    case = cases_by_name.get(name, {"name": name, "expected_class": "UNKNOWN"})
    expected = case["expected_class"]
    print(f"  Validating {name} (expected {expected})...", flush=True)
    try:
        validation = _validate_snapshots(snap_dir, expected)
        hint = _remediation_hint(validation, case)
        ok_str = "PASS" if validation["ok"] else "FAIL"
        print(f"    {ok_str}: {validation['remark']}", flush=True)
        if not validation["ok"]:
            any_failure = True
        all_results.append(
            {
                "name": name,
                "model": case.get("model", ""),
                "expected_class": expected,
                "actual_class": validation["actual_class"],
                "ok": validation["ok"],
                "mismatch_flag": validation["mismatch_flag"],
                "remark": validation["remark"],
                "remediation": hint,
                "blender_rc": 0,
                "snapshots_dir": str(snap_dir),
                "log": str(case_dir / "blender.log"),
                "notes": case.get("notes", ""),
                "stages": validation["stages"],
            }
        )
    except Exception as e:
        print(
            f"    ERROR in _validate_snapshots or _remediation_hint: {type(e).__name__}: {e}",
            flush=True,
        )
        traceback.print_exc()
        sys.exit(1)

print(f"\nBuilding summary...", flush=True)
summary = {
    "run_id": "diag_test2",
    "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    "blender": "test",
    "skin": "test",
    "all_pass": not any_failure,
    "cases": all_results,
}

print("Attempting json.dumps...", flush=True)
try:
    txt = json.dumps(summary, indent=2)
    print(f"json.dumps OK ({len(txt)} chars)", flush=True)
except Exception as e:
    print(f"json.dumps FAILED: {type(e).__name__}: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)

print("\nBuilding text report lines...", flush=True)
lines = [
    "QIDIStudio Texture Pipeline — AI Debug Report",
    f"Result: {'ALL PASS' if not any_failure else 'FAILURES DETECTED'}",
    "",
    "=" * 70,
]
try:
    for r in all_results:
        ok_str = "PASS" if r["ok"] else ("SKIP" if r["ok"] is None else "FAIL")
        lines += [f"", f"[{ok_str}] {r['name']}", f"  verdict  : {r['remark']}"]
        if r.get("remediation"):
            for lne in r["remediation"].split("\n"):
                lines.append(f"  {lne}")
        print(f"  Building feature lines for {r['name']}...", flush=True)
        for s in r.get("stages", []):
            if s.get("stage") == "post_classify":
                f_ = s.get("features", {})
                print(f"    features={f_}", flush=True)
                sf = f_.get("sharp_fraction")
                zr = f_.get("z_ratio")
                cs = f_.get("curvature_std")
                chi = f_.get("euler_characteristic")
                print(f"    sf={sf}, zr={zr}, cs={cs}, chi={chi}", flush=True)
                try:
                    line = f"  features : sharp={sf:.3f}  z_ratio={zr:.3f}  curv_std={cs:.3f}  chi={chi}"
                    lines.append(line)
                    print(f"    Line OK: {line}", flush=True)
                except Exception as e2:
                    print(f"    FORMAT ERROR: {type(e2).__name__}: {e2}", flush=True)
                    traceback.print_exc()
                    sys.exit(1)
                break
    print("Text report lines built OK", flush=True)
except Exception as e:
    print(f"EXCEPTION building text report: {type(e).__name__}: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)

print("\nAll OK! Writing test report...", flush=True)
out = run_dir / "_diag_test2_report.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print(f"Written: {out}", flush=True)
print("TEST PASSED", flush=True)
