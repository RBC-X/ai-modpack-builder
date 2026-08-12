"""Self-update support for the installed app.

Feed contract (update.json served at a URL — the URL is the app setting
`updateUrl`, or the AMB_UPDATE_URL environment variable):

    {
      "version": "1.0.1",                 # newest available version
      "notes": "…",                       # human-readable changelog
      "installerUrl": "https://…/AI-Modpack-Builder-Setup-1.0.1.exe",
      "installerSha256": "<hex sha256 of the installer>"
    }

The installed app compares APP_VERSION (product_config.py) against the feed,
downloads the installer into its per-user data dir (size-capped, SHA-256
verified), then launches it with Inno Setup's silent flags. The installer is
the same per-user Inno Setup build, so it updates in place.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
import urllib.parse
import re
from pathlib import Path
from typing import Optional

try:
    from product_config import APP_VERSION, DEFAULT_UPDATE_FEED_URL
except Exception:  # noqa: BLE001  (module moved / not on path)
    APP_VERSION = "1.0.0"
    DEFAULT_UPDATE_FEED_URL = ""

DEFAULT_MAX_INSTALLER_MB = 600
CHECK_STAMP = "last-update-check"  # filename inside data_dir for throttle
PERIODIC_STAMP = "last-update-periodic-check"  # separate throttle for the 2 h in-app check
EXPECTED_PUBLISHER = os.environ.get("AMB_UPDATE_PUBLISHER", "AI Modpack Builder").strip()


def _validate_url(url: str) -> str:
    """Require HTTPS in production; local/file feeds need an explicit dev flag."""
    parsed = urllib.parse.urlsplit(str(url or "").strip())
    if parsed.scheme.lower() == "https" and parsed.hostname:
        return url
    dev = os.environ.get("AMB_UPDATE_ALLOW_INSECURE", "") == "1"
    local = parsed.scheme.lower() == "file" or (
        parsed.scheme.lower() == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"})
    if dev and local:
        return url
    raise ValueError("update URLs must use HTTPS (local/file testing requires AMB_UPDATE_ALLOW_INSECURE=1)")


def _validate_sha256(value: str) -> str:
    digest = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("update feed must provide a valid 64-character installerSha256")
    return digest


def version_tuple(v: str):
    """'1.0.1' / 'v1.0.1' / '1.0' -> (1, 0, 1). Unparsable -> (0,)."""
    s = str(v or "").strip().lstrip("vV")
    parts = []
    for chunk in s.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts) if parts else (0,)


def update_url() -> str:
    """Feed URL: AMB_UPDATE_URL override, else the embedded default for
    installed builds (the app setting `updateUrl` is merged by callers).
    Fresh installs therefore auto-point at the shipped feed URL."""
    return os.environ.get("AMB_UPDATE_URL", "").strip() or DEFAULT_UPDATE_FEED_URL.strip()


def fetch_feed(url: str, timeout: int = 20) -> dict:
    """GET the update feed and validate its shape."""
    _validate_url(url)
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("update feed too large")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or not str(data.get("version") or "").strip():
        raise ValueError("update feed missing 'version'")
    if not str(data.get("installerUrl") or "").strip():
        raise ValueError("update feed missing 'installerUrl'")
    _validate_url(str(data["installerUrl"]))
    data["installerSha256"] = _validate_sha256(data.get("installerSha256"))
    return data


def check(url: str, timeout: int = 20) -> dict:
    """Compare the feed against the running app version.

    Returns a plain dict: {ok, current, latest, available, notes,
    installerUrl, installerSha256} — never raises for network errors.
    """
    try:
        feed = fetch_feed(url, timeout)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"could not reach update feed: {e}",
                "current": APP_VERSION, "latest": None, "available": False,
                "feedUrl": str(url or "").strip()}
    latest = str(feed.get("version", "")).strip()
    available = version_tuple(latest) > version_tuple(APP_VERSION)
    return {
        "ok": True,
        "current": APP_VERSION,
        "latest": latest,
        "available": available,
        "notes": str(feed.get("notes") or ""),
        "feedUrl": str(url or "").strip(),
        "installerUrl": str(feed.get("installerUrl", "")).strip(),
        "installerSha256": str(feed.get("installerSha256") or "").strip().lower(),
    }


def download(url: str, dest_dir: Path, sha256: str = "", max_mb: int = DEFAULT_MAX_INSTALLER_MB) -> Path:
    """Stream the installer to dest_dir with a size cap and SHA-256 verify.

    Returns the downloaded path. Raises on size-limit or hash mismatch.
    """
    _validate_url(url)
    sha256 = _validate_sha256(sha256)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = Path(urllib.request.urlparse(url).path).name or "update-installer.exe"
    dest = dest_dir / name
    h = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_mb * 1024 * 1024:
                    dest.unlink(missing_ok=True)
                    raise ValueError(f"installer exceeds {max_mb} MB size cap")
                h.update(chunk)
                f.write(chunk)
    if h.hexdigest().lower() != sha256:
        dest.unlink(missing_ok=True)
        raise ValueError(f"SHA-256 mismatch: expected {sha256}, got {h.hexdigest()}")
    return dest


def verify_authenticode(path: Path, expected_publisher: str = EXPECTED_PUBLISHER) -> dict:
    """Verify Windows trust and pin the signer identity before execution."""
    if os.name != "nt":
        raise RuntimeError("installer signature verification is available on Windows only")
    escaped = str(Path(path).resolve()).replace("'", "''")
    script = ("$s=Get-AuthenticodeSignature -LiteralPath '" + escaped + "'; "
              "$o=[ordered]@{Status=[string]$s.Status; Subject=[string]$s.SignerCertificate.Subject; "
              "Thumbprint=[string]$s.SignerCertificate.Thumbprint}; $o|ConvertTo-Json -Compress")
    proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=30)
    try:
        result = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("could not inspect installer signature") from exc
    if proc.returncode != 0 or result.get("Status") != "Valid":
        raise RuntimeError(f"installer Authenticode signature is not valid ({result.get('Status') or 'unknown'})")
    if expected_publisher and expected_publisher.casefold() not in str(result.get("Subject") or "").casefold():
        raise RuntimeError("installer signer does not match the expected publisher")
    return result


def apply_installer(path: Path, extra_dir: Optional[str] = None) -> subprocess.Popen:
    """Launch the downloaded installer in silent per-user update mode.

    The target dir is always pinned with /DIR: Inno Setup remembers the last
    /DIR used on the machine, so an unpinned silent install can silently
    reinstall into a stale (e.g. test-scratch) directory. Precedence:
    explicit extra_dir, then AMB_UPDATE_DIR (test hook), then the running
    app's own folder in frozen builds (i.e. the real install dir).
    """
    if os.environ.get("AMB_UPDATE_ALLOW_UNSIGNED", "") != "1":
        verify_authenticode(path)
    target = extra_dir or os.environ.get("AMB_UPDATE_DIR") or None
    if not target and getattr(sys, "frozen", False):
        target = str(Path(sys.executable).resolve().parent)
    args = [str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]
    if target:
        args.append("/DIR=" + target)
    return subprocess.Popen(args, close_fds=True)


def run_update(url: str, apply: bool = False, dest_dir: Optional[Path] = None,
               extra_dir: Optional[str] = None) -> dict:
    """Orchestrate check -> download -> verify -> (apply) -> report.

    Used by the --check-update CLI mode and the Settings panel. Never raises;
    returns a report dict with everything the UI/log needs.
    """
    res = check(url)
    if not res.get("ok"):
        return res
    if not res["available"]:
        return res
    try:
        dest = dest_dir or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AI Modpack Builder" / "updates"
        path = download(res["installerUrl"], dest, res.get("installerSha256") or "")
        res["downloaded"] = str(path)
        res["sizeBytes"] = path.stat().st_size
        if apply:
            proc = apply_installer(path, extra_dir or os.environ.get("AMB_UPDATE_DIR") or None)
            res["launchedPid"] = proc.pid
            res["applied"] = True
            # Remember which version we just installed so the next boot can
            # health-check it and offer a rollback if it fails.
            try:
                (dest.parent / ROLLBACK_MARKER).write_text(
                    json.dumps({"version": res.get("latest", "")}), "utf-8")
            except Exception:  # noqa: BLE001
                pass
        else:
            res["applied"] = False
    except Exception as e:  # noqa: BLE001
        res["ok"] = False
        res["error"] = str(e)
    return res


def should_auto_check(data_dir: Path, hours: int = 24, stamp: str = CHECK_STAMP) -> bool:
    """Throttle an auto-check to once per N hours (separate stamps allowed)."""
    stamp_path = Path(data_dir) / stamp
    try:
        import time
        age = time.time() - float(stamp_path.read_text().strip())
        return age > hours * 3600
    except Exception:  # noqa: BLE001
        return True


def stamp_check(data_dir: Path, stamp: str = CHECK_STAMP) -> None:
    try:
        import time
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        (Path(data_dir) / stamp).write_text(str(time.time()), "utf-8")
    except Exception:  # noqa: BLE001
        pass


ROLLBACK_MARKER = "last-applied.json"  # inside data_dir: version the last update applied


def applied_marker(data_dir: Path) -> str | None:
    """Version recorded when the last update was launched, if any."""
    try:
        p = Path(data_dir) / ROLLBACK_MARKER
        if p.exists():
            return str(json.loads(p.read_text("utf-8")).get("version") or "").strip() or None
    except Exception:  # noqa: BLE001
        pass
    return None


def clear_applied_marker(data_dir: Path) -> None:
    try:
        (Path(data_dir) / ROLLBACK_MARKER).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def rollback_candidate(data_dir: Path) -> dict | None:
    """Newest installer in the updates pool strictly older than the running app.

    Every applied update leaves its installer in <data_dir>/updates/, so the
    previous (or any older) version is always restorable without a re-download.
    Returns {"version", "path"} or None.
    """
    pool = Path(data_dir) / "updates"
    if not pool.is_dir():
        return None
    best: dict | None = None
    try:
        for f in pool.glob("AI-Modpack-Builder-Setup-*.exe"):
            m = re.match(r"AI-Modpack-Builder-Setup-(?:v)?(\d+(?:\.\d+)*)\.exe$", f.name)
            if not m:
                continue
            ver = m.group(1)
            if version_tuple(ver) >= version_tuple(APP_VERSION):
                continue  # same/never version is not a rollback target
            if best is None or version_tuple(ver) > version_tuple(best["version"]):
                best = {"version": ver, "path": f}
    except Exception:  # noqa: BLE001
        return None
    return best
