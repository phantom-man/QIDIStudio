$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$date = Get-Date -Format 'yyyy-MM-dd'
$repo = 'C:\Users\User\source\repos\QIDIStudio'
$log = Join-Path $repo '.github\hooks\precompact.log'
$py = Join-Path $repo 'memory_env\Scripts\python.exe'

Add-Content -Path $log -Value "$ts [PreCompact] fired"

# Write compaction flag so inject.py banners every subsequent prompt until
# the agent runs extract.py (which deletes the flag).
$flag = Join-Path $repo 'memory\_compaction_pending.txt'
Set-Content -Path $flag -Value $ts -Encoding UTF8
Add-Content -Path $log -Value "$ts [PreCompact] compaction flag written: $flag"

# NOTE: We do NOT run extract.py here before emitting the instruction.
# Reason: extract.py would index the file BEFORE the agent writes new learnings,
# missing everything from the current session. Instead, the agent instruction below
# tells the agent to do the full write → extract → commit sequence itself via tool calls.

# ── AGENT INSTRUCTION ───────────────────────────────────────────────────────
@{
  hookSpecificOutput = @{
    hookEventName     = "PreCompact"
    additionalContext = @"
CONTEXT COMPACTION IMMINENT. Do these steps NOW via tool calls before context is lost:

STEP 1 — WRITE LEARNINGS
Read this conversation. Find every new convention, gotcha, bug fix, confirmed value, or
architectural decision NOT yet in the Session Learnings Log in .github/copilot-instructions.md.
Append those rows to the table (Date | Category | Topic | Decision | Rationale).
Be specific — real values, real function names, real filenames. Not vague summaries.

STEP 2 — INDEX + PRUNE (run in 'scripts' terminal)
  Set-Location C:\Users\User\source\repos\QIDIStudio
  .\memory_env\Scripts\python.exe memory\extract.py

This will: sync all rows to LanceDB, verify learnings landed, archive them to
memory/session_learnings_archive.md, and prune the table from copilot-instructions.md.

STEP 3 — COMMIT
  git add -A
  git commit --allow-empty -m "docs: pre-compact session learnings [$date]"
"@
  }
} | ConvertTo-Json -Compress
