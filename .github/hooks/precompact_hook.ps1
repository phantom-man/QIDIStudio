$ts   = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$date = Get-Date -Format 'yyyy-MM-dd'
$repo = 'C:\Users\User\source\repos\QIDIStudio'
$log  = Join-Path $repo '.github\hooks\precompact.log'

Add-Content -Path $log -Value "$ts [PreCompact] fired — injecting Save This instruction"

# Output JSON to stdout — additionalContext is injected into the agent conversation
# The AGENT must extract learnings and write files; the hook cannot do this itself.
# (Shell actions in hooks are invisible to the agent — only stdout JSON is injected.)
@{
    hookSpecificOutput = @{
        hookEventName     = "PreCompact"
        additionalContext = @"
IMPORTANT: Context is about to be compacted. You MUST now run the Save This Protocol before anything else.

STEP 1 — EXTRACT LEARNINGS: Read this entire conversation. Identify every new convention, gotcha, bug fix, confirmed value, architectural decision, or workflow rule discovered this session.

STEP 2 — WRITE TO FILES: Append new rows to the Session Learnings Log table in .github/copilot-instructions.md. For major discoveries (new gotchas, architecture changes), also update the relevant section in docs/QIDISTUDIO_KNOWLEDGE.md. Be specific: real values, real function names, real filenames. Not vague summaries.

STEP 3 — SYNC TO LANCEDB: Run this in the 'scripts' terminal:
  Set-Location C:\Users\User\source\repos\QIDIStudio
  & 'C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe' memory\extract.py

STEP 4 — COMMIT:
  Set-Location C:\Users\User\source\repos\QIDIStudio
  git add -A
  git commit --allow-empty -m "docs: pre-compact session learnings [$date]"

Do all four steps NOW, before the context window is compacted.
"@
    }
} | ConvertTo-Json -Compress
