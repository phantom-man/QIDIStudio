# UserPromptSubmit hook — prompt persistence + session tracking.
#
# Every time the user sends a prompt this hook:
#   1. Generates a unique PROMPT_RESPONSE_ID (UUID) + saves the prompt to Postgres.
#   2. Persists the prompt text to the `prompts` table for durable knowledge archiving.
#   3. Writes a session file (_session_<id>.txt) so Stop hook can link responses back.
#   4. Optionally shows a popup with today's session stats.
#
# NOTE: UserPromptSubmit uses the COMMON output format only (per VS Code docs).
#   hookSpecificOutput.additionalContext is NOT supported here and is silently dropped.
#   Static knowledge base injection → SessionStart hook (session_start_hook.ps1)
#   Semantic/per-prompt LanceDB injection → future PreToolUse hook
#
# Why the ID?
#   The Stop hook reads the transcript to pair this response back to this prompt.
#   The ID is the join key between the `prompts` and `responses` tables.

$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$logFile = Join-Path $PSScriptRoot "precompact.log"
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent  # hooks → .github → repo root
$python = Join-Path $repo 'memory_env\Scripts\python.exe'
$store = Join-Path $repo 'memory\prompt_store.py'
$statsFile = Join-Path $repo 'memory\_session_stats.txt'
$tmpDir = Join-Path $repo 'memory'

Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] fired"

# ── Read stdin JSON ──────────────────────────────────────────────────────────
$promptText = ""
$sessionId = "unknown"
try {
    $stdinRaw = [System.Console]::In.ReadToEnd()
    if ($stdinRaw -and $stdinRaw.Trim() -ne '') {
        $stdinData = $stdinRaw | ConvertFrom-Json -ErrorAction Stop
        $promptText = if ($stdinData.prompt) { [string]$stdinData.prompt }     else { "" }
        $sessionId = if ($stdinData.sessionId) { [string]$stdinData.sessionId } else { "unknown" }
    }
}
catch {
    Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] stdin parse failed: $_"
}

# ── Generate prompt ID + persist prompt to DB ────────────────────────────────
$promptId = [System.Guid]::NewGuid().ToString()
$promptFile = Join-Path $tmpDir "_prompt_tmp_$promptId.txt"
$safeSession = $sessionId -replace '[^a-zA-Z0-9]', '_'
$sessionFile = Join-Path $tmpDir "_session_$safeSession.txt"

try {
    [System.IO.File]::WriteAllText($promptFile, $promptText, (New-Object System.Text.UTF8Encoding($false)))

    if (Test-Path $python) {
        & $python -B $store --save-prompt `
            --prompt-id  $promptId `
            --session-id $sessionId `
            --file       $promptFile 2>$null | Out-Null
        Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] saved prompt $promptId"
    }

    # Session file lets Stop hook link the response back to this prompt (FK)
    Set-Content -Path $sessionFile -Value $promptId -Encoding UTF8

    Remove-Item $promptFile -ErrorAction SilentlyContinue
}
catch {
    Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] DB save failed: $_"
    Remove-Item $promptFile -ErrorAction SilentlyContinue
}

# ── Session stats (written by previous Stop hook) ──────────────────────────
$additionalContext = ""

# Append yesterday's / today's session stats if available and fresh (< 24 h)
$statsText = $null
if (Test-Path $statsFile) {
    try {
        $statsAge = (Get-Date) - (Get-Item $statsFile).LastWriteTime
        if ($statsAge.TotalHours -lt 24) {
            $statsText = Get-Content $statsFile -Raw -Encoding UTF8 -ErrorAction Stop
            $additionalContext = $additionalContext + "`n`n" + $statsText.Trim()
            Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] session stats injected (age=$([math]::Round($statsAge.TotalMinutes,1))min)"
        }
        else {
            Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] session stats skipped (age=$([math]::Round($statsAge.TotalHours,1))h - too old)"
        }
    }
    catch {
        Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] session stats read failed: $_"
    }
}
else {
    Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] session stats not found (no stop hook run yet)"
}

# ── Scrollable popup notification ────────────────────────────────────────────
try {
    $popupBody = if ($statsText) { $statsText.Trim() } else { "No stats yet for today." }
    $promptCount = if ($statsText -match '\((\d+) prompts today\)') { $Matches[1] } else { "?" }
    $popupScript = Join-Path $repo 'memory\show_stats_popup.ps1'

    if (Test-Path $popupScript) {
        # Launch in a background job so the hook returns immediately
        Start-Process powershell.exe -ArgumentList @(
            '-ExecutionPolicy', 'Bypass',
            '-NonInteractive',
            '-File', $popupScript,
            '-Title', "QIDIStudio - $promptCount prompts today",
            '-Body', $popupBody
        ) -WindowStyle Hidden
        Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] popup launched"
    }
}
catch {
    Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] popup failed: $_"
}

# Append prompt-ID instruction (belt-and-suspenders - session file is authoritative FK)
$additionalContext += @"

`n━━━ PROMPT TRACKING ━━━
PROMPT_RESPONSE_ID: $promptId
Include this line verbatim at the very end of your response (inside an HTML comment is fine):
  <!-- PROMPT_RESPONSE_ID: $promptId -->
This ID links your response to the persistent knowledge database.
━━━ END TRACKING ━━━
"@

# ── Emit hook response (common format only — hookSpecificOutput not supported for UserPromptSubmit) ──
# VS Code docs: UserPromptSubmit uses the common output format only.
# additionalContext is populated for logging/tracking only; not emitted.
@{} | ConvertTo-Json -Compress
