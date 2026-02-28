"""Diagnostic script — run with plain python to check pipeline report writing."""

import json, pathlib, sys, traceback, os

os.chdir(r"C:\Users\User\source\repos\QIDIStudio")
sys.path.insert(0, ".")

run_dir = pathlib.Path(
    r"C:\Users\User\source\repos\QIDIStudio\scripts\debug_runs\20260228_124700"
)
cases_dirs = sorted([d for d in run_dir.iterdir() if d.is_dir()])
print(f"Found {len(cases_dirs)} case dirs: {[d.name for d in cases_dirs]}")

all_results = []
for case_dir in cases_dirs:
    snap = case_dir / "snapshots" / "session_summary.json"
    if snap.exists():
        try:
            d = json.loads(snap.read_text(encoding="utf-8"))
            stages = d.get("stages", [])
            print(f"  {case_dir.name}: {len(stages)} stages OK")
            all_results.append(
                {"name": case_dir.name, "ok": True, "stages": stages, "remark": "ok"}
            )
        except Exception as e:
            print(f"  {case_dir.name}: JSON LOAD FAILED — {e}")
    else:
        print(f"  {case_dir.name}: no session_summary.json")

print("\nAttempting json.dump of all_results...")
summary = {
    "run_id": "diag_test",
    "all_pass": True,
    "cases": all_results,
}
try:
    txt = json.dumps(summary, indent=2)
    print(f"json.dumps OK — {len(txt)} chars")
except Exception as e:
    print(f"json.dumps FAILED: {e}")
    traceback.print_exc()

print("\nWriting test report...")
try:
    out = run_dir / "_diag_report.txt"
    out.write_text("DIAG OK\n", encoding="utf-8")
    print(f"Write OK: {out}")
except Exception as e:
    print(f"Write FAILED: {e}")
    traceback.print_exc()
