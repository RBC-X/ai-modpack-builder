# Register the reboot-survival verifier as a per-user Startup-folder shortcut
# so it runs automatically at the next logon (the reboot test). No elevation.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$verify = Join-Path $root "pyqt\reboot_verify.ps1"
if (-not (Test-Path $verify)) { throw "verifier not found: $verify" }

$ws = New-Object -ComObject WScript.Shell
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "AI Modpack Builder Reboot Verify.lnk"
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = "powershell.exe"
$s.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $verify + '"'
$s.WorkingDirectory = $root
$s.WindowStyle = 7
$s.Description = "One-shot reboot-survival verifier for the AI Modpack Builder update path"
$s.Save()

$t = $ws.CreateShortcut($lnk)
Write-Output "created : $lnk"
Write-Output "target  : $($t.TargetPath)"
Write-Output "args    : $($t.Arguments)"
Write-Output "REGISTERED"
