# PreToolUse - LanceDB semantic memory injection
# Reads transcript_path from stdin, extracts last human message,
# runs inject.py, emits hookSpecificOutput.additionalContext

$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$hooksDir = 'C:\Users\User\source\repos\QIDIStudio\.github\hooks'
$logFile = Join-Path $hooksDir 'precompact.log'
$repo = 'C:\Users\User\source\repos\QIDIStudio'
$python = Join-Path $repo 'memory_env\Scripts\python.exe'
$inject = Join-Path $repo 'memory\inject.py'
$dedupFile = Join-Path $hooksDir '_last_injected.txt'

# Heartbeat - confirms hook was reached
Add-Content -Path $logFile -Value "$ts [PreTool] hook invoked"

# Read one JSON line from stdin (VS Code never closes the pipe)
$transcriptPath = ''
$toolName = ''
try {
    $task = [System.Console]::In.ReadLineAsync()
    $raw = if ($task.Wait(3000)) { $task.Result } else { '' }
    if ($raw -and $raw.Trim()) {
        $data = $raw | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($data) {
            $toolName = [string]$data.tool_name
            $transcriptPath = [string]$data.transcript_path
        }
        Add-Content -Path $logFile -Value "$ts [PreTool] stdin ok tool=$toolName transcript=$transcriptPath"
    }
    else {
        Add-Content -Path $logFile -Value "$ts [PreTool] stdin empty or timeout"
    }
}
catch {
    Add-Content -Path $logFile -Value "$ts [PreTool] stdin error: $_"
}

# Guard: need a transcript file
if ((-not $transcriptPath) -or (-not (Test-Path $transcriptPath))) {
    Add-Content -Path $logFile -Value "$ts [PreTool] no transcript - skipping"
    Write-Output '{}'
    exit 0
}

# ── Extract last human message + log protocol enforcement ─────────────────────
# 1. Find the last user.message in the transcript and record its line index.
# 2. Scan every line AFTER that index for a create_file call targeting logs/*.md
#    (the canonical session log pattern: logs/YYYY-MM-DD_HHMMSS_<slug>.md).
#    If no such call exists yet this turn → the log hasn't been created → warn.
$logGuardMessage = ''
$today = Get-Date -Format 'yyyy-MM-dd'
$promptText = ''
$lastUserLineIdx = -1

try {
    $lines = [System.IO.File]::ReadAllLines($transcriptPath)

    # Walk backwards to find the last user message and its line index
    for ($i = $lines.Length - 1; $i -ge 0; $i--) {
        $line = $lines[$i].Trim()
        if (-not $line) { continue }
        $entry = $line | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($entry -and $entry.type -eq 'user.message' -and $entry.data -and $entry.data.content) {
            $promptText = [string]$entry.data.content
            $lastUserLineIdx = $i
            break
        }
    }

    # Scan forward from that point for a create_file call to logs/YYYY-MM-DD_*.md
    $sessionLogCreated = $false
    if ($lastUserLineIdx -ge 0) {
        $logPattern = [System.Text.RegularExpressions.Regex]::new(
            'create_file.*logs[\\/]\d{4}-\d{2}-\d{2}_\d{6}',
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
        )
        for ($i = $lastUserLineIdx + 1; $i -lt $lines.Length; $i++) {
            if ($logPattern.IsMatch($lines[$i])) {
                $sessionLogCreated = $true
                break
            }
        }
    }

    if ($sessionLogCreated) {
        Add-Content -Path $logFile -Value "$ts [PreTool] session log already created this turn — guard OK"
    }
    else {
        $logGuardMessage = @(
            "STOP -- MANDATORY PROTOCOL VIOLATION DETECTED",
            "You are about to run a tool WITHOUT first creating a session log file.",
            "This violates the PROMPT EXECUTION PROTOCOL in copilot-instructions.md (Phase 0, Step 0.2).",
            "",
            "The transcript shows NO create_file call targeting logs/YYYY-MM-DD_HHMMSS_<slug>.md",
            "has been made since the current prompt arrived. You have not created the session log yet.",
            "",
            "STOP. Your next action MUST be:",
            "  1. Scan logs/ for OPEN logs (find files with '- [ ]' AND '## Status: OPEN').",
            "     Ask user YES/NO to inherit before continuing.",
            "  2. Create the log file NOW via create_file:",
            "       Path:  logs/${today}_<HHMMSS>_<3-6-word-slug>.md",
            "       (Get time: Get-Date -Format 'HH:mm:ss' then strip colons for filename)",
            "       Content: canonical template with Task Checklist + ## Status: OPEN",
            "  3. ONLY THEN run any other tool.",
            "",
            "Do NOT proceed with the currently requested tool call first.",
            "STOP -- END MANDATORY PROTOCOL REMINDER"
        ) -join "`n"
        Add-Content -Path $logFile -Value "$ts [PreTool] NO session log this turn — log guard triggered"
    }
}
catch {
    Add-Content -Path $logFile -Value "$ts [PreTool] transcript parse error: $_"
}

if (-not $promptText) {
    Add-Content -Path $logFile -Value "$ts [PreTool] no human message - skipping"
    Write-Output '{}'
    exit 0
}

# Dedup: skip memory injection if same prompt was already injected this turn,
# but do NOT skip if the log guard needs to fire (we want it on every tool call
# until the session log is actually created).
$fp = "$($promptText.Length):$($promptText.Substring(0, [math]::Min(80, $promptText.Length)))"
$lastFp = if (Test-Path $dedupFile) { (Get-Content $dedupFile -Raw).Trim() } else { '' }
$skipMemoryInject = ($fp -eq $lastFp)
if ($skipMemoryInject -and -not $logGuardMessage) {
    Add-Content -Path $logFile -Value "$ts [PreTool] same prompt - already injected (no guard needed)"
    Write-Output '{}'
    exit 0
}
if ($skipMemoryInject) {
    Add-Content -Path $logFile -Value "$ts [PreTool] same prompt - skipping memory inject but guard still active"
}

# Guard: python must exist
if (-not (Test-Path $python)) {
    Add-Content -Path $logFile -Value "$ts [PreTool] python not found"
    # Still emit guard if needed
    if ($logGuardMessage) {
        @{ hookSpecificOutput = @{ hookEventName = 'PreToolUse'; additionalContext = $logGuardMessage } } | ConvertTo-Json -Compress -Depth 5
    }
    else { Write-Output '{}' }
    exit 0
}

# Run inject.py (skip if same prompt already injected this turn)
$additionalContext = ''
if (-not $skipMemoryInject) {
    $tmpPrompt = [System.IO.Path]::Combine(
        [System.IO.Path]::GetTempPath(),
        "pretool_$([System.Guid]::NewGuid().ToString('N')).txt"
    )
    [System.IO.File]::WriteAllText($tmpPrompt, $promptText, (New-Object System.Text.UTF8Encoding($false)))
    try {
        $result = & $python -B $inject --prompt-file $tmpPrompt 2>$null
        if ($result) {
            $parsed = $result | ConvertFrom-Json -ErrorAction SilentlyContinue
            if ($parsed -and $parsed.hookSpecificOutput -and $parsed.hookSpecificOutput.additionalContext) {
                $additionalContext = [string]$parsed.hookSpecificOutput.additionalContext
            }
        }
        if ($additionalContext) {
            Add-Content -Path $logFile -Value "$ts [Inject/PreTool] injected $($additionalContext.Length) chars"
        }
        else {
            Add-Content -Path $logFile -Value "$ts [Inject/PreTool] no relevant memory"
        }
    }
    catch {
        Add-Content -Path $logFile -Value "$ts [Inject/PreTool] error: $_"
    }
    finally {
        Remove-Item $tmpPrompt -ErrorAction SilentlyContinue
    }
}

# Save fingerprint (always, so dedup tracks even guard-only turns)
[System.IO.File]::WriteAllText($dedupFile, $fp, (New-Object System.Text.UTF8Encoding($false)))

# Emit
if ($additionalContext -or $logGuardMessage) {
    $combined = if ($logGuardMessage -and $additionalContext) {
        "$logGuardMessage`n`n$additionalContext"
    }
    elseif ($logGuardMessage) {
        $logGuardMessage
    }
    else {
        $additionalContext
    }
    $out = @{
        hookSpecificOutput = @{
            hookEventName     = 'PreToolUse'
            additionalContext = $combined
        }
    }
    Write-Output ($out | ConvertTo-Json -Compress -Depth 5)
}
else {
    Write-Output '{}'
}
