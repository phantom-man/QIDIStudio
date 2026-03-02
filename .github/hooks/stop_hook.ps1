# Stop hook — fires when Claude finishes responding (end of turn).
#
# What this does (silently, no agent intervention required):
#   1. Harvest compaction summaries from ~/.claude/projects/<QIDIStudio>/
#      session-memory/summary.md — fills any knowledge holes from compaction.
#   2. Run extract.py to sync the latest state to LanceDB (indexes any new
#      learnings the agent wrote, clears compaction flag if pending).
#   3. Auto-commit copilot-instructions.md + archives if anything changed.
#
# This replaces the heavy steps that used to block the PreCompact flow.
# PreCompact now only writes a lightweight flag; all heavy work happens here.

$ts   = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$date = Get-Date -Format 'yyyy-MM-dd'
$repo = 'C:\Users\User\source\repos\QIDIStudio'
$log  = Join-Path $repo '.github\hooks\stop_hook.log'
$py   = Join-Path $repo 'memory_env\Scripts\python.exe'

Add-Content -Path $log -Value "$ts [Stop] fired"

# ── 1. Harvest compaction summaries ──────────────────────────────────────────
# Grabs ~/.claude/projects/QIDIStudio/*/session-memory/summary.md written
# since last harvest and appends to memory/compaction_summaries.md.
$harvest = Join-Path $repo 'memory\harvest_summaries.py'
if ((Test-Path $harvest) -and (Test-Path $py)) {
    try {
        & $py $harvest >> $log 2>&1
        Add-Content -Path $log -Value "$ts [Stop] harvest done"
    }
    catch {
        Add-Content -Path $log -Value "$ts [Stop] harvest FAILED: $_"
    }
}

# ── 2. Sync LanceDB ───────────────────────────────────────────────────────────
# Runs extract.py which: indexes all source files, verifies learnings,
# archives pruned rows, clears the compaction flag if pending.
$extract = Join-Path $repo 'memory\extract.py'
if ((Test-Path $extract) -and (Test-Path $py)) {
    try {
        & $py $extract >> $log 2>&1
        Add-Content -Path $log -Value "$ts [Stop] extract done"
    }
    catch {
        Add-Content -Path $log -Value "$ts [Stop] extract FAILED: $_"
    }
}

# ── 3. Auto-commit changed memory files ──────────────────────────────────────
Push-Location $repo
try {
    $tracked = @(
        '.github/copilot-instructions.md',
        'memory/session_learnings_archive.md',
        'memory/compaction_summaries.md'
    )
    $changed = git status --porcelain -- $tracked 2>$null
    if ($changed) {
        git add -- $tracked 2>$null
        git commit -m "chore(memory): stop-hook auto-sync [$date]" 2>$null
        Add-Content -Path $log -Value "$ts [Stop] committed changes"
    }
    else {
        Add-Content -Path $log -Value "$ts [Stop] no changes to commit"
    }
}
catch {
    Add-Content -Path $log -Value "$ts [Stop] commit FAILED: $_"
}
finally {
    Pop-Location
}

# Output nothing — allow Claude to stop normally (no JSON needed for Stop hook)
