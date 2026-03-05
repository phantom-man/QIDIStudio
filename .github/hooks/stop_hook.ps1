# Stop hook — fires when Claude finishes responding (end of turn).
#
# What this does (silently, no agent intervention required):
#   1. Reads the session_id + transcript_path from stdin JSON.
#   2. Extracts the last user + assistant messages from the transcript JSONL.
#   3. Saves prompt+response pair to Postgres (self-contained — no UserPromptSubmit needed).
#   4. Writes today's session stats to memory/_session_stats.txt.
#   5. Runs extract.py to sync LanceDB with any new archive/compaction content.
#   6. Runs sync_prompts_to_lancedb.py to push new Postgres pairs to LanceDB.
#   7. Auto-commits changed memory files to git.
#
# NOTE: UserPromptSubmit is permanently removed (VS Code 1.109 crash bug).
# The Stop hook is now fully self-contained for all DB writes.

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

# ── Extract last user + assistant messages from transcript ────────────────────
$responseText = ""
$promptText = ""
if ($transcriptPath -and (Test-Path $transcriptPath)) {
    try {
        $lines = Get-Content $transcriptPath -Encoding UTF8 -ErrorAction Stop
        $foundAssistant = $false
        $foundUser = $false
        for ($i = $lines.Count - 1; $i -ge 0; $i--) {
            $line = $lines[$i].Trim()
            if (-not $line) { continue }
            try {
                $obj = $line | ConvertFrom-Json -ErrorAction Stop
                if (-not $foundAssistant -and $obj.role -eq 'assistant') {
                    if ($obj.content -is [string]) {
                        $responseText = $obj.content
                    }
                    elseif ($obj.content -is [System.Array]) {
                        $responseText = ($obj.content | Where-Object { $_.type -eq 'text' } |
                            ForEach-Object { $_.text }) -join "`n"
                    }
                    $foundAssistant = $true
                }
                elseif ($foundAssistant -and -not $foundUser -and $obj.role -eq 'user') {
                    if ($obj.content -is [string]) {
                        $promptText = $obj.content
                    }
                    elseif ($obj.content -is [System.Array]) {
                        $promptText = ($obj.content | Where-Object { $_.type -eq 'text' } |
                            ForEach-Object { $_.text }) -join "`n"
                    }
                    $foundUser = $true
                    break
                }
            }
            catch { continue }
        }
        Add-Content -Path $log -Value "$ts [Stop] transcript read OK (prompt=$($promptText.Length) response=$($responseText.Length))"
    }
    catch {
        Add-Content -Path $log -Value "$ts [Stop] transcript read failed: $_"
    }
}

# ── Save prompt + response to DB (self-contained, no UserPromptSubmit needed) ─
if ($responseText -ne "" -and (Test-Path $py)) {
    $promptId = [System.Guid]::NewGuid().ToString()
    try {
        # 1. Write prompt row first
        if ($promptText -ne "") {
            $promptFile = Join-Path $tmpDir "_prompt_tmp_$([System.Guid]::NewGuid()).txt"
            [System.IO.File]::WriteAllText($promptFile, $promptText, (New-Object System.Text.UTF8Encoding($false)))

            & $py -B $store --save-prompt `
                --prompt-id  $promptId `
                --session-id $sessionId `
                --file       $promptFile 2>$null | Out-Null

            Remove-Item $promptFile -ErrorAction SilentlyContinue
            Add-Content -Path $log -Value "$ts [Stop] saved prompt $promptId"
        }
        else {
            # No user message found; write a placeholder so the FK is satisfied
            $placeholderFile = Join-Path $tmpDir "_prompt_tmp_$([System.Guid]::NewGuid()).txt"
            [System.IO.File]::WriteAllText($placeholderFile, "[session $sessionId — prompt not captured]", (New-Object System.Text.UTF8Encoding($false)))
            & $py -B $store --save-prompt `
                --prompt-id  $promptId `
                --session-id $sessionId `
                --file       $placeholderFile 2>$null | Out-Null
            Remove-Item $placeholderFile -ErrorAction SilentlyContinue
            Add-Content -Path $log -Value "$ts [Stop] saved placeholder prompt $promptId"
        }

        # 2. Write response row (linked to prompt above)
        $isCompaction = if ($responseText -match 'COMPACTION_SUMMARY') { "--compaction" } else { "" }
        $respFile = Join-Path $tmpDir "_response_tmp_$([System.Guid]::NewGuid()).txt"
        [System.IO.File]::WriteAllText($respFile, $responseText, (New-Object System.Text.UTF8Encoding($false)))

        & $py -B $store --save-response `
            --prompt-id  $promptId `
            --session-id $sessionId `
            --file       $respFile `
            $isCompaction 2>$null | Out-Null

        Remove-Item $respFile -ErrorAction SilentlyContinue
        Add-Content -Path $log -Value "$ts [Stop] saved response for prompt $promptId"
    }
    catch {
        Add-Content -Path $log -Value "$ts [Stop] DB save failed: $_"
        Remove-Item $promptFile -ErrorAction SilentlyContinue
        Remove-Item $respFile -ErrorAction SilentlyContinue
    }
}
else {
    Add-Content -Path $log -Value "$ts [Stop] no response text — DB write skipped (session=$sessionId)"
}

# ── Write daily stats to file (for visibility in log) ────────────────────────
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

# ── Sync LanceDB (extract.py — static docs) ─────────────────────────────────
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

# ── Sync prompts/responses Postgres → LanceDB (replaces 30-min scheduler) ───
$syncScript = Join-Path $repo 'memory\sync_prompts_to_lancedb.py'
if ((Test-Path $syncScript) -and (Test-Path $py)) {
    try {
        & $py -B $syncScript >> $log 2>&1
        Add-Content -Path $log -Value "$ts [Stop] prompt sync done"
    }
    catch {
        Add-Content -Path $log -Value "$ts [Stop] prompt sync FAILED: $_"
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
