#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Deploy all 4 Nexus sites to Firebase Hosting using curl.exe
  Run from the sites\ directory or from the repo root:
    powershell -ExecutionPolicy Bypass -File sites\deploy_all.ps1
#>
$ErrorActionPreference = 'Stop'

$PROJECT_ID = 'nexuicer'
$SITES_DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
$LOG_FILE = Join-Path $SITES_DIR 'deploy_result_ps.txt'

# site_id -> local folder (all sites already exist in Firebase)
$SITES = @(
    @{ id = 'nexuicer'; folder = 'nexusslicer' }
    @{ id = 'nexuicer-desktop'; folder = 'nexusslicer-desktop' }
    @{ id = 'nexusmill-app'; folder = 'nexusmill' }
    @{ id = 'nexusgauge-app'; folder = 'nexusgauge' }
)

$Results = [ordered]@{}

function Log($msg) {
    Write-Host $msg
    Add-Content -Path $LOG_FILE -Value $msg -Encoding UTF8
}

function Get-Token {
    $tok = (gcloud auth print-access-token 2>$null).Trim()
    if (-not $tok) { throw "gcloud: empty token" }
    return $tok
}

function Invoke-Api {
    param(
        [string]$Url,
        [string]$Method = 'GET',
        [string]$Body = $null,
        [string]$ContentType = 'application/json',
        [byte[]]$RawBody = $null
    )
    $tok = Get-Token
    $tmpResp = [System.IO.Path]::GetTempFileName()
    $tmpHead = [System.IO.Path]::GetTempFileName()

    $args = @(
        '--max-time', '60',
        '--silent', '--show-error',
        '-X', $Method,
        '-H', "Authorization: Bearer $tok",
        '-H', "x-goog-user-project: $PROJECT_ID",
        '-w', '%{http_code}',
        '-D', $tmpHead,
        '-o', $tmpResp
    )

    if ($RawBody) {
        $tmpRaw = [System.IO.Path]::GetTempFileName()
        [System.IO.File]::WriteAllBytes($tmpRaw, $RawBody)
        $args += @('-H', "Content-Type: application/octet-stream", '--data-binary', "@$tmpRaw")
    }
    elseif ($Body) {
        $args += @('-H', "Content-Type: $ContentType", '--data', $Body)
    }

    $httpCode = (& curl.exe @args $Url 2>&1).Trim()
    $respBody = Get-Content $tmpResp -Raw -Encoding UTF8 -ErrorAction SilentlyContinue

    if ($RawBody -and (Test-Path $tmpRaw)) { Remove-Item $tmpRaw -Force }
    Remove-Item $tmpResp, $tmpHead -Force -ErrorAction SilentlyContinue

    if ($httpCode -match '^[45]') {
        return $null, "HTTP $httpCode : $($respBody.Substring(0,[Math]::Min(300,$respBody.Length)))"
    }
    try { return ($respBody | ConvertFrom-Json), $null }
    catch { return @{}, $null }
}

function Deploy-Site($siteId, $folder) {
    $sitePath = Join-Path $SITES_DIR $folder
    $htmlFiles = @(Get-ChildItem -Path $sitePath -Filter '*.html' -Recurse)
    if ($htmlFiles.Count -eq 0) {
        Log "  [$siteId] No HTML files in $sitePath — skip"
        return $false
    }

    Log ("`n--- Deploying {0} ({1}/)  {2} file(s) ---" -f $siteId, $folder, $htmlFiles.Count)

    # Gzip + SHA-256 per file
    $fileMap = @{}
    foreach ($f in $htmlFiles) {
        $rawBytes = [System.IO.File]::ReadAllBytes($f.FullName)

        $ms = New-Object System.IO.MemoryStream
        $gz = New-Object System.IO.Compression.GZipStream($ms, [System.IO.Compression.CompressionLevel]::Optimal)
        $gz.Write($rawBytes, 0, $rawBytes.Length)
        $gz.Close()
        $gzBytes = $ms.ToArray()

        $sha = [System.BitConverter]::ToString(
            [System.Security.Cryptography.SHA256]::Create().ComputeHash($gzBytes)
        ).Replace('-', '').ToLower()

        $rel = '/' + ($f.FullName.Substring($sitePath.Length).Replace('\', '/').TrimStart('/'))
        $fileMap[$rel] = @{ gz = $gzBytes; sha = $sha }
        Log ("     {0}  [{1} B gzipped]  hash={2}..." -f $rel, $gzBytes.Length, $sha.Substring(0, 12))
    }

    # 1. Create version
    $versionBody = '{"config":{"headers":[{"glob":"**","headers":{"Cache-Control":"public,max-age=300,must-revalidate"}}],"rewrites":[{"glob":"**","path":"/index.html"}]}}'
    $resp, $err = Invoke-Api -Url "https://firebasehosting.googleapis.com/v1beta1/sites/$siteId/versions" `
        -Method 'POST' -Body $versionBody
    if ($err) { Log "  Create version ERROR: $err"; return $false }
    $versionName = $resp.name
    Log "  Version: $($versionName.Split('/')[-1])"

    # 2. Populate files
    $filesObj = @{}
    $fileMap.GetEnumerator() | ForEach-Object { $filesObj[$_.Key] = $_.Value.sha }
    $popBody = @{ files = $filesObj } | ConvertTo-Json -Compress
    $resp, $err = Invoke-Api -Url "https://firebasehosting.googleapis.com/v1beta1/$versionName`:populateFiles" `
        -Method 'POST' -Body $popBody
    if ($err) { Log "  populateFiles ERROR: $err"; return $false }
    $uploadUrl = $resp.uploadUrl
    $requiredHashes = @{}
    if ($resp.uploadRequiredHashes) {
        $resp.uploadRequiredHashes | ForEach-Object { $requiredHashes[$_] = $true }
    }
    Log "  Upload required: $($requiredHashes.Count) / $($fileMap.Count) file(s)"

    # 3. Upload required files
    foreach ($entry in $fileMap.GetEnumerator()) {
        $sha = $entry.Value.sha
        if ($requiredHashes.ContainsKey($sha)) {
            $_, $err = Invoke-Api -Url "$uploadUrl/$sha" -Method 'POST' -RawBody $entry.Value.gz
            if ($err) { Log "  Upload $($entry.Key) ERROR: $err"; return $false }
            Log "  Uploaded: $($entry.Key)"
        }
    }

    # 4. Finalize version
    $resp, $err = Invoke-Api -Url "https://firebasehosting.googleapis.com/v1beta1/$versionName`?updateMask=status" `
        -Method 'PATCH' -Body '{"status":"FINALIZED"}'
    if ($err) { Log "  Finalize ERROR: $err"; return $false }
    Log "  Status: $($resp.status)"

    # 5. Create release
    $resp, $err = Invoke-Api -Url "https://firebasehosting.googleapis.com/v1beta1/sites/$siteId/releases?versionName=$versionName" `
        -Method 'POST'
    if ($err) { Log "  Release ERROR: $err"; return $false }
    Log "  LIVE -> https://$siteId.web.app/"
    return $true
}

# ─── main ────────────────────────────────────────────────────────────────────
if (Test-Path $LOG_FILE) { Remove-Item $LOG_FILE -Force }

Log ('=' * 60)
Log "Firebase project : $PROJECT_ID"
Log "Sites dir        : $SITES_DIR"
Log ('=' * 60)

Log "`n=== Deploying all 4 sites ==="

foreach ($site in $SITES) {
    $ok = Deploy-Site $site.id $site.folder
    $Results[$site.id] = if ($ok) { 'OK' } else { 'FAILED' }
    Start-Sleep -Milliseconds 300
}

Log ("`n" + ('=' * 60))
Log 'DEPLOYMENT SUMMARY'
Log ('=' * 60)
foreach ($kv in $Results.GetEnumerator()) {
    Log ("  {0,-6}  {1,-25}  https://{2}.web.app/" -f $kv.Value, $kv.Key, $kv.Key)
}

$failed = $Results.Values | Where-Object { $_ -ne 'OK' }
if ($failed) { exit 1 } else { exit 0 }
