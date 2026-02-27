$ts   = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$date = Get-Date -Format 'yyyy-MM-dd'
$repo = 'C:\Users\User\source\repos\QIDIStudio'
$log  = Join-Path $repo '.github\hooks\precompact.log'
$py   = Join-Path $repo 'memory_env\Scripts\python.exe'

Add-Content -Path $log -Value "$ts [PreCompact] fired - running autonomous save"

# ── AUTONOMOUS WORK (runs regardless of agent availability) ─────────────────
# These shell commands execute in the system. The agent cannot see their output,
# but they DO run — ensuring files already on disk get indexed and committed
# even if the agent is out of context budget.

Set-Location $repo

# Step A: Re-index all source docs into LanceDB
try {
    $extractResult = & $py memory\extract.py 2>&1
    Add-Content -Path $log -Value "$ts [PreCompact] extract.py: $($extractResult[-1])"
} catch {
    Add-Content -Path $log -Value "$ts [PreCompact] extract.py FAILED: $_"
}

# Step B: Commit whatever is already staged/modified on disk
$status = & git status --porcelain 2>&1
if ($status) {
    & git add -A
    & git commit --allow-empty -m "docs: pre-compact auto-save [$date]"
    Add-Content -Path $log -Value "$ts [PreCompact] committed pending changes"
} else {
    Add-Content -Path $log -Value "$ts [PreCompact] nothing to commit"
}

# ── AGENT INSTRUCTION (injected into compaction context) ────────────────────
# Ask the agent to write any NEW learnings it knows from the conversation.
# The hook already handled extract.py + git commit for what's on disk.
@{
    hookSpecificOutput = @{
        hookEventName     = "PreCompact"
        additionalContext = @"
IMPORTANT: Context is about to be compacted. The precompact hook has already run memory\extract.py and committed any pending file changes. Your job is ONE thing only:

WRITE NEW LEARNINGS: Read this conversation. Identify every new convention, gotcha, bug fix, confirmed value, or architectural decision that is NOT yet in the Session Learnings Log in .github/copilot-instructions.md. Append those rows now. For major discoveries also update docs/QIDISTUDIO_KNOWLEDGE.md.

Be specific — real values, real function names, real filenames. Not vague summaries.

After writing, run in the scripts terminal:
  Set-Location C:\Users\User\source\repos\QIDIStudio
  & $py memory\extract.py
  git add -A
  git commit --allow-empty -m "docs: pre-compact session learnings [$date]"
"@
    }
} | ConvertTo-Json -Compress
