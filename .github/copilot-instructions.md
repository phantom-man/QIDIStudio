# QIDIStudio Copilot — Session Bootstrap

You are **GitHub Copilot**, engineering AI for the **QIDIStudio** fork.
Repo  : `C:\Users\User\source\repos\QIDIStudio\`  
GitHub: `phantom-man/QIDIStudio`
Model : Claude Sonnet 4.6

---

## YOUR KNOWLEDGE IS IN LanceDB, NOT IN THIS FILE

The **UserPromptSubmit** hook has already called `memory/inject.py` before this prompt arrived.  
Look above — you should see `━━━ QIDISTUDIO KNOWLEDGE BASE ━━━`.

**If you see it:** knowledge base is loaded. Proceed.  
**If you do NOT see it:** run this in the `scripts` terminal, then read the output:
```powershell
& 'C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe' memory/inject.py
```

---

## Memory Commands

| Purpose | Command |
|---------|---------|
| Compact manifest (all topics) | `python memory/inject.py` |
| Full text dump (everything verbatim) | `python memory/inject.py --full` |
| Semantic search | `python memory/inject.py --query "cmake build"` |
| Re-index docs to LanceDB | `python memory/extract.py` |
| Push prompt to LangSmith Hub | `python memory/push_prompt.py` |

---

## Minimal Reference (in case memory is unavailable)

- **Build source**: `C:\QIDISrc\QIDIStudio\build\`  
- **Install dir** : `C:\QIDISrc\QIDIStudio\install_dir\`  
- **bpy script**  : `resources\scripts\apply_texture_bpy.py`  
- **Blender**     : `C:\Program Files\Blender Foundation\Blender 5.0\blender.exe`  
- **Python 3.13** : `C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe`  
- **Python 3.11** : `bpy_env\Scripts\python.exe` (Blender bpy pip package, not for general use)

**Build command:**
```powershell
Set-Location C:\QIDISrc\QIDIStudio\build
cmake --build . --target install --config Release -- /m:16 2>&1 | Tee-Object build_out.txt; echo "DONE" >> build_out.txt
```

---

## Session Learnings Log

Append rows here — `memory/extract.py` auto-indexes them into LanceDB.

| Date | Category | Topic | Decision | Rationale |
|------|----------|-------|----------|-----------|
