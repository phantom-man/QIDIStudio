<#
.SYNOPSIS
    Nightly full-machine backup to GCS Coldline via rclone.
    Scheduled by setup_backup_schedule.ps1 — do not move this file.

.USAGE
    Run manually:   powershell -File scripts\gcs_backup.ps1
    With verbose:   powershell -File scripts\gcs_backup.ps1 -Verbose
#>
param(
    [switch]$Verbose
)

$ErrorActionPreference = "Continue"

$RCLONE = "C:\Users\User\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.73.1-windows-amd64\rclone.exe"
$REMOTE = "gcs-backup:qidistudio-machine-backup"
$LOG_DIR = "C:\Users\User\AppData\Local\QIDIStudio\backup-logs"
$LOG_FILE = Join-Path $LOG_DIR "backup-$(Get-Date -Format 'yyyyMMdd').log"

# Create log dir
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Add-Content -Path $LOG_FILE -Value $line
    if ($Verbose) { Write-Host $line }
}

Log "=== Backup started ==="
Log "Rclone : $RCLONE"
Log "Remote : $REMOTE"

# ── Directories to back up ────────────────────────────────────────────────────
$SOURCES = @(
    @{ Src = "C:\Users\User"; Dst = "users/User" },
    @{ Src = "C:\Users\User\source\repos"; Dst = "repos" },
    @{ Src = "C:\ProgramData\QIDIStudio"; Dst = "programdata" }
)

# ── Global excludes (system noise) ───────────────────────────────────────────
$EXCLUDES = @(
    "--exclude", "AppData/Local/Temp/**",
    "--exclude", "AppData/Local/Microsoft/Windows/**",
    "--exclude", "AppData/LocalLow/**",
    "--exclude", ".git/**",
    "--exclude", "node_modules/**",
    "--exclude", "__pycache__/**",
    "--exclude", "*.pyc",
    "--exclude", ".venv/**",
    "--exclude", "memory_env/**",
    "--exclude", "bpy_env/**",
    "--exclude", "build/**"
    # data/lancedb excluded from repo — store is on GCS (gs://qidistudio-lancedb/lancedb)
)

$RCLONE_FLAGS = @(
    "--transfers", "8",
    "--checkers", "16",
    "--stats", "60s",
    "--log-level", "INFO",
    "--log-file", $LOG_FILE,
    "--backup-dir", "$REMOTE/deleted/$(Get-Date -Format 'yyyyMMdd')"
)

$overall_ok = $true

foreach ($s in $SOURCES) {
    if (-not (Test-Path $s.Src)) {
        Log "SKIP (not found): $($s.Src)"
        continue
    }
    Log "Syncing $($s.Src) -> $REMOTE/$($s.Dst)"
    $args = @("sync", $s.Src, "$REMOTE/$($s.Dst)") + $RCLONE_FLAGS + $EXCLUDES
    & $RCLONE @args
    if ($LASTEXITCODE -ne 0) {
        Log "ERROR exit $LASTEXITCODE for $($s.Src)"
        $overall_ok = $false
    }
    else {
        Log "OK: $($s.Src)"
    }
}

# ── Prune old deleted snapshots (keep last 7 days) ────────────────────────────
Log "Pruning deleted snapshots older than 7 days..."
$cutoff = (Get-Date).AddDays(-7)
& $RCLONE lsd "$REMOTE/deleted/" --log-level ERROR 2>$null | ForEach-Object {
    $dateStr = ($_ -split '\s+')[-1]
    try {
        $date = [datetime]::ParseExact($dateStr, 'yyyyMMdd', $null)
        if ($date -lt $cutoff) {
            Log "Deleting old snapshot: deleted/$dateStr"
            & $RCLONE purge "$REMOTE/deleted/$dateStr" --log-level ERROR
        }
    }
    catch {}
}

if ($overall_ok) {
    Log "=== Backup completed successfully ==="
    exit 0
}
else {
    Log "=== Backup completed WITH ERRORS — check log ==="
    exit 1
}
