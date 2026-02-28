# ============================================================
# run_texture_pipeline.ps1  —  Standalone Blender invocation
# ============================================================
# Runs apply_texture_bpy.py directly via Blender without
# needing QIDIStudio to be running.  Full debugpy support:
#   1. Launch debugpy in apply_texture_bpy.py (QIDI_BPY_DEBUG=1)
#   2. Attach VS Code "Python: Remote Attach" to localhost:5678
#
# Usage:
#   .\scripts\run_texture_pipeline.ps1 `
#       -Model  C:\path\to\model.stl `
#       -Skin   C:\path\to\skin.png  `
#       -Output C:\path\to\out.stl
#
# Optional:
#   -BlenderExe  C:\path\to\blender.exe   # override auto-discovery
#   -Debug                                 # enable debugpy wait-for-attach
#   -LogFile     C:\path\to\log.txt        # default: $TEMP\qidi_bpy.log
# ============================================================

param(
    [string]$Model,
    [string]$Skin,
    [string]$Output,
    [string]$BlenderExe,
    [switch]$Debug,
    [string]$LogFile
)

$ErrorActionPreference = "Stop"

# Derive workspace root from this script's location — no hardcoding
$Workspace  = Split-Path $PSScriptRoot -Parent
$ScriptPath = Join-Path $Workspace "resources\scripts\apply_texture_bpy.py"

if (-not (Test-Path $ScriptPath)) {
    Write-Error "apply_texture_bpy.py not found at: $ScriptPath"
    exit 1
}

# ---- Discover Blender ----
function Find-Blender {
    # 1. Explicit env var (same override pattern as Plater.cpp find_bpy_python())
    if ($env:QIDI_BLENDER_EXE -and (Test-Path $env:QIDI_BLENDER_EXE)) {
        return $env:QIDI_BLENDER_EXE
    }
    # 2. Scan Program Files for newest Blender
    $candidates = @(
        "$env:ProgramFiles\Blender Foundation",
        "${env:ProgramFiles(x86)}\Blender Foundation"
    ) | Where-Object { Test-Path $_ } |
        ForEach-Object { Get-ChildItem $_ -Filter "blender.exe" -Recurse -ErrorAction SilentlyContinue } |
        Sort-Object { $_.FullName } -Descending |
        Select-Object -First 1
    if ($candidates) { return $candidates.FullName }
    return $null
}

if (-not $BlenderExe) { $BlenderExe = Find-Blender }
if (-not $BlenderExe) {
    Write-Error @"
Blender not found. Either:
  set QIDI_BLENDER_EXE=C:\path\to\blender.exe
  or pass -BlenderExe C:\path\to\blender.exe
"@
    exit 1
}

Write-Host "Blender : $BlenderExe"
Write-Host "Script  : $ScriptPath"

# ---- Build argument list ----
$blenderArgs = @("--background", "--python", $ScriptPath, "--")

if ($Model)   { $blenderArgs += @("--model",   $Model) }
if ($Skin)    { $blenderArgs += @("--skin",    $Skin) }
if ($Output)  { $blenderArgs += @("--output",  $Output) }

if (-not $LogFile) { $LogFile = Join-Path $env:TEMP "qidi_bpy.log" }
$blenderArgs += @("--log", $LogFile)

if ($Debug) {
    $blenderArgs += "--wait-for-debugger"
    $env:QIDI_BPY_DEBUG = "1"
    Write-Host ""
    Write-Host "Debug mode: Blender will pause and wait for debugpy on localhost:5678" -ForegroundColor Cyan
    Write-Host "  In VS Code: Run & Debug -> 'Python: Remote Attach'" -ForegroundColor Cyan
}

Write-Host "Log     : $LogFile"
Write-Host ""

# ---- Run ----
Write-Host "Launching Blender..." -ForegroundColor Yellow
$proc = Start-Process -FilePath $BlenderExe `
                      -ArgumentList $blenderArgs `
                      -NoNewWindow -PassThru -Wait

$exitCode = $proc.ExitCode
Write-Host ""

# Tail log output
if (Test-Path $LogFile) {
    Write-Host "--- Pipeline log ($LogFile) ---" -ForegroundColor Cyan
    Get-Content $LogFile | Write-Host
    Write-Host "--- end log ---" -ForegroundColor Cyan
    Write-Host ""
}

if ($exitCode -eq 0) {
    Write-Host "Pipeline completed successfully." -ForegroundColor Green
} else {
    Write-Host "Pipeline exited with code $exitCode." -ForegroundColor Red
    exit $exitCode
}
