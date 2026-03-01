<#
.SYNOPSIS
    Registers the nightly GCS Coldline backup as a Windows Scheduled Task.
    Run once as Administrator.

.USAGE
    powershell -ExecutionPolicy Bypass -File scripts\setup_backup_schedule.ps1
#>

$TASK_NAME = "QIDIStudio - Nightly GCS Backup"
$SCRIPT_PATH = "C:\Users\User\source\repos\QIDIStudio\scripts\gcs_backup.ps1"
$LOG_DIR = "C:\Users\User\AppData\Local\QIDIStudio\backup-logs"

# Ensure log dir exists
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

# Remove existing task if present
if (Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
    Write-Host "Removed existing task."
}

# Action: run powershell with the backup script
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$SCRIPT_PATH`""

# Trigger: daily at 02:00
$trigger = New-ScheduledTaskTrigger -Daily -At "02:00"

# Settings: wake machine, restart on failure, run if missed
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 30) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -MultipleInstances IgnoreNew

# Principal: run as current user, only when logged on (avoids UAC issues with ADC)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

$task = Register-ScheduledTask `
    -TaskName $TASK_NAME `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Nightly rclone sync of User profile + repos to gs://qidistudio-machine-backup (Coldline storage)"

if ($task) {
    Write-Host "Scheduled task '$TASK_NAME' registered."
    Write-Host "Runs daily at 02:00. Logs -> $LOG_DIR"
    Write-Host ""
    Write-Host "To run a test backup now:"
    Write-Host "  powershell -File `"$SCRIPT_PATH`" -Verbose"
}
else {
    Write-Error "Failed to register scheduled task."
}
