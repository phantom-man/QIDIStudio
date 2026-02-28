# ============================================================
# debug_build.ps1  —  QIDIStudio Debug CMake Configuration
# ============================================================
# Configures a separate CMake build with:
#   - RelWithDebInfo (optimized + full debug symbols /Zi)
#   - MSVC AddressSanitizer (/fsanitize=address)
#     Catches buffer overruns and use-after-free in C++ geometry
#     Requires VS 2019 16.9+ or VS 2022
#   - /DWIN32 /D_WINDOWS standard MSVC flags preserved
#
# Reference: "PhD-Level Hybrid Debugging Workflow.md" §II
#            "Debugging C++ and Python Systems.md" §II.1
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\debug_build.ps1
#
# Output: C:\QIDISrc\QIDIStudio\build_debug\
# Run resulting binary for ASan-instrumented testing.
# ============================================================

$ErrorActionPreference = "Stop"

# Paths — only source/install are machine-specific
$SourceDir  = "C:\QIDISrc\QIDIStudio"
$BuildDir   = "C:\QIDISrc\QIDIStudio\build_debug"
$InstallDir = "C:\QIDISrc\QIDIStudio\install_dir_debug"
$Cmake      = "C:\CMake329\bin\cmake.exe"   # Use CMake 3.29 (avoids 4.x policy break)

# Workspace derived — no hardcoding
$Workspace = Split-Path $PSScriptRoot -Parent

if (-not (Test-Path $Cmake)) {
    # Fallback: cmake on PATH
    $Cmake = "cmake"
}

Write-Host ""
Write-Host "=== QIDIStudio Debug Build ===" -ForegroundColor Cyan
Write-Host "Source  : $SourceDir"
Write-Host "Build   : $BuildDir"
Write-Host "Install : $InstallDir"
Write-Host ""

# Create build dir
if (-not (Test-Path $BuildDir)) {
    New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null
}

Push-Location $BuildDir

try {
    # Configure with ASan + debug symbols
    # MSVC /fsanitize=address requires the sanitizer runtime DLL:
    #   clang_rt.asan_dynamic-x86_64.dll — ships with VS, deployer must distribute it
    Write-Host "Configuring CMake (RelWithDebInfo + ASan)..." -ForegroundColor Yellow

    & $Cmake $SourceDir `
        -G "Visual Studio 17 2022" `
        -A x64 `
        -DCMAKE_BUILD_TYPE=RelWithDebInfo `
        -DCMAKE_INSTALL_PREFIX="$InstallDir" `
        "-DCMAKE_CXX_FLAGS=/fsanitize=address /Zi /RTC1" `
        "-DCMAKE_C_FLAGS=/fsanitize=address /Zi /RTC1" `
        -DQDT_RELEASE_TO_PUBLIC=0 `
        2>&1 | Tee-Object "$BuildDir\configure_debug_out.txt"

    if ($LASTEXITCODE -ne 0) {
        Write-Error "CMake configure failed (exit $LASTEXITCODE). See $BuildDir\configure_debug_out.txt"
    }

    Write-Host ""
    Write-Host "Configuration complete." -ForegroundColor Green
    Write-Host ""
    Write-Host "To build (will take ~20-40 min first time):" -ForegroundColor Cyan
    Write-Host "  cd $BuildDir"
    Write-Host "  cmake --build . --target install --config RelWithDebInfo -- /m:8 2>&1 | Tee-Object build_debug_out.txt"
    Write-Host ""
    Write-Host "ASan violations appear in the terminal as:" -ForegroundColor Yellow
    Write-Host "  ==<pid>==ERROR: AddressSanitizer: heap-buffer-overflow on address ..."
    Write-Host ""
    Write-Host "Note: Run from an x64 Native Tools Command Prompt, or ensure" -ForegroundColor DarkYellow
    Write-Host "  clang_rt.asan_dynamic-x86_64.dll is on PATH (ships with VS)." -ForegroundColor DarkYellow

} finally {
    Pop-Location
}
