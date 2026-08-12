# Register the HTTPS update-feed mirror in the HKCU Run key — the logon path
# proven to be processed early and reliably on this machine (the Startup
# folder ran ~4 min late at the reboot test). The Startup-folder shortcut is
# kept as a redundant second hook.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root "pyqt\.venv\Scripts\pythonw.exe"
$script = Join-Path $root "pyqt\serve_feed_https.py"
if (-not (Test-Path $pythonw)) { throw "pythonw not found: $pythonw" }

$cmd = '"' + $pythonw + '" "' + $script + '"'
New-Item -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Force | Out-Null
Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" `
    -Name "AI Modpack Builder Update Feed" -Value $cmd
$v = (Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run")."AI Modpack Builder Update Feed"
Write-Output "RUN KEY: AI Modpack Builder Update Feed = $v"
Write-Output "REGISTERED"
