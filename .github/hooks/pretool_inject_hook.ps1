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

# ── Log protocol enforcement ──────────────────────────────────────────────────
# Check whether a session log was created in the last 90 minutes.
# If not, prepend a hard-stop reminder to every tool call's context.
$logGuardMessage = ''
$logsDir = Join-Path $repo 'logs'
$cutoff = (Get-Date).AddMinutes(-90)
$today = Get-Date -Format 'yyyy-MM-dd'
$recentLog = $null
if (Test-Path $logsDir) {
    $recentLog = Get-ChildItem -Path $logsDir -Filter "$today*.md" -ErrorAction SilentlyContinue |
        Where-Object { $_.CreationTime -ge $cutoff -or $_.LastWriteTime -ge $cutoff } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}
if (-not $recentLog) {
    $logGuardMessage = @"
⛔⛔⛔ MANDATORY PROTOCOL VIOLATION DETECTED ⛔⛔⛔
You are about to run a tool WITHOUT first creating a session log file.
This violates the PROMPT EXECUTION PROTOCOL in copilot-instructions.md (Phase 0, Step 0.2).

BEFORE running ANY tool you MUST:
  1. Check logs/ for unfinished tasks (grep for '- [ ]' + '## Status: OPEN')
  2. Create a log file: logs/$today_HHMMSS_<slug>.md  using create_file
     Template: # Log: <title> / **Date:** / **Time:** / **Model:** Claude Sonnet 4.6 /
               **Prompt Summary:** / ## Task Checklist / ## Status: OPEN
  3. THEN proceed with the actual work

Do NOT skip this. Do NOT continue with the current tool call.
Create the session log NOW.
⛔⛔⛔ END MANDATORY PROTOCOL REMINDER ⛔⛔⛔
"@
    Add-Content -Path $logFile -Value "$ts [PreTool] NO SESSION LOG — log guard triggered"
} else {
    Add-Content -Path $logFile -Value "$ts [PreTool] session log found: $($recentLog.Name)"
}

# Extract last human message from JSONL transcript
# Format: {"type":"user.message","data":{"content":"..."},...}
$promptText = ''
try {
    $lines = [System.IO.File]::ReadAllLines($transcriptPath)
    for ($i = $lines.Length - 1; $i -ge 0; $i--) {
        $line = $lines[$i].Trim()
        if (-not $line) { continue }
        $entry = $line | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($entry -and $entry.type -eq 'user.message' -and $entry.data -and $entry.data.content) {
            $promptText = [string]$entry.data.content
            break
        }
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

# Dedup: skip if same prompt was already injected this turn
$fp = "$($promptText.Length):$($promptText.Substring(0, [math]::Min(80, $promptText.Length)))"
$lastFp = if (Test-Path $dedupFile) { (Get-Content $dedupFile -Raw).Trim() } else { '' }
if ($fp -eq $lastFp) {
    Add-Content -Path $logFile -Value "$ts [PreTool] same prompt - already injected"
    Write-Output '{}'
    exit 0
}

# Guard: python must exist
if (-not (Test-Path $python)) {
    Add-Content -Path $logFile -Value "$ts [PreTool] python not found"
    Write-Output '{}'
    exit 0
}

# Write prompt to temp file
$tmpPrompt = [System.IO.Path]::Combine(
    [System.IO.Path]::GetTempPath(),
    "pretool_$([System.Guid]::NewGuid().ToString('N')).txt"
)
[System.IO.File]::WriteAllText($tmpPrompt, $promptText, (New-Object System.Text.UTF8Encoding($false)))

# Run inject.py
$additionalContext = ''
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

# Cleanup + save fingerprint
Remove-Item $tmpPrompt -ErrorAction SilentlyContinue
[System.IO.File]::WriteAllText($dedupFile, $fp, (New-Object System.Text.UTF8Encoding($false)))

# Emit
if ($additionalContext -or $logGuardMessage) {
    $combined = if ($logGuardMessage -and $additionalContext) {
        "$logGuardMessage`n`n$additionalContext"
    } elseif ($logGuardMessage) {
        $logGuardMessage
    } else {
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
