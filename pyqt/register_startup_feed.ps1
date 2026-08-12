# Register the HTTPS update-feed mirror as a logon startup shortcut so the
# installed launcher's auto-update keeps working after every reboot.
# No elevation needed — this writes to the current user's Startup folder.
$ErrorActionPreference = "Stop"

# Project root is the parent of the pyqt/ folder this script lives in —
# portable across machines/checkouts.
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root "pyqt\.venv\Scripts\pythonw.exe"
$script = Join-Path $root "pyqt\serve_feed_https.py"

if (-not (Test-Path $pythonw)) { throw "pythonw not found: $pythonw" }
if (-not (Test-Path $script))  { throw "mirror script not found: $script" }

$ws = New-Object -ComObject WScript.Shell
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "AI Modpack Builder Update Feed.lnk"
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = $pythonw
$s.Arguments = '"' + $script + '"'
$s.WorkingDirectory = $root
$s.WindowStyle = 7  # minimized; pythonw has no console anyway
$s.Description = "AI Modpack Builder HTTPS update-feed mirror (auto-update support)"
$s.Save()

# Verify what was written.
$t = $ws.CreateShortcut($lnk)
Write-Output "created : $lnk"
Write-Output "target  : $($t.TargetPath)"
Write-Output "args    : $($t.Arguments)"
Write-Output "workdir : $($t.WorkingDirectory)"
if (-not (Test-Path $lnk)) { throw "shortcut not created" }
Write-Output "REGISTERED"
