# ============================================================
# dev_setup.ps1  —  QIDIStudio Dev Workspace Setup
# ============================================================
# Creates an NTFS directory junction so QIDIStudio always reads
# scripts directly from this workspace — no copy, no stub, no
# rebuild needed.  Works transparently with the VS Code debugger.
#
# Architecture:
#   install_dir\resources\scripts\  -->  [JUNCTION]
#          workspace\resources\scripts\  (this repo)
#
# QIDIStudio resolves resources_dir() at runtime as:
#   binary.parent_path() / "resources"   (QIDIStudio.cpp ~L8000)
# so the junction is picked up without any C++ change.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\dev_setup.ps1
#
# Re-run if:
#   - You do a clean build (install_dir\resources\ gets wiped)
#   - The workspace or install_dir path changes
#
# Only ONE path needs configuration: $InstallDir below.
# Everything else is derived from $PSScriptRoot.
# ============================================================

$ErrorActionPreference = "Stop"

# ---- CONFIGURE: machine-specific install location ----
# This is the only hardcoded value in the whole pipeline.
# Change it once if your build output lives elsewhere.
$InstallDir = "C:\QIDISrc\QIDIStudio\install_dir"
# ------------------------------------------------------

# All other paths derived — no hardcoding
$Workspace   = Split-Path $PSScriptRoot -Parent
$JunctionSrc = Join-Path $InstallDir "resources\scripts"
$JunctionTgt = Join-Path $Workspace  "resources\scripts"

Write-Host ""
Write-Host "=== QIDIStudio Dev Setup (junction mode) ==="
Write-Host "Workspace  : $Workspace"
Write-Host "InstallDir : $InstallDir"
Write-Host ""

# Sanity checks
if (-not (Test-Path $JunctionTgt)) {
    Write-Error "Workspace scripts folder not found: $JunctionTgt"
    exit 1
}

$installResources = Join-Path $InstallDir "resources"
if (-not (Test-Path $installResources)) {
    Write-Warning "install_dir\resources\ not found — run a build first, then re-run this script."
    Write-Host "Expected: $installResources"
    exit 1
}

# Check current state
$existing = Get-Item $JunctionSrc -ErrorAction SilentlyContinue

if ($existing -and $existing.LinkType -eq "Junction") {
    $currentTarget = $existing.Target
    if ($currentTarget -eq $JunctionTgt) {
        Write-Host "Junction already live — workspace is the single source of truth." -ForegroundColor Green
        Write-Host "  $JunctionSrc"
        Write-Host "  --> $JunctionTgt"
        Write-Host ""
        exit 0
    } else {
        Write-Host "Junction exists but points elsewhere. Retargeting..."
        Write-Host "  Was: $currentTarget"
        Remove-Item $JunctionSrc -Force
    }
} elseif ($existing) {
    # Real directory (post-build copy) — remove it so we can create the junction
    Write-Host "Removing real directory at junction point..."
    Remove-Item $JunctionSrc -Recurse -Force
}

# Create the junction
New-Item -ItemType Junction -Path $JunctionSrc -Target $JunctionTgt | Out-Null

Write-Host "Junction created:" -ForegroundColor Green
Write-Host "  $JunctionSrc"
Write-Host "  --> $JunctionTgt"
Write-Host ""
Write-Host "From now on, edit workspace scripts directly — QIDIStudio reads them live." -ForegroundColor Green
Write-Host "VS Code debugger breakpoints in workspace files will fire normally." -ForegroundColor Green
Write-Host "No Copy-Item, no rebuild, no restart needed." -ForegroundColor Green
Write-Host ""
