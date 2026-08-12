"""Shared widgets + async helpers for the launcher UI."""
from __future__ import annotations

import hashlib
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap, QPainter
from PyQt6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QProgressBar,
                             QPushButton, QSizePolicy, QVBoxLayout, QWidget)

import icons
import theme
from theme import polish


# --------------------------------------------------------------------------
# Async worker
# --------------------------------------------------------------------------
class _Poster(QObject):
    """Cross-thread delivery: emits from worker threads, queued connection
    runs the callback on the main thread (QTimer.singleShot from a worker
    thread never fires — it has no event loop)."""
    _deliver = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._deliver.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

    def _dispatch(self, payload: tuple) -> None:
        fn, arg = payload
        fn(arg)


_poster = _Poster()


def _post(fn: Callable, arg) -> None:
    """Run a callback on the main thread (thread-safe, queued)."""
    _poster._deliver.emit((fn, arg))


class _Worker(QRunnable):
    def __init__(self, fn: Callable, on_ok: Callable, on_err: Optional[Callable]):
        super().__init__()
        self.fn, self.on_ok, self.on_err = fn, on_ok, on_err

    def run(self):  # worker thread
        try:
            result = self.fn()
        except Exception as e:  # noqa: BLE001 — surfaced to the UI
            if self.on_err:
                _post(self.on_err, e)
            return
        _post(self.on_ok, result)


_pool = QThreadPool.globalInstance()


def run_async(fn: Callable, on_ok: Callable, on_err: Optional[Callable] = None) -> None:
    _pool.start(_Worker(fn, on_ok, on_err))


class _StreamWorker(QRunnable):
    """Long-lived stream: repeatedly calls `read_once()` (a blocking generator
    next / socket read) in a worker thread and delivers each batch of events
    to the main thread. Ends when read_once() raises StopIteration or the
    stop_event is set."""

    def __init__(self, read_once: Callable, on_events: Callable, stop_event: threading.Event):
        super().__init__()
        self.read_once = read_once
        self.on_events = on_events
        self.stop_event = stop_event

    def run(self):
        try:
            while not self.stop_event.is_set():
                events = self.read_once()
                if events is None or not events:
                    break
                _post(self.on_events, events)
        except StopIteration:
            pass
        except Exception:  # noqa: BLE001 — stream ended; UI falls back to polling
            pass


def start_stream(read_once: Callable, on_events: Callable, stop_event: threading.Event) -> QRunnable:
    """Run a blocking stream in the background; each batch of events is
    delivered to the main thread via the queued bridge."""
    w = _StreamWorker(read_once, on_events, stop_event)
    _pool.start(w)
    return w


# --------------------------------------------------------------------------
# Icon cache (real provider icons loaded off the UI thread)
# --------------------------------------------------------------------------
class _ImageWorker(QRunnable):
    """Fetch image bytes away from the GUI thread.

    QPixmap is intentionally created later on the Qt main thread; constructing
    pixmaps in Python worker threads is undefined on several Qt platforms and
    was the reason some catalog images intermittently stayed as letter tiles.
    """

    MAX_BYTES = 5 * 1024 * 1024
    DISK_TTL_SECONDS = 30 * 24 * 3600

    def __init__(self, url: str, cache_path: Path, deliver: Callable):
        super().__init__()
        self.url = url
        self.cache_path = cache_path
        self.deliver = deliver

    def run(self) -> None:
        data: bytes | None = None
        try:
            if (self.cache_path.is_file()
                    and time.time() - self.cache_path.stat().st_mtime < self.DISK_TTL_SECONDS):
                data = self.cache_path.read_bytes()
            else:
                req = urllib.request.Request(
                    self.url,
                    headers={
                        "User-Agent": "AIMinecraftLauncher/1.1",
                        "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*;q=0.5",
                    },
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    declared = int(resp.headers.get("Content-Length") or 0)
                    if declared > self.MAX_BYTES:
                        raise ValueError("provider image is too large")
                    data = resp.read(self.MAX_BYTES + 1)
                if len(data) > self.MAX_BYTES:
                    raise ValueError("provider image is too large")
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_bytes(data)
        except Exception:  # noqa: BLE001 - the UI keeps its local fallback tile
            data = None
        try:
            self.deliver(self.url, data)
        except RuntimeError:
            pass


class IconCache(QObject):
    ready = pyqtSignal(str, object)  # url, bytes | None

    def __init__(self):
        super().__init__()
        self._cache: dict[str, QPixmap] = {}
        self._pending: dict[str, list[tuple[QLabel, int]]] = {}
        self._loading: set[str] = set()
        self._failed_at: dict[str, float] = {}
        local = os.environ.get("LOCALAPPDATA")
        root = Path(local) if local else Path.home() / ".cache"
        self._disk_dir = root / "AI Modpack Builder" / "cache" / "icons"
        self._image_pool = QThreadPool()
        self._image_pool.setMaxThreadCount(6)
        self._closed = False
        self.ready.connect(self._apply)

    def pixmap_for(self, url: str, size: int = 48) -> Optional[QPixmap]:
        pm = self._cache.get(url)
        if pm and not pm.isNull():
            return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self.request(url, None, size)
        return None

    def request(self, url: str, label: Optional[QLabel], size: int = 48) -> None:
        if not url or self._closed:
            return
        pm = self._cache.get(url)
        if pm and not pm.isNull():
            if label:
                try:
                    label.setPixmap(pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
                except RuntimeError:
                    pass
            return
        if label is not None:
            waiting = self._pending.setdefault(url, [])
            if not any(existing is label and existing_size == size for existing, existing_size in waiting):
                waiting.append((label, size))
        if url in self._loading:
            return
        # Avoid hammering a broken URL while cards are re-rendered.
        if time.monotonic() - self._failed_at.get(url, 0.0) < 120:
            return
        self._loading.add(url)
        digest = hashlib.sha256(url.encode("utf-8", "replace")).hexdigest()
        try:
            self._image_pool.start(_ImageWorker(url, self._disk_dir / f"{digest}.img", self.ready.emit))
        except RuntimeError:
            self._closed = True
            self._loading.discard(url)

    def _apply(self, url: str, data: bytes | None) -> None:
        self._loading.discard(url)
        pm = QPixmap()
        if data:
            pm.loadFromData(data)
        if pm.isNull():
            self._failed_at[url] = time.monotonic()
        else:
            self._cache[url] = pm
            self._failed_at.pop(url, None)
        labels = self._pending.pop(url, [])
        if pm.isNull():
            return
        for target, size in labels:
            try:
                # Apply even when a parent page is currently hidden. Checking
                # isVisible() here discarded fast cache hits before a new card
                # had been inserted into its layout.
                target.setPixmap(pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
            except RuntimeError:
                pass  # card was deleted while the request was in flight

    def shutdown(self, timeout_ms: int = 15000) -> bool:
        """Drain private image workers before Qt destroys their signal owner."""
        self._closed = True
        self._pending.clear()
        try:
            return self._image_pool.waitForDone(timeout_ms)
        except RuntimeError:
            return True


icon_cache = IconCache()


def avatar(text: str, color: str = theme.GREEN, size: int = 48, radius: int = 10) -> QPixmap:
    """Letter avatar fallback (used when a provider icon is unavailable)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(theme.HOVER))
    p.setPen(QColor("#2A2F35"))
    p.drawRoundedRect(0, 0, size - 1, size - 1, radius, radius)
    p.setPen(QColor(color))
    f = p.font()
    f.setPointSize(max(10, size // 2))
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, (text or "?").strip()[:1].upper())
    p.end()
    return pm


def icon_pixmap(name: str, color: str, size: int) -> QPixmap:
    return icons.pix(name, color, size)


# --------------------------------------------------------------------------
# Basic builders
# --------------------------------------------------------------------------
def card(parent: QWidget, hover: bool = False) -> QFrame:
    w = QFrame(parent)
    w.setProperty("cls", "card-hover" if hover else "card")
    polish(w)
    return w


def label(parent: QWidget, text: str = "", cls: str = "sub") -> QLabel:
    l = QLabel(text, parent)
    l.setProperty("cls", cls)
    l.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    polish(l)
    return l


def button(parent: QWidget, text: str = "", cls: str = "btn-dark", icon_name: Optional[str] = None,
           icon_color: Optional[str] = None) -> QPushButton:
    b = QPushButton(text, parent)
    b.setProperty("cls", cls)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        b.setIcon(icons.icon(icon_name, icon_color or (theme.GREEN if cls == "btn-primary" else theme.TEXT2)))
        b.setIconSize(b.iconSize().scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio))
    polish(b)
    return b


def icon_btn(parent: QWidget, icon_name: str, tip: str = "", color: str = theme.TEXT2) -> QPushButton:
    b = QPushButton(parent)
    b.setProperty("cls", "iconbtn")
    b.setIcon(icons.icon(icon_name, color))
    b.setIconSize(b.iconSize().scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    polish(b)
    return b


def pill(parent: QWidget, text: str, active: bool = False, cls: str = "pill",
         icon_name: Optional[str] = None, icon_color: Optional[str] = None) -> QPushButton:
    # Ampersands are literal product text here, never keyboard-mnemonic
    # markers (for example "Create & Automate").
    b = QPushButton(text.replace("&", "&&"), parent)
    b.setProperty("cls", cls)
    b.setProperty("active", "true" if active else "false")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setCheckable(False)
    if icon_name:
        b.setIcon(icons.icon(icon_name, icon_color or theme.TEXT2, 14))
        b.setIconSize(b.iconSize().scaled(14, 14, Qt.AspectRatioMode.KeepAspectRatio))
    polish(b)
    return b


def progress(parent: QWidget, value: int = 0, thin: bool = True) -> QProgressBar:
    p = QProgressBar(parent)
    p.setRange(0, 100)
    p.setValue(value)
    p.setTextVisible(False)
    p.setProperty("cls", "thin" if thin else "")
    polish(p)
    return p


def toggle(parent: QWidget, checked: bool = False) -> QCheckBox:
    t = QCheckBox(parent)
    t.setChecked(checked)
    t.setCursor(Qt.CursorShape.PointingHandCursor)
    return t


def vbox(parent: QWidget, spacing: int = 8, margins=0) -> QVBoxLayout:
    lay = QVBoxLayout(parent)
    lay.setSpacing(spacing)
    if isinstance(margins, int):
        lay.setContentsMargins(margins, margins, margins, margins)
    else:
        lay.setContentsMargins(*margins)
    return lay


def hbox(parent: QWidget, spacing: int = 8, margins=0) -> QHBoxLayout:
    lay = QHBoxLayout(parent)
    lay.setSpacing(spacing)
    if isinstance(margins, int):
        lay.setContentsMargins(margins, margins, margins, margins)
    else:
        lay.setContentsMargins(*margins)
    return lay


def clear_layout(layout) -> None:
    """Recursively remove and delete all items of a layout."""
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            # deleteLater() alone leaves the old widget paintable until Qt
            # returns to its outer event loop. Detach it immediately so quick
            # tab/status changes never display two panels on top of each other.
            w.hide()
            w.setParent(None)
            w.deleteLater()
            continue
        sub = item.layout()
        if sub is not None:
            clear_layout(sub)
        elif item.spacerItem() is not None:
            pass


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------
def fmt_bytes(n: Optional[int]) -> str:
    if not n:
        return "0 B"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def fmt_downloads(n: Optional[int]) -> str:
    if not n:
        return "0"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def fmt_ago(iso: Optional[str]) -> str:
    if not iso:
        return "Never"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        secs = max(0, int((now - dt).total_seconds()))
    except Exception:  # noqa: BLE001
        return "Just now"
    if secs < 60:
        return "Just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    if secs < 86400 * 7:
        return f"{secs // 86400}d ago"
    return iso[:10]


def fmt_time(iso: Optional[str]) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return iso
