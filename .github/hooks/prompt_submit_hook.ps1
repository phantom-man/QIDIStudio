# UserPromptSubmit hook — injects session memories + "use Context7" into every prompt
$ts      = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$logFile = Join-Path $PSScriptRoot "precompact.log"
$repo    = 'C:\Users\User\source\repos\QIDIStudio'
$python  = 'C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe'
$inject  = Join-Path $repo 'memory\inject.py'

Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] fired"

# Try to inject memories from LanceDB
$result  = $null
$success = $false
if ((Test-Path $inject) -and (Test-Path $python)) {
    try {
        $result = & $python $inject 2>$null
        if ($LASTEXITCODE -eq 0 -and $result -and $result.Trim() -ne '') {
            $success = $true
            Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] memory inject OK"
        }
    } catch {
        Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] memory inject FAILED: $_"
    }
}

if ($success) {
    # inject.py already returns valid hook JSON — forward it directly
    Write-Output $result
} else {
    # Fallback: static "use Context7" (memory module not installed or failed)
    Add-Content -Path $logFile -Value "$ts [UserPromptSubmit] falling back to static Context7 hint"
    $fallbackMsg = 'use Context7. NOTE: persistent memory is offline - run: pip install -r memory/requirements.txt'
    @{
        hookSpecificOutput = @{
            hookEventName     = 'UserPromptSubmit'
            additionalContext = $fallbackMsg
        }
    } | ConvertTo-Json -Compress
}
