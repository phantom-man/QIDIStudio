import json, pathlib

h = json.loads(pathlib.Path("scripts/debug_runs/pipeline_history.json").read_text())
for e in h:
    role = str(e.get("role", ""))
    fn = str(e.get("function", ""))
    txt = str(e.get("result", e.get("text", "")))[:120]
    print(f"iter={e.get('iteration')}  role={role:<12}  fn={fn:<28}  {txt}")
