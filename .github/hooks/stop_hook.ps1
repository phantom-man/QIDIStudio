# Stop hook — fires when Claude finishes responding (end of turn).
#
# What this does (silently, no agent intervention required):
#   1. Reads the session_id + transcript_path from stdin JSON.
#   2. Extracts the last assistant message from the transcript JSONL.
#   3. Saves the response to the `responses` table (linked to the prompt via session file).
#   4. Writes today's session stats to memory/_session_stats.txt so the NEXT turn
#      can display them (Stop hook stdout is NOT shown during the current turn).
#   5. Runs extract.py to sync LanceDB with any new archive/compaction content.
#   6. Auto-commits changed memory files to git.
#
# NOTE: Session learnings are NO LONGER written to copilot-instructions.md.
# All learnings flow through the prompts/responses DB → 30-min sync job → LanceDB.
# See memory/setup_tasks.ps1 for the scheduler setup.

$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$date = Get-Date -Format 'yyyy-MM-dd'
$repo = 'C:\Users\User\source\repos\QIDIStudio'
$log = Join-Path $repo '.github\hooks\stop_hook.log'
$py = Join-Path $repo 'memory_env\Scripts\python.exe'
$store = Join-Path $repo 'memory\prompt_store.py'
$tmpDir = Join-Path $repo 'memory'

Add-Content -Path $log -Value "$ts [Stop] fired"

# ── Read stdin JSON (session_id + transcript_path) ───────────────────────────
$sessionId = "unknown"
$transcriptPath = $null
try {
    $stdinRaw = [System.Console]::In.ReadToEnd()
    if ($stdinRaw -and $stdinRaw.Trim() -ne '') {
        $stdinData = $stdinRaw | ConvertFrom-Json -ErrorAction Stop
        $sessionId = if ($stdinData.session_id) { [string]$stdinData.session_id }      else { "unknown" }
        $transcriptPath = if ($stdinData.transcript_path) { [string]$stdinData.transcript_path } else { $null }
    }
}
catch {
    Add-Content -Path $log -Value "$ts [Stop] stdin parse failed: $_"
}

# ── Extract last assistant message from transcript ────────────────────────────
$responseText = ""
if ($transcriptPath -and (Test-Path $transcriptPath)) {
    try {
        # Transcript is JSONL — one JSON object per line, last assistant role is the response
        $lines = Get-Content $transcriptPath -Encoding UTF8 -ErrorAction Stop
        for ($i = $lines.Count - 1; $i -ge 0; $i--) {
            $line = $lines[$i].Trim()
            if (-not $line) { continue }
            try {
                $obj = $line | ConvertFrom-Json -ErrorAction Stop
                if ($obj.role -eq 'assistant') {
                    if ($obj.content -is [string]) {
                        $responseText = $obj.content
                    }
                    elseif ($obj.content -is [System.Array]) {
                        # Content blocks — join text blocks
                        $responseText = ($obj.content | Where-Object { $_.type -eq 'text' } |
                            ForEach-Object { $_.text }) -join "`n"
                    }
                    break
                }
            }
            catch { continue }
        }
        Add-Content -Path $log -Value "$ts [Stop] transcript read OK (len=$($responseText.Length))"
    }
    catch {
        Add-Content -Path $log -Value "$ts [Stop] transcript read failed: $_"
    }
}

# ── Save response to DB ──────────────────────────────────────────────────────
$safeSession = $sessionId -replace '[^a-zA-Z0-9]', '_'
$sessionFile = Join-Path $tmpDir "_session_$safeSession.txt"
$promptId = $null

if (Test-Path $sessionFile) {
    $promptId = (Get-Content $sessionFile -Raw -ErrorAction SilentlyContinue).Trim()
}

if ($promptId -and $responseText -ne "" -and (Test-Path $py)) {
    try {
        # Check if this response is a compaction summary
        $isCompaction = if ($responseText -match 'COMPACTION_SUMMARY') { "--compaction" } else { "" }

        $respFile = Join-Path $tmpDir "_response_tmp_$([System.Guid]::NewGuid()).txt"
        [System.IO.File]::WriteAllText($respFile, $responseText, [System.Text.Encoding]::UTF8)

        & $py -B $store --save-response `
            --prompt-id  $promptId `
            --session-id $sessionId `
            --file       $respFile `
            $isCompaction 2>$null | Out-Null

        Remove-Item $respFile -ErrorAction SilentlyContinue
        Add-Content -Path $log -Value "$ts [Stop] saved response for prompt $promptId"
    }
    catch {
        Add-Content -Path $log -Value "$ts [Stop] DB save response failed: $_"
        Remove-Item $respFile -ErrorAction SilentlyContinue
    }

    # Clean up session file — prevents stale FK on next run
    Remove-Item $sessionFile -ErrorAction SilentlyContinue
}
elseif (-not $promptId) {
    Add-Content -Path $log -Value "$ts [Stop] no session file for session=$sessionId — response not saved"
}

# ── Write daily stats to file (injected into NEXT turn by UserPromptSubmit) ───
if (Test-Path $py) {
    try {
        $statsOut = & $py -B $store --daily-stats 2>$null
        Add-Content -Path $log -Value "$ts [Stop] daily stats written"
        # Also log the stats for direct visibility
        Add-Content -Path $log -Value $statsOut
    }
    catch {
        Add-Content -Path $log -Value "$ts [Stop] daily stats failed: $_"
    }
}

# ── Sync LanceDB (extract.py) ────────────────────────────────────────────────
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

# ── Auto-commit changed memory files ─────────────────────────────────────────
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
