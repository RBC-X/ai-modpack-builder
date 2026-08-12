# Reboot-survival verifier (runs at logon via the Startup folder).
#
# After a real reboot this confirms:
#   1. the HTTPS update-feed mirror relaunched (port 8543 + its feed over TLS), and
#   2. the installed launcher still reaches the PUBLIC GitHub feed (no dev flags).
#
# Evidence is written to %LOCALAPPDATA%\AI Modpack Builder\workspace\reboot-verify.json.
$ErrorActionPreference = "Continue"
$wsDir = Join-Path $env:LOCALAPPDATA "AI Modpack Builder\workspace"
New-Item -ItemType Directory -Force -Path $wsDir | Out-Null
$report = [ordered]@{
    timestamp     = (Get-Date).ToString("o")
    mirrorPort    = 8543
    mirrorPid     = $null
    mirrorListening = $false
    mirrorFeedVersion = $null
    mirrorFeedHttp = $null
    appOk         = $null
    appCurrent    = $null
    appLatest     = $null
    appAvailable  = $null
}

# 1) Wait for the mirror (its own Startup shortcut also runs at logon; order
#    is not guaranteed, so poll for up to ~2 minutes).
for ($i = 0; $i -lt 60; $i++) {
    $conn = Get-NetTCPConnection -LocalPort 8543 -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $report.mirrorListening = $true
        $report.mirrorPid = ($conn | Select-Object -First 1).OwningProcess
        break
    }
    Start-Sleep -Seconds 2
}

# 2) Ask the mirror for the feed over TLS (machine-trusted cert, no dev flag).
if ($report.mirrorListening) {
    try {
        $r = Invoke-WebRequest -Uri "https://127.0.0.1:8543/workspace/update-feed-https/update.json" `
            -UseBasicParsing -TimeoutSec 10
        $feed = $r.Content | ConvertFrom-Json
        $report.mirrorFeedHttp = [int]$r.StatusCode
        $report.mirrorFeedVersion = [string]$feed.version
    } catch {
        $report.mirrorFeedError = $_.Exception.Message
    }
} else {
    $report.mirrorFeedError = "mirror did not come up within ~120s of logon"
}

# 3) The installed launcher checks the PUBLIC GitHub feed (needs no local process).
$exe = Join-Path $env:LOCALAPPDATA "Programs\AI Modpack Builder\AI Modpack Builder.exe"
$feedUrl = "https://github.com/RBC-X/ai-modpack-builder/releases/latest/download/update.json"
if (Test-Path $exe) {
    try {
        $p = Start-Process -FilePath $exe -ArgumentList @("--check-update", $feedUrl) -Wait -PassThru
        $report.appCheckRc = $p.ExitCode
    } catch {
        $report.appCheckError = $_.Exception.Message
    }
    $vc = Join-Path $wsDir "update-check.json"
    if (Test-Path $vc) {
        $v = Get-Content $vc -Raw | ConvertFrom-Json
        $report.appOk        = $v.ok
        $report.appCurrent   = $v.current
        $report.appLatest    = $v.latest
        $report.appAvailable = $v.available
        if ($v.error) { $report.appError = [string]$v.error }
    } else {
        $report.appCheckError = "no update-check.json verdict written"
    }
} else {
    $report.appCheckError = "installed app not found: $exe"
}

$out = Join-Path $wsDir "reboot-verify.json"
$report | ConvertTo-Json -Depth 4 | Set-Content -Path $out -Encoding UTF8
Write-Output ("VERDICT " + ($report | ConvertTo-Json -Compress -Depth 4))
