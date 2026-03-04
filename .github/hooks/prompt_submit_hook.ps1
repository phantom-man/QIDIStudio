# UserPromptSubmit hook — semantic memory injection + prompt persistence.
#
# Every time the user sends a prompt this hook:
#   1. Generates a unique PROMPT_RESPONSE_ID (UUID) + saves the prompt to Postgres.
#   2. Persists the prompt text to the `prompts` table for durable knowledge archiving.
#   3. Injects the N most semantically-relevant memories from LanceDB into context.
#   4. Injects today's session stats (written by the previous Stop hook) into context.
#   5. Tells the agent to include the PROMPT_RESPONSE_ID in its reply.
#
# Why the ID?
#   The Stop hook reads the transcript to pair this response back to this prompt.
#   The ID is the join key between the `prompts` and `responses` tables.
#   Including it in the response is belt-and-suspenders — the session file is the
#   authoritative FK source; the ID in the reply is a human-readable audit trail.

$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$logFile = Join-Path $PSScriptRoot "precompact.log"
$repo = 'C:\Users\User\source\repos\QIDIStudio'
$python = Join-Path $repo 'memory_env\Scripts\python.exe'
$inject = Join-Path $repo 'memory\inject.py'
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
        $sessionId = if ($stdinData.session_id) { [string]$stdinData.session_id } else { "unknown" }
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
    [System.IO.File]::WriteAllText($promptFile, $promptText, [System.Text.Encoding]::UTF8)

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

# ── Inject semantically relevant memories ────────────────────────────────────
$memoryContext = ""
$memoryOk = $false

if ((Test-Path $inject) -and (Test-Path $python)) {
    try {
        if ($promptText -ne "") {
            $memoryContext = & $python $inject --prompt $promptText 2>$null
        }
        else {
            $memoryContext = & $python $inject 2>$null
        }
        if ($LASTEXITCODE -eq 0 -and $memoryContext -and $memoryContext.Trim() -ne '') {
            $memoryOk = $true
            Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] memory inject OK"
        }
    }
    catch {
        Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] inject FAILED: $_"
    }
}

# ── Assemble additionalContext ────────────────────────────────────────────────
$additionalContext = if ($memoryOk) {
    $memoryContext
}
else {
    "use Context7. NOTE: persistent memory offline — run: pip install -r memory/requirements.txt"
}

# Append yesterday's / today's session stats if available and fresh (< 24 h)
if (Test-Path $statsFile) {
    try {
        $statsAge = (Get-Date) - (Get-Item $statsFile).LastWriteTime
        if ($statsAge.TotalHours -lt 24) {
            $statsText = Get-Content $statsFile -Raw -ErrorAction Stop
            $additionalContext = $additionalContext + "`n`n" + $statsText.Trim()
        }
    }
    catch { }
}

# Append prompt-ID instruction (belt-and-suspenders — session file is authoritative FK)
$additionalContext += @"

`n━━━ PROMPT TRACKING ━━━
PROMPT_RESPONSE_ID: $promptId
Include this line verbatim at the very end of your response (inside an HTML comment is fine):
  <!-- PROMPT_RESPONSE_ID: $promptId -->
This ID links your response to the persistent knowledge database.
━━━ END TRACKING ━━━
"@

# ── Emit hook response ────────────────────────────────────────────────────────
@{
    hookSpecificOutput = @{
        hookEventName     = 'UserPromptSubmit'
        additionalContext = $additionalContext
    }
} | ConvertTo-Json -Compress
