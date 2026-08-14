"""Core engine: paths, util, events, logger.

The single engine of the system — plain JSON-dict data shapes shared by every
subsystem. The legacy Node engine (src/) was deleted on 2026-08-11.
"""
from __future__ import annotations

import datetime
import hashlib
import io
import json
import os
import re
import shutil
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional

USER_AGENT = "ai-modpack-builder/0.1 (automated modpack builder; contact: local)"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle (installed app)."""
    return bool(getattr(sys, "frozen", False))


def resource_path(rel: str) -> Path:
    """Resolve a bundled resource (fonts, icons) in dev and frozen builds.

    Dev:      <checkout>/pyqt/<rel>
    Frozen:   <bundle>/_internal/<rel>  (PyInstaller contents directory)
    """
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        return base / rel
    return Path(__file__).resolve().parent.parent / rel


def data_dir() -> Path:
    """Per-user writable data root for the installed app.

    Installed builds must never write next to the executable (Program Files /
    the PyInstaller bundle may be read-only); per-user app data is the
    standard Windows location. AMB_WORKSPACE keeps overriding everything for
    dev/test harnesses.
    """
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "AI Modpack Builder"
    return PROJECT_ROOT


def workspace_dir() -> Path:
    env = os.environ.get("AMB_WORKSPACE")
    if env:
        return Path(env).resolve()
    return data_dir() / "workspace"


def builds_dir() -> Path:
    return workspace_dir() / "builds"


def cache_dir() -> Path:
    return workspace_dir() / "cache"


def config_dir() -> Path:
    return workspace_dir() / "config"


def java_dir() -> Path:
    return workspace_dir() / "java"


def settings_path() -> Path:
    return config_dir() / "settings.json"


def web_dir() -> Path:
    return PROJECT_ROOT / "web"


# ---------------------------------------------------------------------------
# Misc util
# ---------------------------------------------------------------------------

def uid(prefix: str = "") -> str:
    return prefix + format(int(time.time() * 1000), "x") + "-" + os.urandom(4).hex()


def sleep(ms: float) -> None:
    time.sleep(ms / 1000.0)


def unique(arr: list) -> list:
    return list(dict.fromkeys(arr))


def clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


def mkdirp(p: Path) -> None:
    Path(p).mkdir(parents=True, exist_ok=True)


def sanitize_filename(name: str, fallback: str = "file") -> str:
    s = re.sub(r"[\\/]", "_", name)
    s = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", s)
    s = re.sub(r"[. ]+$", "", s).strip()
    if not s or s in (".", ".."):
        s = fallback
    return s[:120]


def sha1_hex(buf: bytes) -> str:
    return hashlib.sha1(buf).hexdigest()


def sha512_hex(buf: bytes) -> str:
    return hashlib.sha512(buf).hexdigest()


def format_bytes(n: float) -> str:
    if not n or n <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = min(len(units) - 1, int(n.bit_length() / 10) if n > 0 else 0)
    # simpler log-based index
    import math
    i = min(len(units) - 1, max(0, int(math.log(n) / math.log(1024))))
    val = n / (1024 ** i)
    return f"{val:.0f} {units[i]}" if i == 0 else f"{val:.1f} {units[i]}"


def read_json_file(p: Path) -> Optional[Any]:
    try:
        return json.loads(Path(p).read_text("utf-8"))
    except Exception:
        return None


def write_json_file(p: Path, data: Any) -> None:
    """Atomic write with a bounded retry on transient Windows locks
    (antivirus/OneDrive brief holds can otherwise fail os.replace)."""
    mkdirp(Path(p).parent)
    target = Path(p)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    last_err: Exception | None = None
    for _attempt in range(3):
        try:
            temporary.write_text(json.dumps(data, indent=2), "utf-8")
            os.replace(temporary, target)
            last_err = None
            break
        except OSError as e:  # noqa: BLE001 — transient lock; retry briefly
            last_err = e
            sleep(0.15 * (_attempt + 1))
    if last_err is not None:
        raise last_err
    else:
        temporary.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Version math
# ---------------------------------------------------------------------------

def version_parts(v: str) -> list:
    return [
        int(p) if p.isdigit() else p
        for p in re.split(r"[.\-_+]", v.lower())
        if p != ""
    ]


def compare_versions(a: str, b: str) -> int:
    pa, pb = version_parts(a), version_parts(b)
    for i in range(max(len(pa), len(pb))):
        x = pa[i] if i < len(pa) else 0
        y = pb[i] if i < len(pb) else 0
        if isinstance(x, int) and isinstance(y, int):
            if x != y:
                return -1 if x < y else 1
        else:
            xs, ys = str(x), str(y)
            if xs != ys:
                return -1 if xs < ys else 1
    return 0


def _tilde_bounds(v: str) -> tuple[str, str]:
    """npm-style compatible range for '~v': >= v and < the next minor (or the
    next major when v has only one numeric part). '~1.2' -> (1.2, 1.3),
    '~1.2.3' -> (1.2.3, 1.3), '~1' -> (1, 2)."""
    nums = re.findall(r"\d+", v)
    if not nums:
        return v, ""
    if len(nums) == 1:
        return v, str(int(nums[0]) + 1)
    lo = ".".join(nums[:2])
    hi = f"{nums[0]}.{int(nums[1]) + 1}"
    return lo, hi


def parse_version_range(spec: str) -> list[dict]:
    """Parse Modrinth-style version ranges into a list of constraints.

    Supported syntax (documented — Issue 16):
      "1.2"              exact
      ">1.2" ">=1.2" "<1.2" "<=1.2"
      "[1.2,2.0)"        interval (exclusive/inclusive brackets)
      "~1.2"             compatible minor: >=1.2 and <1.3 (npm semantics)
      "1.2 2.0"          space-separated conjunction (all must hold)
    Minecraft-style names ("1.20.1", "1.20.1-beta") compare naturally by
    numeric parts; prerelease suffixes sort before the release.
    """
    spec = (spec or "").strip()
    if not spec:
        return []
    out: list[dict] = []
    single = re.match(r"^([\[(])([^,)\]]+)([\])])$", spec)
    if single:
        out.append({"op": "=", "version": single.group(2).strip()})
        return out
    m = re.match(r"^([\[(])([^,]+),([^)\]]*)([\])])$", spec)
    if m:
        lo_bracket, lo_v, hi_v, hi_bracket = m.groups()
        if lo_v.strip():
            out.append({"op": ">=" if lo_bracket == "[" else ">", "version": lo_v.strip()})
        if hi_v.strip():
            out.append({"op": "<=" if hi_bracket == "]" else "<", "version": hi_v.strip()})
        return out
    # Commas are optional separators (">=1.20, <1.21" == ">=1.20 <1.21");
    # normalize them so the first constraint is never dropped (Issue 16).
    for p in spec.replace(",", " ").split():
        cm = re.match(r"^(>=|<=|>|<|=|~)?([0-9][A-Za-z0-9.\-_+]*(?::[A-Za-z0-9.\-_+]+)?)$", p)
        if not cm:
            continue
        op, v = cm.groups()
        if op == "~":
            # ~ is a compatible-minor range, not merely '>=' (was the old bug:
            # anything above the floor matched, so ~1.2 accepted 2.x).
            lo, hi = _tilde_bounds(v)
            out.append({"op": ">=", "version": lo})
            if hi:
                out.append({"op": "<", "version": hi})
            continue
        out.append({"op": op or "=", "version": v})
    return out


def version_satisfies(version: str, range_spec: Optional[str]) -> bool:
    if not range_spec or not range_spec.strip() or range_spec.strip() == "*":
        return True
    constraints = parse_version_range(range_spec)
    if not constraints:
        return False
    for c in constraints:
        cmpv = compare_versions(version, c["version"])
        op = c["op"]
        if op == ">" and not (cmpv > 0):
            return False
        if op == ">=" and not (cmpv >= 0):
            return False
        if op == "<" and not (cmpv < 0):
            return False
        if op == "<=" and not (cmpv <= 0):
            return False
        if op == "=" and cmpv != 0:
            return False
        # '~' is expanded by parse_version_range into >= + <; keep the direct
        # call safe for legacy single-constraint use (floor check only).
        if op == "~" and cmpv < 0:
            return False
    return True


def minor_version(v: str) -> str:
    m = re.match(r"^(\d+\.\d+)(?:\.\d+)?$", v)
    return m.group(1) if m else v


# ---------------------------------------------------------------------------
# HTTP with retry / backoff
# ---------------------------------------------------------------------------

def retry_fetch(url: str, headers: Optional[dict] = None, retries: int = 3,
                timeout_ms: int = 30000, on_retry: Optional[Callable] = None) -> Any:
    import urllib.error
    import urllib.request

    last_err = ""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout_ms / 1000.0) as resp:
                status = resp.status
                if status == 429 and attempt < retries:
                    retry_after = resp.headers.get("Retry-After")
                    wait = (float(retry_after) * 1000 if retry_after and retry_after.isdigit() else 1000) * (attempt + 1)
                    last_err = "HTTP 429 rate limited"
                    if on_retry:
                        on_retry(attempt, last_err, wait)
                    sleep(wait)
                    continue
                if status >= 500 and attempt < retries:
                    last_err = f"HTTP {status}"
                    wait = 800 * (attempt + 1)
                    if on_retry:
                        on_retry(attempt, last_err, wait)
                    sleep(wait)
                    continue
                raw = resp.read()
                if not raw:
                    return None
                try:
                    return json.loads(raw.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    return raw
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            # HTTPError bodies carry the REAL reason ("API Key missing or
            # invalid", scope denials, author-disabled files). Include status
            # + body in the message so callers can classify rather than guess.
            if isinstance(e, urllib.error.HTTPError):
                body = b""
                try:
                    body = e.read(300)
                except Exception:  # noqa: BLE001
                    body = b""
                detail = body.decode("utf-8", "replace").strip()
                last_err = f"HTTP {e.code}" + (f": {detail[:200]}" if detail else "")
                # Client errors are DEFINITIVE — a 403 invalid key, a 404
                # removed project, a 410 gone file. Retrying them wastes ~4 s
                # per call and never changes the outcome.
                if 400 <= e.code < 500 and e.code != 429:
                    break
            else:
                last_err = str(e)
            if attempt >= retries:
                break
            wait = 700 * (attempt + 1)
            if on_retry:
                on_retry(attempt, last_err, wait)
            sleep(wait)
    raise RuntimeError(f"Request failed after retries: {url} ({last_err})")


def fetch_json(url: str, headers: Optional[dict] = None) -> Any:
    return retry_fetch(url, headers=headers)


# ---------------------------------------------------------------------------
# Budgeted, hash-verified download
# ---------------------------------------------------------------------------

def download_to_file(url: str, dest_path: Path, max_bytes: int,
                     expected_sha1: Optional[str] = None,
                     on_progress: Optional[Callable] = None,
                     timeout_ms: int = 120000,
                     stall_ms: int = 30000,
                     headers: Optional[dict] = None) -> dict:
    """Download with a hard total deadline AND a no-data stall guard.

    urllib's socket timeout applies per socket operation, so a server that
    trickles a few bytes every minute can hold a download open for hours. We
    enforce timeout_ms as a wall-clock budget and abort if no bytes arrive for
    stall_ms — so a hung CDN connection fails in ~30s instead of hanging the
    whole build forever."""
    import socket
    import urllib.error
    import urllib.request

    mkdirp(Path(dest_path).parent)
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    tmp = Path(str(dest_path) + ".part")
    received = 0
    h = hashlib.sha1()
    deadline = time.monotonic() + timeout_ms / 1000.0
    try:
        with urllib.request.urlopen(req, timeout=min(timeout_ms / 1000.0, 30.0)) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            if total > max_bytes:
                raise RuntimeError(f"Download too large: {format_bytes(total)} exceeds limit {format_bytes(max_bytes)}")
            last_byte = time.monotonic()
            with open(tmp, "wb") as fh:
                while True:
                    if time.monotonic() > deadline:
                        raise RuntimeError(
                            f"Download timed out after {timeout_ms} ms ({format_bytes(received)} of {format_bytes(total or 0)})")
                    if time.monotonic() - last_byte > stall_ms / 1000.0:
                        raise RuntimeError(
                            f"Download stalled: no data for {stall_ms // 1000}s ({format_bytes(received)} of {format_bytes(total or 0)})")
                    try:
                        chunk = resp.read(65536)
                    except socket.timeout:
                        # per-op timeout fired; keep waiting only if bytes are still flowing
                        if time.monotonic() - last_byte > stall_ms / 1000.0:
                            raise
                        continue
                    if not chunk:
                        break
                    received += len(chunk)
                    h.update(chunk)
                    fh.write(chunk)
                    last_byte = time.monotonic()
                    if received > max_bytes:
                        raise RuntimeError(f"Download exceeded size limit {format_bytes(max_bytes)}")
                    if on_progress:
                        on_progress(received, total or None)
        sha1 = h.hexdigest()
        if expected_sha1 and expected_sha1.lower() != sha1:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise RuntimeError(f"SHA1 mismatch: expected {expected_sha1}, got {sha1}")
        try:
            tmp.replace(dest_path)
        except OSError:
            shutil.copyfile(tmp, dest_path)
            try:
                tmp.unlink()
            except OSError:
                pass
        return {"size": received, "sha1": sha1}
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, socket.timeout) as e:
        raise RuntimeError(f"Download failed for {url}: {e}") from e


# ---------------------------------------------------------------------------
# Safe ZIP helpers (stdlib zipfile)
# ---------------------------------------------------------------------------

def list_zip_entries(zip_path: Path) -> list[dict]:
    with zipfile.ZipFile(zip_path) as zf:
        return [
            {
                "name": info.filename,
                "method": info.compress_type,
                "comp_size": info.compress_size,
                "uncomp_size": info.file_size,
                "is_directory": info.is_dir(),
            }
            for info in zf.infolist()
        ]


def extract_zip_safe(zip_path: Path, dest_dir: Path,
                     caps: Optional[dict] = None) -> dict:
    """Path-traversal-proof extraction with entry-count + size caps."""
    caps = caps or {}
    max_entries = caps.get("maxEntries", 5000)
    max_total = caps.get("maxTotalBytes", 2 * 1024 ** 3)
    max_single = caps.get("maxSingleBytes", 500 * 1024 ** 2)
    root = Path(dest_dir).resolve()
    mkdirp(root)
    total = 0
    extracted = 0
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > max_entries:
            raise RuntimeError(f"ZIP has {len(infos)} entries, exceeds cap {max_entries}")
        for info in infos:
            name = info.filename
            if name.startswith("/") or name.startswith("\\") or re.match(r"^[a-zA-Z]:", name):
                raise RuntimeError(f"ZIP entry has absolute path: {name}")
            target = (root / name).resolve()
            if target != root and not str(target).startswith(str(root) + os.sep):
                raise RuntimeError(f"ZIP entry escapes destination: {name}")
            if info.is_dir():
                mkdirp(target)
                continue
            if info.file_size > max_single or total + info.file_size > max_total:
                raise RuntimeError(f"ZIP exceeds extraction budget (entry {name}, {format_bytes(info.file_size)})")
            mkdirp(target.parent)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            total += info.file_size
            extracted += 1
    return {"extracted": extracted, "totalBytes": total}


def create_zip_buffer(entries: list[dict]) -> bytes:
    """entries: [{name, data(bytes), method? 0|8}]"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for e in entries:
            zf.writestr(e["name"], e["data"])
    return buf.getvalue()


def write_zip_file(zip_path: Path, entries: list[dict]) -> None:
    mkdirp(Path(zip_path).parent)
    Path(zip_path).write_bytes(create_zip_buffer(entries))


def read_zip_entry(zip_path: Path, entry_name: str) -> Optional[bytes]:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return zf.read(entry_name)
    except Exception:
        return None


def read_zip_entry_buf(buf: bytes, entry_name: str) -> Optional[bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(buf)) as zf:
            return zf.read(entry_name)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

EVENT_STAGES = (
    "init", "parse", "search", "select", "resolve", "conflict", "download",
    "reconcile", "instance", "config", "test", "repair", "export", "report",
    "system", "perf", "launch", "modstore", "fix", "hardware", "import",
)
EVENT_LEVELS = ("info", "stage", "ok", "warn", "error", "debug")


class EventBusImpl:
    def __init__(self) -> None:
        self._listeners: list[Callable[[dict], None]] = []
        self._history: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    def subscribe(self, fn: Callable[[dict], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(fn)
        return lambda: self._unsubscribe(fn)

    def _unsubscribe(self, fn) -> None:
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def emit(self, ev: dict) -> None:
        with self._lock:
            arr = self._history.setdefault(ev.get("buildId", ""), [])
            arr.append(ev)
            if len(arr) > 5000:
                del arr[: len(arr) - 5000]
            listeners = list(self._listeners)
        for l in listeners:
            try:
                l(ev)
            except Exception:
                pass

    def history_for(self, build_id: str) -> list[dict]:
        with self._lock:
            return list(self._history.get(build_id, []))


EVENT_BUS = EventBusImpl()


# ---------------------------------------------------------------------------
# BuildLogger
# ---------------------------------------------------------------------------

class BuildLogger:
    def __init__(self, build_id: str, build_dir: Path):
        self.build_id = build_id
        self.build_dir = Path(build_dir)
        self.log_path = self.build_dir / "logs" / "build.log"
        self.events_path = self.build_dir / "logs" / "events.jsonl"
        mkdirp(self.build_dir / "logs")
        if not self.log_path.exists():
            self.log_path.write_text(f"# build {build_id}\n", "utf-8")
        if not self.events_path.exists():
            self.events_path.write_text("", "utf-8")
        self.progress = 0

    def set_progress(self, p: float) -> None:
        self.progress = max(0, min(100, round(p)))

    def log(self, level: str, stage: str, message: str, detail: Optional[str] = None,
            progress: Optional[float] = None) -> None:
        ev = {
            "buildId": self.build_id,
            "ts": int(time.time() * 1000),
            "level": level,
            "stage": stage,
            "message": message,
            "detail": detail,
            "progress": progress if progress is not None else self.progress,
        }
        line = f"[{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')}] [{level.upper()[:5]:<5}] [{stage}] {message}"
        if detail:
            line += "\n  " + "\n  ".join(detail.split("\n"))
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            with open(self.events_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev) + "\n")
        except OSError:
            pass
        EVENT_BUS.emit(ev)

    def info(self, stage: str, message: str, detail: Optional[str] = None) -> None:
        self.log("info", stage, message, detail)

    def ok(self, stage: str, message: str, detail: Optional[str] = None) -> None:
        self.log("ok", stage, message, detail)

    def warn(self, stage: str, message: str, detail: Optional[str] = None) -> None:
        self.log("warn", stage, message, detail)

    def error(self, stage: str, message: str, detail: Optional[str] = None) -> None:
        self.log("error", stage, message, detail)

    def debug(self, stage: str, message: str, detail: Optional[str] = None) -> None:
        self.log("debug", stage, message, detail)

    def stage(self, stage: str, message: str) -> None:
        self.log("stage", stage, message)

    def child(self, name: str) -> dict:
        file = self.build_dir / "logs" / name
        mkdirp(file.parent)
        file.write_text("", "utf-8")

        def write(line: str) -> None:
            try:
                with open(file, "a", encoding="utf-8", errors="replace") as f:
                    f.write(line + "\n")
            except OSError:
                pass
            self.log("debug", "test", line[:400] + ("…" if len(line) > 400 else line))

        return {"file": str(file), "write": write}


def new_build_id() -> str:
    return "b-" + uid("")
