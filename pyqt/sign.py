"""Code-signing for the installer pipeline.

Preferred tool: the Windows SDK `signtool.exe` (handles CNG keys reliably).
Fallback: PowerShell Set-AuthenticodeSignature. Either way a code-signing
certificate is created once per user (self-signed, CurrentUser store) unless
AMB_SIGN_THUMBPRINT points at a real CA-issued cert.

Local trust: `trust()` installs the cert into the machine's Trusted Root and
Trusted Publisher stores (UAC prompt when not elevated) so Windows verifies
this machine's own builds as Valid instead of Unknown Publisher. Honest
limitation: this only trusts the cert on THIS machine — other machines still
see an untrusted self-signed cert unless AMB_SIGN_THUMBPRINT points at a
publicly trusted OV/EV code-signing cert.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CERT_SUBJECT = "CN=AI Modpack Builder, O=AI Modpack Builder"
TIMESTAMP = "http://timestamp.digicent.com".replace("digicent", "digicert")


def _run(cmd: list, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True,
                          text=True, timeout=timeout)


def signtool() -> str | None:
    """Locate signtool.exe in the Windows SDK if installed."""
    if os.environ.get("AMB_SIGNTOOL"):
        return os.environ["AMB_SIGNTOOL"]
    kits = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
    if kits.is_dir():
        for ver in sorted(kits.iterdir(), reverse=True):
            cand = ver / "x64" / "signtool.exe"
            if cand.exists():
                return str(cand)
    return shutil.which("signtool")


def ps(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=180)


def find_cert() -> str | None:
    """Thumbprint of an existing AI Modpack Builder code-signing cert."""
    r = ps(
        "Get-ChildItem Cert:\\CurrentUser\\My | Where-Object { "
        "$_.Subject -like '*AI Modpack Builder*' -and "
        "$_.EnhancedKeyUsageList -like '*Code Signing*' } | "
        "Select-Object -First 1 -ExpandProperty Thumbprint")
    tp = (r.stdout or "").strip()
    return tp or None


def ensure_cert() -> str:
    """Return a code-signing cert thumbprint (env override, existing, or new)."""
    env_tp = os.environ.get("AMB_SIGN_THUMBPRINT", "").strip()
    if env_tp:
        return env_tp
    tp = find_cert()
    if tp:
        return tp
    r = ps(
        f"New-SelfSignedCertificate -Type CodeSigningCert "
        f"-Subject '{CERT_SUBJECT}' -CertStoreLocation Cert:\\CurrentUser\\My "
        f"-NotAfter (Get-Date).AddYears(3) | Select-Object -ExpandProperty Thumbprint")
    tp = (r.stdout or "").strip()
    if not tp:
        raise RuntimeError(f"could not create code-signing cert: {(r.stderr or '').strip()[:300]}")
    return tp


def sign_file(path: Path, thumbprint: str) -> tuple[bool, str]:
    """Sign a PE file with SHA-256 + RFC3161 timestamp. Prefers signtool."""
    st = signtool()
    if st:
        cmd = [st, "sign", "/s", "My", "/sha1", thumbprint,
               "/fd", "SHA256", "/tr", TIMESTAMP, "/td", "SHA256", str(path)]
        r = _run(cmd)
        if r.returncode == 0:
            return True, "signed (signtool, SHA256 + timestamp)"
        # Retry without the timestamp server (offline / blocked).
        r = _run(cmd[: cmd.index("/tr")] + [str(path)])
        if r.returncode == 0:
            return True, "signed (signtool, SHA256, no timestamp — server unreachable)"
        return False, (r.stdout or "")[-200:] + (r.stderr or "")[-200:]
    # Fallback: PowerShell Set-AuthenticodeSignature.
    base = (f"$cert = Get-Item Cert:\\CurrentUser\\My\\{thumbprint}; "
            f"Set-AuthenticodeSignature -FilePath '{path}' -Certificate $cert "
            f"-HashAlgorithm SHA256")
    r = ps(base + f" -TimestampServer '{TIMESTAMP}'")
    if "Signed" in (r.stdout or ""):
        return True, "signed (Set-AuthenticodeSignature, SHA256 + timestamp)"
    r2 = ps(base)
    if "Signed" in (r2.stdout or ""):
        return True, "signed (Set-AuthenticodeSignature, SHA256, no timestamp)"
    return False, ((r.stdout or "") + (r.stderr or "")).strip()[:300]


def verify(path: Path) -> str:
    st = signtool()
    if st:
        r = _run([st, "verify", "/pa", str(path)])
        return "Valid" if r.returncode == 0 else "Invalid/Untrusted"
    r = ps(f"(Get-AuthenticodeSignature -FilePath '{path}').Status")
    return (r.stdout or "").strip() or "Unknown"


# ---------------------------------------------------------------------------
# Local trust (Trusted Root / Trusted Publisher on this machine)
# ---------------------------------------------------------------------------
def is_admin() -> bool:
    """True when the current process runs elevated."""
    r = ps("(New-Object Security.Principal.WindowsPrincipal("
           "[Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole("
           "[Security.Principal.WindowsBuiltInRole]::Administrator)")
    return (r.stdout or "").strip().lower() == "true"


def is_trusted(thumbprint: str) -> bool:
    """True when the cert already sits in the machine Trusted Root store."""
    r = ps(f"Get-ChildItem Cert:\\LocalMachine\\Root\\{thumbprint} "
           "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty Thumbprint")
    return bool((r.stdout or "").strip())


def trust(thumbprint: str, elevate: bool = True) -> dict:
    """Install the cert into LocalMachine Root + TrustedPublisher.

    Needs admin (machine stores). When the current process is not elevated
    and elevate=True, re-runs itself through a UAC prompt and waits. Returns
    {ok, message, elevated} — never raises.
    """
    inner = (
        "try { "
        f"$c = Get-ChildItem Cert:\\CurrentUser\\My\\{thumbprint} -ErrorAction Stop; "
        "$r = New-Object System.Security.Cryptography.X509Certificates.X509Store("
        "'Root','LocalMachine'); $r.Open('ReadWrite'); $r.Add($c); $r.Close(); "
        "$p = New-Object System.Security.Cryptography.X509Certificates.X509Store("
        "'TrustedPublisher','LocalMachine'); $p.Open('ReadWrite'); $p.Add($c); $p.Close(); "
        "Write-Output 'TRUSTED' } "
        "catch { Write-Output ('FAIL: ' + $_.Exception.Message); exit 1 }"
    )
    enc = base64.b64encode(inner.encode("utf-16-le")).decode("ascii")
    if is_admin():
        r = ps(f"& ([ScriptBlock]::Create([Text.Encoding]::Unicode.GetString("
               f"[Convert]::FromBase64String('{enc}'))))")
        elevated = False
    elif not elevate:
        return {"ok": False, "message": "requires administrator privileges", "elevated": False}
    else:
        # UAC prompt; the elevated child runs the same store-import script.
        r = ps(f"Start-Process powershell -Verb RunAs -Wait -ArgumentList "
               f"'-NoProfile','-NonInteractive','-EncodedCommand','{enc}'")
        elevated = True
    out = (r.stdout or "").strip()
    if "TRUSTED" in out:
        return {"ok": True, "message": "cert trusted in LocalMachine Root + TrustedPublisher",
                "elevated": elevated}
    err = (out or (r.stderr or "").strip())[:300]
    if "The operation was canceled" in err or "canceled by the user" in err.lower():
        return {"ok": False, "message": "UAC prompt canceled — cert not trusted", "elevated": elevated}
    return {"ok": False, "message": f"trust failed: {err}", "elevated": elevated}


if __name__ == "__main__":
    # Usage: python sign.py --trust [thumbprint] | --trust-status [thumbprint]
    args = sys.argv[1:]
    if "--trust" in args:
        tp = args[args.index("--trust") + 1] if len(args) > args.index("--trust") + 1 else ensure_cert()
        res = trust(tp)
        print(json.dumps(res, indent=2))
        sys.exit(0 if res["ok"] else 1)
    elif "--trust-status" in args:
        tp = args[args.index("--trust-status") + 1] if len(args) > args.index("--trust-status") + 1 else ensure_cert()
        print(json.dumps({"thumbprint": tp, "trusted": is_trusted(tp)}))
    else:
        print("usage: python sign.py --trust [thumbprint] | --trust-status [thumbprint]")
        sys.exit(2)
