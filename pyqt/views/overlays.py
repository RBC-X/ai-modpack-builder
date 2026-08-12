"""Floating overlays: launch progress, crash drawer, account & import modals."""
from __future__ import annotations

import json
import os
import threading

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
                             QLineEdit, QPlainTextEdit, QSpinBox, QVBoxLayout, QWidget)

import theme
import minecraft_auth
from common import (button, card, hbox, icon_btn, icon_pixmap, label, pill,
                    progress, run_async, vbox)

def _state_path() -> str:
    """UI state file: LOCALAPPDATA when frozen (bundle may be read-only),
    the checkout's pyqt/ dir in dev."""
    from engine.core import is_frozen, data_dir
    if is_frozen():
        return str(data_dir() / "state.json")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state.json")


STATE_PATH = _state_path()


def _microsoft_icon(size: int = 18) -> QIcon:
    """Microsoft's familiar four-pane mark for the system-browser sign-in action."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    gap = max(1, size // 10)
    tile = (size - gap) // 2
    for x, y, color in [
        (0, 0, "#F25022"), (tile + gap, 0, "#7FBA00"),
        (0, tile + gap, "#00A4EF"), (tile + gap, tile + gap, "#FFB900"),
    ]:
        painter.fillRect(x, y, tile, tile, QColor(color))
    painter.end()
    return QIcon(pm)


def _load_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _save_state(st: dict) -> None:
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2)
    except Exception:  # noqa: BLE001
        pass


# ===========================================================================
# Launch progress overlay (floating bottom-right)
# ===========================================================================
class LaunchOverlay(QFrame):
    stop_requested = pyqtSignal()
    view_crash = pyqtSignal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setProperty("cls", "panel")
        theme.polish(self)
        self.setFixedWidth(430)
        self.hide()
        self._status: dict = {}
        self._name = "pack"
        self._mode = "starting"

        self._lay = vbox(self, 12, margins=(18, 14, 18, 14))

    def show_launch(self, name: str) -> None:
        self._name = name
        self._mode = "starting"
        self._status = {}
        self._render()
        self.show()
        self.raise_()
        p = self.parentWidget()
        self._reposition(p.width() if p else 1320, p.height() if p else 840)

    def apply_status(self, status: dict) -> None:
        phase = status.get("phase") or ""
        running = bool(status.get("running"))
        err = status.get("error")
        if running:
            self._mode = "running"
        elif phase == "error" or err:
            self._mode = "crashed"
        elif phase == "relaunching":
            self._mode = "relaunching"
        else:
            self._mode = "starting"
        self._status = status
        self._render()
        if self.isHidden():
            self.show()
            self.raise_()

    def _render(self) -> None:
        from common import clear_layout
        clear_layout(self._lay)
        st = self._status or {}
        mode = self._mode

        head = QHBoxLayout()
        head.setSpacing(8)
        if mode == "crashed":
            head.addWidget(self._ic("alert", theme.DANGER))
            head.addWidget(label(self, "Minecraft Failed to Start", "h3"))
        elif mode == "running":
            dot = QLabel(self)
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background: {theme.GREEN}; border-radius: 5px;")
            head.addWidget(dot)
            head.addWidget(label(self, f"{self._name} is Running", "h3"))
        elif mode == "relaunching":
            head.addWidget(self._ic("refresh", theme.WARNING))
            head.addWidget(label(self, f"Recovering {self._name}", "h3"))
        else:
            head.addWidget(self._ic("refresh", theme.GREEN))
            head.addWidget(label(self, f"Starting {self._name}", "h3"))
        head.addStretch(1)
        x = icon_btn(self, "x", "Dismiss")
        x.clicked.connect(self.hide)
        head.addWidget(x)
        self._lay.addLayout(head)

        if mode == "crashed":
            msg = st.get("error") or "Minecraft process terminated with a non-zero exit code."
            self._lay.addWidget(label(self, msg[:200], "sub"))
            missing = st.get("missingDeps")
            if missing:
                row = QHBoxLayout()
                row.setSpacing(6)
                row.addWidget(label(self, "Missing:", "warn"))
                for m in missing[:4]:
                    row.addWidget(pill(self, m, False, "pill-danger"))
                row.addStretch(1)
                self._lay.addLayout(row)
            b = button(self, "VIEW CRASH REPORT", "btn-danger", "filetext")
            b.clicked.connect(self.view_crash.emit)
            self._lay.addWidget(b)
        elif mode == "relaunching":
            stage = st.get("stage") or "Silent close detected — relaunching…"
            row = QHBoxLayout()
            row.addWidget(label(self, stage, "sub"), 1)
            row.addWidget(label(self, f"{int(st.get('progress') or 54)}%", "warn"))
            self._lay.addLayout(row)
            self._lay.addWidget(progress(self, int(st.get("progress") or 54)))
            ctx = st.get("closeContext") or {}
            if ctx:
                reason = ctx.get("reason") or "Game closed without a crash report — auto-relaunch scheduled."
                tail = (ctx.get("logTail") or [])[-6:]
                box = QPlainTextEdit(self)
                box.setReadOnly(True)
                box.setMaximumHeight(110)
                box.setStyleSheet(
                    f"QPlainTextEdit {{ background: {theme.CARD}; color: {theme.TEXT2}; border: 1px solid {theme.BORDER2};"
                    f" border-radius: 6px; padding: 6px; font-family: Consolas, monospace; font-size: 11px; }}")
                box.setPlainText(reason + ("\n\n" + "\n".join(tail) if tail else ""))
                self._lay.addWidget(box)
            stop = button(self, "STOP", "btn-dark")
            stop.clicked.connect(self.stop_requested.emit)
            self._lay.addWidget(stop)
        elif mode == "running":
            c = QFrame(self)
            c.setStyleSheet(f"background: {theme.GREEN_GLOW}; border: 1px solid rgba(57,184,106,0.3); border-radius: 8px;")
            cl = hbox(c, 10, margins=(12, 10, 12, 10))
            pid = st.get("pid")
            cl.addWidget(label(c, f"Main menu reached • PID {pid}" if pid else "Main menu reached", "h3"))
            cl.addStretch(1)
            stop = button(c, "STOP", "btn-danger")
            stop.clicked.connect(self.stop_requested.emit)
            cl.addWidget(stop)
            self._lay.addWidget(c)
        else:
            pct = int(st.get("progress") or 0)
            stage = st.get("stage") or "Preparing launch…"
            row = QHBoxLayout()
            row.addWidget(label(self, stage, "sub"), 1)
            row.addWidget(label(self, f"{pct}%", "green"))
            self._lay.addLayout(row)
            self._lay.addWidget(progress(self, pct))
            mods = st.get("modsLoaded")
            total = st.get("modsTotal")
            self._lay.addWidget(label(self, f"Mods: {mods}/{total}" if mods and total else "Waiting for the game process…", "muted"))
            stop = button(self, "STOP", "btn-dark")
            stop.clicked.connect(self.stop_requested.emit)
            self._lay.addWidget(stop)

        # Status changes rebuild the card. Recompute its natural height after
        # the rebuild and pin it back to the bottom-right of the real window.
        self._lay.activate()
        self.adjustSize()
        if self.isVisible():
            QTimer.singleShot(0, self._resize_and_reposition)

    def _resize_and_reposition(self) -> None:
        self._lay.activate()
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self._reposition(parent.width(), parent.height())
            self.raise_()

    def _ic(self, name: str, color: str) -> QLabel:
        l = QLabel(self)
        l.setPixmap(icon_pixmap(name, color, 18))
        return l

    def _reposition(self, w: int, h: int) -> None:
        self.move(w - self.width() - 24, h - self.height() - 24)


# ===========================================================================
# Import progress overlay (CurseForge-style: stage + cancel, then Play)
# ===========================================================================
class ImportOverlay(QFrame):
    cancel_requested = pyqtSignal()
    play_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setProperty("cls", "panel")
        theme.polish(self)
        self.setFixedWidth(430)
        self.hide()
        self._mode = "importing"
        self._name = "pack"
        self._build_id: str | None = None
        self._lay = vbox(self, 12, margins=(18, 14, 18, 14))

    def show_import(self, name: str) -> None:
        self._name = name
        self._build_id = None
        self._mode = "importing"
        self._render("Preparing import…", 0, 0)
        self.show()
        self.raise_()
        p = self.parentWidget()
        self._reposition(p.width() if p else 1320, p.height() if p else 840)

    def is_importing(self) -> bool:
        return self._mode == "importing" and not self.isHidden()

    def set_progress(self, stage: str, done: int, total: int) -> None:
        if self._mode != "importing":
            return
        self._render(stage, done, total)

    def set_cancelling(self) -> None:
        if self._mode == "importing":
            self._render("Cancelling…", 0, 0)

    def set_done(self, build_id: str, name: str, summary: str) -> None:
        self._build_id = build_id
        self._name = name
        self._mode = "done"
        self._render(summary, 100, 100)
        self.show()
        self.raise_()
        self._resize_and_reposition()

    def set_error(self, msg: str) -> None:
        self._mode = "error"
        self._render(msg, 0, 0)
        self.show()
        self.raise_()
        self._resize_and_reposition()

    def _render(self, stage: str, done: int, total: int) -> None:
        from common import clear_layout
        clear_layout(self._lay)
        mode = self._mode

        head = QHBoxLayout()
        head.setSpacing(8)
        if mode == "done":
            head.addWidget(self._ic("check", theme.GREEN))
            head.addWidget(label(self, f"{self._name} Imported", "h3"))
        elif mode == "error":
            head.addWidget(self._ic("alert", theme.DANGER))
            head.addWidget(label(self, "Import Failed", "h3"))
        else:
            head.addWidget(self._ic("download", theme.GREEN))
            head.addWidget(label(self, f"Importing {self._name}", "h3"))
        head.addStretch(1)
        x = icon_btn(self, "x", "Dismiss")
        x.clicked.connect(self._dismiss)
        head.addWidget(x)
        self._lay.addLayout(head)

        if mode == "importing":
            pct = int((done / total) * 100) if total and done >= 0 else 0
            row = QHBoxLayout()
            row.addWidget(label(self, stage, "sub"), 1)
            if total:
                row.addWidget(label(self, f"{done}/{total}", "muted"))
            row.addWidget(label(self, f"{pct}%", "green"))
            self._lay.addLayout(row)
            self._lay.addWidget(progress(self, pct))
            self._lay.addWidget(label(self, "Installing mods, configs and overrides…", "muted"))
            cancel = button(self, "CANCEL", "btn-dark")
            cancel.clicked.connect(self.cancel_requested.emit)
            self._lay.addWidget(cancel)
        elif mode == "done":
            self._lay.addWidget(label(self, stage, "sub"))
            play = button(self, "PLAY", "btn-green", "play")
            play.clicked.connect(lambda: self.play_requested.emit(self._build_id or ""))
            self._lay.addWidget(play)
            hint = label(self, "or dismiss to keep browsing", "muted")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._lay.addWidget(hint)
        else:  # error
            self._lay.addWidget(label(self, (stage or "Import failed.")[:260], "sub"))
            close = button(self, "CLOSE", "btn-dark")
            close.clicked.connect(self.hide)
            self._lay.addWidget(close)

        self._lay.activate()
        self.adjustSize()
        if self.isVisible():
            QTimer.singleShot(0, self._resize_and_reposition)

    def _dismiss(self) -> None:
        if self._mode == "importing":
            self.cancel_requested.emit()
        else:
            self.hide()

    def _ic(self, name: str, color: str) -> QLabel:
        l = QLabel(self)
        l.setPixmap(icon_pixmap(name, color, 18))
        return l

    def _resize_and_reposition(self) -> None:
        self._lay.activate()
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self._reposition(parent.width(), parent.height())
            self.raise_()

    def _reposition(self, w: int, h: int) -> None:
        self.move(w - self.width() - 24, h - self.height() - 24)


# ===========================================================================
# Crash drawer (right slide-in)
# ===========================================================================
class CrashDrawer(QFrame):
    close_requested = pyqtSignal()
    fix_requested = pyqtSignal()

    def __init__(self, parent: QWidget, api):
        super().__init__(parent)
        self.api = api
        self.setProperty("cls", "panel")
        theme.polish(self)
        self.setFixedWidth(560)
        self._build_id: str | None = None
        self._lay = vbox(self, 14, margins=(22, 18, 22, 18))
        self.hide()

    def show_report(self, build_id: str, status: dict, name: str = "") -> None:
        self._build_id = build_id
        self._name = name
        self._status = status
        self._render()
        self.show()
        self.raise_()
        p = self.parentWidget()
        self._reposition(p.width() if p else 1320, p.height() if p else 840)

    def _render(self) -> None:
        from common import clear_layout
        clear_layout(self._lay)
        st = self._status or {}
        missing = st.get("missingDeps") or []

        head = QHBoxLayout()
        head.addWidget(self._ic("alert", theme.DANGER))
        head.addWidget(label(self, "Minecraft Crash Report", "h2"))
        head.addStretch(1)
        x = icon_btn(self, "x", "Close")
        x.clicked.connect(self.close_requested.emit)
        head.addWidget(x)
        self._lay.addLayout(head)

        diag = QFrame(self)
        diag.setStyleSheet(f"background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.3); border-radius: 10px;")
        dl = vbox(diag, 8, margins=(16, 12, 16, 12))
        dl.addWidget(label(diag, "AI DIAGNOSIS & ROOT CAUSE", "danger"))
        err = st.get("error") or "The game process exited unexpectedly."
        dl.addWidget(label(diag, err[:300], "h3"))
        if missing:
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(label(diag, "Missing Mod Dependencies:", "warn"))
            for m in missing:
                row.addWidget(pill(diag, m, False, "pill-danger"))
            row.addStretch(1)
            dl.addLayout(row)
        self._lay.addWidget(diag)

        act = card(self)
        al = vbox(act, 10, margins=(16, 12, 16, 12))
        al.addWidget(label(act, "Recommended AI Resolution", "sub"))
        fix = button(act, "ADD MISSING MODS & RELAUNCH", "btn-primary", "wrench", theme.BG)
        fix.setEnabled(bool(missing))
        fix.clicked.connect(self.fix_requested.emit)
        al.addWidget(fix)
        if not missing:
            al.addWidget(label(act, "No missing dependencies detected — the engine can still run a full repair scan from the Pack Detail page.", "muted"))
        self._lay.addWidget(act)

        meta = card(self)
        ml = vbox(meta, 6, margins=(16, 12, 16, 12))
        for k, v in [("Modpack Target:", self._name or "—"), ("Phase:", st.get("phase") or "—"),
                     ("Crash files:", ", ".join((st.get("crashFiles") or [])[:2]) or "—")]:
            row = QHBoxLayout()
            row.addWidget(label(meta, k, "sub"))
            row.addStretch(1)
            row.addWidget(label(meta, str(v)[:80], "h3"))
            ml.addLayout(row)
        self._lay.addWidget(meta)

        # raw evidence
        ev = st.get("crashFiles") or []
        if ev:
            self._load_evidence(ev[0].rsplit("/", 1)[-1])

    def _load_evidence(self, filename: str) -> None:
        def fetch():
            return self.api.evidence(self._build_id, filename)

        def ok(text):
            from common import clear_layout
            box = QPlainTextEdit(self)
            box.setProperty("cls", "console")
            box.setReadOnly(True)
            box.setMinimumHeight(200)
            box.setPlainText(text[:6000])
            clear_layout(self._lay)
            # rebuild with evidence appended
            self._render()
            self._lay.addWidget(label(self, "Raw Crash Report", "sub"))
            self._lay.addWidget(box)
            self._reposition(parent().width(), parent().height())

        run_async(fetch, ok, None)

    def _ic(self, name: str, color: str) -> QLabel:
        l = QLabel(self)
        l.setPixmap(icon_pixmap(name, color, 20))
        return l

    def _reposition(self, w: int, h: int) -> None:
        self.setGeometry(w - self.width() - 16, 16, self.width(), h - 32)
        self.raise_()


# ===========================================================================
# Account modal
# ===========================================================================
class AccountModal(QDialog):
    account_changed = pyqtSignal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Minecraft Account")
        self.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        self.setModal(True)
        self.resize(560, 520)
        self._cancel_login = threading.Event()
        lay = vbox(self, 14, margins=(22, 18, 22, 18))
        lay.addWidget(label(self, "Minecraft Account", "h2"))
        intro = label(
            self,
            "Connect the Microsoft account that owns Minecraft: Java Edition. Your password is entered only on Microsoft's website.",
            "muted",
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        ms = card(self)
        ml = vbox(ms, 9, margins=(14, 12, 14, 12))
        ml.addWidget(label(ms, "Microsoft account", "h3"))
        self._profile = label(ms, "Not connected", "muted")
        self._profile.setWordWrap(True)
        ml.addWidget(self._profile)
        self._microsoft_helper = label(
            ms,
            "A secure Microsoft sign-in page will open in your browser and return you here automatically.",
            "small",
        )
        self._microsoft_helper.setWordWrap(True)
        ml.addWidget(self._microsoft_helper)
        actions = hbox(ms, 8)
        self._signin = button(ms, "Sign in with Microsoft", "btn-microsoft")
        self._signin.setIcon(_microsoft_icon())
        self._signin.clicked.connect(self._start_microsoft)
        actions.addWidget(self._signin, 1)
        ml.addLayout(actions)
        self._auth_status = label(ms, "", "muted")
        self._auth_status.setWordWrap(True)
        ml.addWidget(self._auth_status)
        self._disconnect_button = button(ms, "DISCONNECT ACCOUNT", "btn-dark", "close")
        self._disconnect_button.clicked.connect(self._disconnect)
        self._disconnect_button.hide()
        ml.addWidget(self._disconnect_button)
        lay.addWidget(ms)

        local = card(self)
        local_lay = vbox(local, 8, margins=(14, 12, 14, 12))
        local_lay.addWidget(label(local, "Offline / local profile", "h3"))
        local_hint = label(local, "For local testing only; it cannot join authenticated online servers.", "small")
        local_hint.setWordWrap(True)
        local_lay.addWidget(local_hint)
        self._name = QLineEdit(local)
        self._name.setPlaceholderText("Enter Minecraft Username...")
        local_lay.addWidget(self._name)
        b = button(local, "USE OFFLINE PROFILE", "btn-dark", "usercheck")
        b.clicked.connect(self._save_offline)
        local_lay.addWidget(b)
        lay.addWidget(local)
        lay.addStretch(1)
        self._reload()
    def showEvent(self, event) -> None:  # noqa: N802
        self._reload()
        super().showEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cancel_login.set()
        super().closeEvent(event)

    def _reload(self) -> None:
        st = _load_state()
        offline = st.get("offlineAccountName") or (
            st.get("accountName") if st.get("accountMode") != "microsoft" else "")
        self._name.setText(offline or "")
        connected = st.get("accountMode") == "microsoft" and minecraft_auth.has_saved_credential()
        if connected:
            name = st.get("minecraftProfileName") or st.get("accountName") or "Minecraft profile"
            self._profile.setText(f"Connected as {name}  •  Microsoft / Java Edition")
            self._profile.setProperty("cls", "green")
            self._signin.setText("Switch Microsoft account")
        else:
            self._profile.setText("Not connected")
            self._profile.setProperty("cls", "muted")
            self._signin.setText("Sign in with Microsoft")
        try:
            minecraft_auth.configured_client_id()
            microsoft_available = True
        except Exception:
            microsoft_available = False
        if not microsoft_available and not connected:
            self._signin.setText("Microsoft sign-in unavailable")
            self._signin.setEnabled(False)
            self._microsoft_helper.setText(
                "Publisher setup is pending: this release does not yet include an approved Microsoft application ID. Offline testing remains available below.")
            self._auth_status.setText("No Microsoft credentials are requested or embedded in this build.")
        else:
            self._signin.setEnabled(True)
            self._microsoft_helper.setText(
                "A secure Microsoft sign-in page will open in your browser and return you here automatically.")
        theme.polish(self._profile)
        self._disconnect_button.setVisible(connected)

    def _start_microsoft(self) -> None:
        try:
            client_id = minecraft_auth.configured_client_id()
        except Exception as exc:  # noqa: BLE001
            self._auth_status.setText(str(exc))
            return
        self._cancel_login.set()
        self._cancel_login = threading.Event()
        self._signin.setEnabled(False)
        self._auth_status.setText("Opening Microsoft's secure sign-in page…")
        run_async(lambda: minecraft_auth.begin_browser_login(client_id),
                  lambda flow: self._browser_ready(client_id, flow), self._auth_failed)

    def _browser_ready(self, client_id: str, flow: minecraft_auth.BrowserLogin) -> None:
        QDesktopServices.openUrl(QUrl(flow.authorize_url))
        self._auth_status.setText("Finish signing in with Microsoft in your browser. This window will update automatically…")
        run_async(lambda: minecraft_auth.finish_browser_login(flow, self._cancel_login),
                  lambda session: self._auth_complete(client_id, session), self._auth_failed)

    def _auth_complete(self, client_id: str, session: dict) -> None:
        st = _load_state()
        name = session.get("username") or "Minecraft profile"
        st.update({
            "accountMode": "microsoft",
            "microsoftClientId": client_id,
            "minecraftProfileName": name,
            "minecraftProfileId": session.get("uuid") or "",
            "accountName": name,
        })
        _save_state(st)
        self._auth_status.setText(f"Connected as {name}. New launches will use this account.")
        self._signin.setEnabled(True)
        self._reload()
        self.account_changed.emit()

    def _auth_failed(self, error: Exception) -> None:
        self._signin.setEnabled(True)
        self._auth_status.setText(str(error))

    def _disconnect(self) -> None:
        try:
            minecraft_auth.disconnect()
        except Exception as exc:  # noqa: BLE001
            self._auth_status.setText(str(exc))
            return
        st = _load_state()
        st["accountMode"] = "offline"
        st["accountName"] = st.get("offlineAccountName") or "N/A"
        st.pop("minecraftProfileName", None)
        st.pop("minecraftProfileId", None)
        _save_state(st)
        self._auth_status.setText("Microsoft account disconnected from this launcher.")
        self._reload()
        self.account_changed.emit()

    def _save_offline(self) -> None:
        name = self._name.text().strip()
        if not name:
            return
        st = _load_state()
        st["accountMode"] = "offline"
        st["offlineAccountName"] = name
        st["accountName"] = name
        _save_state(st)
        self._auth_status.setText(f"Offline profile {name} selected.")
        self._reload()
        self.account_changed.emit()


# ===========================================================================
# Import modal (provider import + local .mrpack / ZIP drag & drop)
# ===========================================================================
class ImportModal(QDialog):
    import_pack = pyqtSignal(str, str)      # provider, projectId/slug
    import_file = pyqtSignal(str)           # local archive path

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Import Modpack")
        self.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        self.resize(480, 420)
        self.setAcceptDrops(True)
        self._local_path: str | None = None
        lay = vbox(self, 12, margins=(22, 18, 22, 18))
        lay.addWidget(label(self, "Import Modpack", "h2"))

        # ---- Local file (drag & drop / browse) ----
        local = card(self)
        ll = vbox(local, 10, margins=(16, 14, 16, 14))
        ll.addWidget(label(local, "Local .mrpack / CurseForge ZIP", "h3"))
        self._drop = QFrame(local)
        self._drop.setStyleSheet(
            f"QFrame {{ border: 2px dashed {theme.BORDER2}; border-radius: 10px; background: rgba(32,36,40,0.4); }}"
            f"QFrame:hover {{ border-color: {theme.GREEN}; }}")
        dl = vbox(self._drop, 6, margins=(16, 18, 16, 18))
        dl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel(self._drop)
        ic.setPixmap(icon_pixmap("upload", theme.GREEN, 28))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(ic)
        self._drop_text = label(self._drop, "Drag & drop a .mrpack or CurseForge ZIP here", "sub")
        self._drop_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(self._drop_text)
        browse = button(self._drop, "Browse…", "btn-dark", "folder")
        browse.clicked.connect(self._browse)
        dl.addWidget(browse, 0, Qt.AlignmentFlag.AlignCenter)
        ll.addWidget(self._drop)
        ll.addWidget(label(local, "The archive is uploaded to the engine, parsed, resolved, and installed into a new pack (mods, shaders, resource packs, configs).", "muted"))
        lay.addWidget(local)

        sep = QFrame(self)
        sep.setFixedHeight(1)
        sep.setProperty("cls", "sep")
        theme.polish(sep)
        lay.addWidget(sep)

        # ---- Provider import ----
        prov = card(self)
        pl = vbox(prov, 10, margins=(16, 14, 16, 14))
        pl.addWidget(label(prov, "Or import from a provider", "h3"))
        row = QHBoxLayout()
        row.addWidget(label(prov, "Provider:", "sub"))
        self._prov = QComboBox(prov)
        self._prov.addItems(["Modrinth", "CurseForge"])
        row.addWidget(self._prov, 1)
        pl.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(label(prov, "Pack id/slug:", "sub"))
        self._pid = QLineEdit(prov)
        self._pid.setPlaceholderText("e.g. fabulously-optimized")
        row2.addWidget(self._pid, 1)
        pl.addLayout(row2)
        hint = QHBoxLayout()
        hint.addWidget(label(prov, "Popular:", "muted"))
        for ex in ["fabulously-optimized", "horrors-in-the-fog", "better-mc"]:
            p = pill(prov, ex, False, "pill")
            p.clicked.connect(lambda _=False, e=ex: self._pid.setText(e))
            hint.addWidget(p)
        hint.addStretch(1)
        pl.addLayout(hint)
        go_prov = button(prov, "IMPORT FROM PROVIDER", "btn-dark", "download", theme.GREEN)
        def do_prov():
            pid = self._pid.text().strip()
            if not pid:
                return
            self.import_pack.emit(self._prov.currentText().lower(), pid)
            self.accept()
        go_prov.clicked.connect(do_prov)
        pl.addWidget(go_prov)
        lay.addWidget(prov)

        act = QHBoxLayout()
        act.addStretch(1)
        cancel = button(self, "Cancel", "btn-dark")
        cancel.clicked.connect(self.reject)
        go = button(self, "IMPORT LOCAL FILE", "btn-primary", "upload", theme.BG)
        def do_local():
            if self._local_path:
                self.import_file.emit(self._local_path)
                self.accept()
        go.clicked.connect(do_local)
        act.addWidget(cancel)
        act.addWidget(go)
        lay.addLayout(act)

    def _browse(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Select modpack archive", "",
                                              "Modpack archives (*.mrpack *.zip);;All files (*)")
        if path:
            self._set_local(path)

    def _set_local(self, path: str) -> None:
        self._local_path = path
        import os
        self._drop_text.setText(os.path.basename(path))
        self._drop_text.setProperty("cls", "green")
        theme.polish(self._drop_text)
        self._drop.setStyleSheet(f"QFrame {{ border: 2px solid {theme.GREEN}; border-radius: 10px; background: {theme.GREEN_GLOW}; }}")

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            for u in event.mimeData().urls():
                p = u.toLocalFile().lower()
                if p.endswith((".mrpack", ".zip")):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event) -> None:  # noqa: N802
        for u in event.mimeData().urls():
            path = u.toLocalFile()
            if path.lower().endswith((".mrpack", ".zip")):
                self._set_local(path)
                event.acceptProposedAction()
                return


# ===========================================================================
# New pack modal (build your own pack from the Library)
# ===========================================================================
class NewPackDialog(QDialog):
    """Blank-pack creation: name + MC version + loader + RAM. The pack is
    created empty and filled via the Mod Browser (Discover drawer)."""

    create_requested = pyqtSignal(str, str, str, int)  # name, mcVersion, loader, ramGB

    MC_VERSIONS = [
        "Auto (default 1.20.1)", "1.21.4", "1.21.3", "1.21.1", "1.21",
        "1.20.6", "1.20.4", "1.20.1", "1.19.4", "1.19.2", "1.18.2", "1.17.1", "1.16.5",
    ]
    LOADERS = ["Auto", "Forge", "NeoForge", "Fabric", "Quilt", "Vanilla"]

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("New Modpack")
        self.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        self.resize(520, 480)
        lay = vbox(self, 14, margins=(22, 18, 22, 18))
        lay.addWidget(label(self, "Build Your Own Pack", "h2"))
        intro = label(
            self,
            "Create an empty pack with your chosen version, loader and RAM, then fill it from the Mod Browser — mods, shaders and resource packs, each resolved with its real dependencies.",
            "muted",
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        form = card(self)
        fl = vbox(form, 12, margins=(16, 14, 16, 14))

        fl.addWidget(label(form, "Pack name", "h3"))
        self._name = QLineEdit(form)
        self._name.setPlaceholderText("e.g. My Medieval Adventure")
        fl.addWidget(self._name)

        row = QHBoxLayout()
        row.setSpacing(10)
        mc_col = vbox(form, 4)
        mc_col.addWidget(label(form, "Minecraft version", "h3"))
        self._mc = QComboBox(form)
        self._mc.addItems(self.MC_VERSIONS)
        mc_col.addWidget(self._mc)
        row.addLayout(mc_col, 1)
        ld_col = vbox(form, 4)
        ld_col.addWidget(label(form, "Mod loader", "h3"))
        self._loader = QComboBox(form)
        self._loader.addItems(self.LOADERS)
        ld_col.addWidget(self._loader)
        row.addLayout(ld_col, 1)
        fl.addLayout(row)

        ram_col = vbox(form, 4)
        ram_col.addWidget(label(form, "RAM allocation (GB)", "h3"))
        self._ram = QSpinBox(form)
        self._ram.setRange(2, 24)
        self._ram.setValue(8)
        self._ram.setSuffix(" GB")
        ram_col.addWidget(self._ram)
        fl.addLayout(ram_col)

        hint = label(form, "Pick the RAM your PC can actually spare — it becomes the pack's launch allocation and the performance estimate's basis.", "small")
        hint.setWordWrap(True)
        fl.addWidget(hint)
        lay.addWidget(form)

        note = card(self)
        nl = vbox(note, 6, margins=(14, 12, 14, 12))
        nl.addWidget(label(note, "What happens next", "h3"))
        for step in [
            "The empty pack is created instantly — no downloads yet.",
            "Open Discover and pick any mod/sharder/resource pack to add it (dependencies are resolved automatically).",
            "Press PLAY any time; the launcher installs Java + Mojang + loader on first launch.",
        ]:
            r = QHBoxLayout()
            dot = label(note, "•", "green")
            r.addWidget(dot)
            t = label(note, step, "sub")
            t.setWordWrap(True)
            r.addWidget(t, 1)
            nl.addLayout(r)
        lay.addWidget(note)

        act = QHBoxLayout()
        act.addStretch(1)
        cancel = button(self, "Cancel", "btn-dark")
        cancel.clicked.connect(self.reject)
        create = button(self, "CREATE PACK", "btn-primary", "plus", theme.BG)
        create.clicked.connect(self._submit)
        act.addWidget(cancel)
        act.addWidget(create)
        lay.addLayout(act)

    def _submit(self) -> None:
        name = self._name.text().strip()
        mc = self._mc.currentText()
        if mc.startswith("Auto"):
            mc = "auto"
        loader = self._loader.currentText().lower()
        if loader == "auto":
            loader = "auto"
        self.create_requested.emit(name, mc, loader, self._ram.value())
        self.accept()
