# SessionStart hook — semantic memory injection.
#
# Fires once at the beginning of every agent session.
# Injects the N most relevant memories from LanceDB as additionalContext,
# which VS Code Copilot places directly into the model's context window.
#
# NOTE: UserPromptSubmit does NOT support hookSpecificOutput.additionalContext
# (it uses the common output format only, per VS Code docs).
# SessionStart IS one of the supported hook events for additionalContext injection.

$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$logFile = Join-Path $PSScriptRoot "precompact.log"
$repo = 'C:\Users\User\source\repos\QIDIStudio'
$python = Join-Path $repo 'memory_env\Scripts\python.exe'
$inject = Join-Path $repo 'memory\inject.py'

Add-Content -Path $logFile -Value "$ts [SessionStart] fired"

# ── Inject semantically relevant memories (no prompt available at session start) ──
$memoryContext = ""
$memoryOk = $false

if ((Test-Path $inject) -and (Test-Path $python)) {
    try {
        $memoryContext = & $python $inject 2>$null
        if ($LASTEXITCODE -eq 0 -and $memoryContext -and $memoryContext.Trim() -ne '') {
            $memoryOk = $true
            Add-Content -Path $logFile -Value "$ts [SessionStart] memory inject OK ($($memoryContext.Length) chars)"
        }
        else {
            Add-Content -Path $logFile -Value "$ts [SessionStart] memory inject returned empty (exit=$LASTEXITCODE)"
        }
    }
    catch {
        Add-Content -Path $logFile -Value "$ts [SessionStart] inject FAILED: $_"
    }
}
else {
    Add-Content -Path $logFile -Value "$ts [SessionStart] python or inject.py not found"
}

$additionalContext = if ($memoryOk) {
    $memoryContext
}
else {
    "NOTE: QIDIStudio persistent memory offline. Run: memory_env\Scripts\python.exe memory\inject.py"
}

# ── Emit hook response ────────────────────────────────────────────────────────
@{
    hookSpecificOutput = @{
        hookEventName     = 'SessionStart'
        additionalContext = $additionalContext
    }
} | ConvertTo-Json -Compress
