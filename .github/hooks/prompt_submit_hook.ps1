# UserPromptSubmit hook — semantic memory injection using the user's prompt text.
# Reads the prompt from stdin JSON, passes it to inject.py for targeted retrieval.
# Result: only the N most relevant memory chunks land in context — NOT a full table scan.

$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$logFile = Join-Path $PSScriptRoot "precompact.log"
$repo = 'C:\Users\User\source\repos\QIDIStudio'
$python = Join-Path $repo 'memory_env\Scripts\python.exe'
$inject = Join-Path $repo 'memory\inject.py'

Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] fired"

# ── Read prompt text from stdin JSON ────────────────────────────────────────
# VS Code passes: { "prompt": "user message text", ... } on stdin
$promptText = ""
try {
    $stdinRaw = [System.Console]::In.ReadToEnd()
    if ($stdinRaw -and $stdinRaw.Trim() -ne '') {
        $stdinData = $stdinRaw | ConvertFrom-Json -ErrorAction Stop
        $promptText = if ($stdinData.prompt) { [string]$stdinData.prompt } else { "" }
    }
}
catch {
    Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] stdin parse failed: $_"
}

# ── Inject semantically relevant memories ───────────────────────────────────
$result = $null
$success = $false

if ((Test-Path $inject) -and (Test-Path $python)) {
    try {
        if ($promptText -ne "") {
            # FAST PATH: semantic search — only N relevant chunks, no full GCS table scan
            $result = & $python $inject --prompt $promptText 2>$null
            Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] semantic inject OK (prompt len=$($promptText.Length))"
        }
        else {
            # FALLBACK: no prompt text from stdin — call with no args (returns stub, no GCS scan)
            $result = & $python $inject 2>$null
            Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] fallback inject (no prompt received)"
        }
        if ($LASTEXITCODE -eq 0 -and $result -and $result.Trim() -ne '') {
            $success = $true
        }
    }
    catch {
        Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] inject FAILED: $_"
    }
}

if ($success) {
    Write-Output $result
}
else {
    Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] falling back to static Context7 hint"
    @{
        hookSpecificOutput = @{
            hookEventName     = 'UserPromptSubmit'
            additionalContext = 'use Context7. NOTE: persistent memory is offline - run: pip install -r memory/requirements.txt'
        }
    } | ConvertTo-Json -Compress
}
