# Fresh-user proof: brand-new PC install of the shipped installer, zero
# pre-configuration (no state.json, no AMB_UPDATE_URL), must auto-point at
# the embedded default GitHub feed and check-update against it.
$ErrorActionPreference = "Stop"
$root = "C:\Users\bsmit\OneDrive\Documents\Minecraft Builder"
$setup = Join-Path $root "installers\AI-Modpack-Builder-Setup-1.0.7.exe"
$scratch = Join-Path $env:TEMP "amb-fresh-user-$(Get-Random)"
New-Item -ItemType Directory -Path $scratch -Force | Out-Null
$installDir = Join-Path $scratch "install"
$freshAppData = Join-Path $scratch "appdata"

Write-Host "=== 1. Silent install into clean prefix ==="
$p = Start-Process -FilePath $setup -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/SP-","/DIR=$installDir" -PassThru -Wait
Write-Host ("installer exit: {0}" -f $p.ExitCode)
Start-Sleep -Seconds 2
$exe = Join-Path $installDir "AI Modpack Builder.exe"
if (-not (Test-Path $exe)) { Write-Host "FAIL: install did not produce $exe"; exit 1 }
Write-Host "PASS: installed -> $exe"

Write-Host "=== 2. Confirm zero pre-configuration ==="
$state = Join-Path $freshAppData "AI Modpack Builder\state.json"
if (Test-Path $state) { Write-Host "WARN: state.json already exists"; } else { Write-Host "PASS: no state.json (fresh user)" }
$env:AMB_UPDATE_URL = ""          # no env override
$env:LOCALAPPDATA = $freshAppData # fresh data dir
Remove-Item Env:AMB_UPDATE_ALLOW_INSECURE -ErrorAction SilentlyContinue

Write-Host "=== 3. --check-update with NO url argument (default must kick in) ==="
$p2 = Start-Process -FilePath $exe -ArgumentList "--check-update" -PassThru -Wait
$rc = $p2.ExitCode
$report = Join-Path $freshAppData "AI Modpack Builder\workspace\update-check.json"
$deadline = (Get-Date).AddSeconds(90)
while (-not (Test-Path $report) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
if (Test-Path $report) {
    $r = Get-Content $report -Raw | ConvertFrom-Json
    Write-Host ("verdict: ok={0} current={1} available={2} latest={3}" -f $r.ok, $r.current, $r.available, $r.latest)
    Write-Host ("feedUrl={0}" -f $r.feedUrl)
} else {
    Write-Host "FAIL: no update-check.json written"
}
Write-Host "rc=$rc"
Write-Host "scratch=$scratch"
