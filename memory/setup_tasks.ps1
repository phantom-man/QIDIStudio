# memory/setup_tasks.ps1 — Register Windows Task Scheduler tasks for QIDIStudio memory jobs.
#
# Run ONCE as Administrator:
#   powershell -ExecutionPolicy Bypass -File memory\setup_tasks.ps1
#
# Tasks created:
#   QIDIStudio Prompt Sync   — every 30 min, syncs prompts/responses → LanceDB + .md files
#   QIDIStudio LanceDB Dedupe — daily 03:00 AM, deduplicates LanceDB
#   QIDIStudio Prompt Store Setup — runs once on logon to ensure DB tables exist

$repo = 'C:\Users\User\source\repos\QIDIStudio'
$python = "$repo\memory_env\Scripts\python.exe"

# ── Helper ────────────────────────────────────────────────────────────────────
function Register-QidiTask {
    param($Name, $Description, $Script, $Trigger, $ExtraArgs = "")

    $action = New-ScheduledTaskAction `
        -Execute $python `
        -Argument "-B `"$Script`" $ExtraArgs" `
        -WorkingDirectory $repo

    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable:$false `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -MultipleInstances IgnoreNew

    # Run as current user (no password needed for interactive session)
    $principal = New-ScheduledTaskPrincipal `
        -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType S4U `
        -RunLevel Limited

    # Remove existing task if it exists
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue

    Register-ScheduledTask `
        -TaskName    $Name `
        -Description $Description `
        -Action      $action `
        -Trigger     $Trigger `
        -Settings    $settings `
        -Principal   $principal `
        -Force | Out-Null

    Write-Host "Registered: $Name"
}

# ── 1. Prompt Sync (every 30 minutes) ────────────────────────────────────────
$syncTrigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 30) -Once `
    -At (Get-Date).Date  # start from midnight today, repeat every 30 min

Register-QidiTask `
    -Name        "QIDIStudio Prompt Sync" `
    -Description "Syncs new prompt/response pairs from Postgres to LanceDB and regenerates .md files" `
    -Script      "$repo\memory\sync_prompts_to_lancedb.py" `
    -Trigger     $syncTrigger

# ── 2. LanceDB Dedupe (daily at 03:00) ───────────────────────────────────────
$dedupeTrigger = New-ScheduledTaskTrigger -Daily -At "03:00"

Register-QidiTask `
    -Name        "QIDIStudio LanceDB Dedupe" `
    -Description "Daily: deduplicates LanceDB by content hash; re-indexes archive + compaction summaries" `
    -Script      "$repo\memory\daily_lancedb_dedupe.py" `
    -Trigger     $dedupeTrigger

# ── 3. DB Table Setup on logon (idempotent) ───────────────────────────────────
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn

Register-QidiTask `
    -Name        "QIDIStudio Prompt Store Setup" `
    -Description "Ensures prompt_store DB tables exist on logon (idempotent)" `
    -Script      "$repo\memory\prompt_store.py" `
    -Trigger     $logonTrigger `
    -ExtraArgs   "--daily-stats"    # harmless call that runs setup() as side-effect

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Tasks registered:"
Get-ScheduledTask | Where-Object { $_.TaskName -like "QIDIStudio*" } |
Format-Table TaskName, State -AutoSize

Write-Host ""
Write-Host "Run a task immediately with:"
Write-Host "  Start-ScheduledTask -TaskName 'QIDIStudio Prompt Sync'"
Write-Host "  Start-ScheduledTask -TaskName 'QIDIStudio LanceDB Dedupe'"
Write-Host ""
Write-Host "View logs:"
Write-Host "  Get-Content $repo\memory\_dedupe.log"
