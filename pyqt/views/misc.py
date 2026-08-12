"""Downloads · Activity · Settings views (real backend data)."""
from __future__ import annotations

import json
import os

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout,
                             QLabel, QLineEdit, QPlainTextEdit, QScrollArea,
                             QSizePolicy, QSlider, QVBoxLayout, QWidget)

import theme
import minecraft_auth
import updater
from common import (button, card, clear_layout, fmt_bytes, fmt_time, hbox,
                    icon_pixmap, label, pill, progress, run_async, vbox)
from icons import icon
from product_config import APP_VERSION

# ===========================================================================
# Downloads
# ===========================================================================
class DownloadsView(QWidget):
    def __init__(self, api):
        super().__init__()
        self.api = api
        outer = QScrollArea(self)
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.Shape.NoFrame)
        outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setProperty("page", "true")
        outer.setWidget(body)
        self.root = vbox(body, 24, margins=(32, 32, 32, 30))
        self.root.setAlignment(Qt.AlignmentFlag.AlignTop)
        download_head = QWidget(body)
        download_head.setFixedWidth(960)
        download_head_lay = vbox(download_head, 0, margins=0)
        download_head_lay.addWidget(label(download_head, "Download Manager", "h1"))
        download_head_lay.addWidget(label(
            download_head,
            "Monitor real file downloads, their source, completion status, and recorded size.",
            "small",
        ))
        self.root.addWidget(download_head, 0, Qt.AlignmentFlag.AlignHCenter)
        self._status = label(body, "Loading download history…", "muted")
        self._status.setFixedWidth(960)
        self.root.addWidget(self._status, 0, Qt.AlignmentFlag.AlignHCenter)
        self._list_wrap = QWidget(body)
        self._list_wrap.setFixedWidth(960)
        self._list = vbox(self._list_wrap, 8, margins=0)
        self.root.addWidget(self._list_wrap, 0, Qt.AlignmentFlag.AlignHCenter)

        lay = vbox(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(outer)

    def showEvent(self, event) -> None:  # noqa: N802
        if event is not None:
            super().showEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        def fetch():
            builds = self.api.builds()
            rows = []
            for b in builds[:12]:
                try:
                    rec = self.api.build(b["buildId"])
                except Exception:  # noqa: BLE001
                    continue
                for d in (rec.get("downloads") or [])[-12:]:
                    rows.append({
                        "name": d.get("filename") or d.get("key") or "file",
                        "provider": (d.get("key") or "").split(":")[0],
                        "sizeBytes": d.get("sizeBytes") or 0,
                        "sha1": d.get("sha1") or "",
                        "status": d.get("status") or "ok",
                        "build": b.get("name") or b.get("buildId"),
                        "error": d.get("error"),
                    })
            return rows

        def ok(rows):
            self._status.setText(f"{len(rows)} download records across your packs.")
            self._status.setVisible(False)
            self._render(rows)

        def err(e):
            self._status.setText(f"[{e}]")
            self._status.setVisible(True)

        run_async(fetch, ok, err)

    def _render(self, rows: list[dict]) -> None:
        clear_layout(self._list)
        active_states = {"queued", "pending", "downloading", "verifying"}
        active = [r for r in rows if str(r.get("status") or "").lower() in active_states]
        completed = [r for r in rows if r not in active]

        active_head = QHBoxLayout()
        active_icon = QLabel(self)
        active_icon.setPixmap(icon_pixmap("download", theme.GREEN, 16))
        active_head.addWidget(active_icon)
        active_head.addWidget(label(self, f"ACTIVE DOWNLOADS ({len(active)})", "h3"))
        active_head.addStretch(1)
        self._list.addLayout(active_head)
        if active:
            for r in active:
                self._list.addWidget(self._row(r))
        else:
            empty_active = card(self)
            empty_lay = vbox(empty_active, 0, margins=(18, 20, 18, 20))
            msg = label(empty_active, "No downloads are active right now.", "muted")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lay.addWidget(msg)
            self._list.addWidget(empty_active)

        completed_head = QHBoxLayout()
        completed_icon = QLabel(self)
        completed_icon.setPixmap(icon_pixmap("checkcircle", theme.GREEN, 16))
        completed_head.addWidget(completed_icon)
        completed_head.addWidget(label(self, f"COMPLETED DOWNLOADS ({len(completed)})", "h3"))
        completed_head.addStretch(1)
        self._list.addLayout(completed_head)
        if not completed:
            empty_done = card(self)
            empty_lay = vbox(empty_done, 0, margins=(18, 20, 18, 20))
            msg = label(empty_done, "No completed download history.", "muted")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lay.addWidget(msg)
            self._list.addWidget(empty_done)
            return
        for r in completed:
            self._list.addWidget(self._row(r))

    def _row(self, r: dict) -> QFrame:
        c = card(self)
        row = hbox(c, 12, margins=(14, 10, 14, 10))
        ok = r.get("status") == "ok"
        ic = QLabel(c)
        ic.setPixmap(icon_pixmap("checkcircle" if ok else "alert", theme.GREEN if ok else theme.DANGER, 18))
        row.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
        col = vbox(c, 1)
        t = label(c, r.get("name") or "?", "h3")
        t.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(label(c, f"{r.get('provider')} • {r.get('build')} • {fmt_bytes(r.get('sizeBytes'))}", "muted"))
        row.addLayout(col, 1)
        if not ok:
            row.addWidget(pill(c, r.get("status") or "failed", False, "pill-danger"))
        else:
            state = "SHA-1 verified" if r.get("sha1") else "completed"
            state_label = label(c, state, "green")
            if r.get("sha1"):
                state_label.setToolTip(f"Recorded SHA-1: {r.get('sha1')}")
            row.addWidget(state_label)
        return c


# ===========================================================================
# Activity
# ===========================================================================
class ActivityView(QWidget):
    open_evidence = pyqtSignal(str, str)   # build_id, filename

    def __init__(self, api):
        super().__init__()
        self.api = api
        self._tab = "feed"
        outer = QScrollArea(self)
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.Shape.NoFrame)
        outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setProperty("page", "true")
        outer.setWidget(body)
        self.root = vbox(body, 24, margins=(32, 32, 32, 30))
        self.root.setAlignment(Qt.AlignmentFlag.AlignTop)
        activity_head = QWidget(body)
        activity_head.setFixedWidth(960)
        activity_head_lay = vbox(activity_head, 0, margins=0)
        activity_head_lay.addWidget(label(activity_head, "Activity & Diagnostics", "h1"))
        activity_head_lay.addWidget(label(
            activity_head,
            "Track launcher execution history, Minecraft logs, crash reports, and AI repairs.",
            "small",
        ))
        self.root.addWidget(activity_head, 0, Qt.AlignmentFlag.AlignHCenter)

        tabs_frame = QFrame(body)
        tabs_frame.setFixedSize(960, 42)
        tabs_frame.setStyleSheet(f"border: none; border-bottom: 1px solid {theme.BORDER};")
        tabs = hbox(tabs_frame, 8, margins=(0, 0, 0, 8))
        self._tabs: dict[str, object] = {}
        tab_specs = [("feed", "Activity Feed", "activity"), ("logs", "Engine Logs", "terminal"),
                     ("crashes", "Crash Reports", "alert"), ("repairs", "AI Repairs", "wrench")]
        for tid, tl, icon_name in tab_specs:
            p = pill(tabs_frame, tl, active=tid == self._tab)
            p.setFixedHeight(34)
            p.setIcon(icon(icon_name, theme.GREEN if tid == self._tab else theme.TEXT2))
            p.clicked.connect(lambda _=False, t=tid: self._set_tab(t))
            tabs.addWidget(p)
            self._tabs[tid] = p
        tabs.addStretch(1)
        self.root.addWidget(tabs_frame, 0, Qt.AlignmentFlag.AlignHCenter)

        self._body = QFrame(body)
        self._body.setFixedWidth(960)
        self._body_lay = vbox(self._body, 10)
        self.root.addWidget(self._body, 0, Qt.AlignmentFlag.AlignHCenter)

        lay = vbox(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(outer)

    def _set_tab(self, t: str) -> None:
        self._tab = t
        icon_names = {"feed": "activity", "logs": "terminal", "crashes": "alert", "repairs": "wrench"}
        for tid, b in self._tabs.items():
            b.setProperty("active", "true" if tid == t else "false")
            b.setIcon(icon(icon_names[tid], theme.GREEN if tid == t else theme.TEXT2))
            theme.polish(b)
        self._refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        if event is not None:
            super().showEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        clear_layout(self._body_lay)
        if self._tab == "feed":
            self._feed()
        elif self._tab == "logs":
            self._engine_logs()
        elif self._tab == "crashes":
            self._crashes()
        else:
            self._repairs()

    def _empty_state(self, title: str, copy: str, icon_name: str = "activity") -> QFrame:
        empty = card(self._body)
        empty.setProperty("cls", "empty-state")
        theme.polish(empty)
        empty_lay = vbox(empty, 10, margins=(30, 34, 30, 34))
        empty_icon = QLabel(empty)
        empty_icon.setPixmap(icon_pixmap(icon_name, theme.MUTED, 30))
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lay.addWidget(empty_icon)
        title_label = label(empty, title, "h2")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lay.addWidget(title_label)
        copy_label = label(empty, copy, "sub")
        copy_label.setWordWrap(True)
        copy_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lay.addWidget(copy_label)
        return empty

    def _feed(self) -> None:
        self._body_lay.addWidget(label(self._body, "Loading engine events…", "muted"))

        def fetch():
            return list(self.api.events("", idle_timeout=1.5))[:120]

        def ok(evs):
            clear_layout(self._body_lay)
            if not evs:
                self._body_lay.addWidget(self._empty_state(
                    "No engine activity yet",
                    "Build, test, repair, or launch a pack and its real engine events will appear here.",
                    "activity",
                ))
                return
            history = card(self._body)
            history_lay = vbox(history, 10, margins=(22, 18, 22, 18))
            history_lay.addWidget(label(history, "EXECUTION HISTORY", "h3"))
            for ev in reversed(evs):
                row = QHBoxLayout()
                ts = label(history, fmt_time(ev.get("ts") or ""), "mono muted")
                ts.setProperty("cls", "mono muted")
                ts.setFixedWidth(150)
                row.addWidget(ts)
                lvl = ev.get("level") or "info"
                lc = theme.GREEN if lvl == "info" else (theme.WARNING if lvl == "warn" else theme.DANGER)
                row.addWidget(pill(history, lvl.upper(), False, "pill"), 0, Qt.AlignmentFlag.AlignTop)
                msg = label(history, ev.get("message") or "", "sub")
                msg.setWordWrap(True)
                row.addWidget(msg, 1)
                history_lay.addLayout(row)
            self._body_lay.addWidget(history)

        run_async(fetch, ok, lambda e: self._body_lay.addWidget(label(self._body, f"[{e}]", "muted")))

    def _engine_logs(self) -> None:
        def fetch():
            return list(self.api.events("", idle_timeout=1.5))[:400]

        def ok(evs):
            clear_layout(self._body_lay)
            if not evs:
                self._body_lay.addWidget(self._empty_state(
                    "No engine logs yet",
                    "Logs will appear after the builder or launcher performs an operation.",
                    "terminal",
                ))
                return
            console = QPlainTextEdit(self._body)
            console.setProperty("cls", "console")
            console.setReadOnly(True)
            console.setMinimumHeight(420)
            lines = []
            for ev in reversed(evs):
                lines.append(f"[{fmt_time(ev.get('ts') or '')}] [{ev.get('stage') or 'engine'}] [{ev.get('level') or 'info'}] {ev.get('message') or ''}")
            console.setPlainText("\n".join(lines[-300:]))
            self._body_lay.addWidget(console)

        run_async(fetch, ok, None)

    def _crashes(self) -> None:
        self._body_lay.addWidget(label(self._body, "Scanning pack launch states…", "muted"))

        def fetch():
            builds = self.api.builds()
            out = []
            for b in builds:
                if b.get("launchPhase") == "error" or b.get("failure"):
                    st = {}
                    try:
                        st = self.api.status(b["buildId"])
                    except Exception:  # noqa: BLE001
                        pass
                    out.append({"build": b, "status": st})
            return out

        def ok(items):
            clear_layout(self._body_lay)
            if not items:
                self._body_lay.addWidget(self._empty_state(
                    "No crash reports",
                    "Minecraft launch failures and their collected evidence will appear here.",
                    "checkcircle",
                ))
                return
            for it in items:
                b = it["build"]
                st = it["status"]
                c = card(self._body)
                cl = vbox(c, 8, margins=(18, 14, 18, 14))
                head = QHBoxLayout()
                ic = QLabel(c)
                ic.setPixmap(icon_pixmap("alert", theme.DANGER, 18))
                head.addWidget(ic)
                head.addWidget(label(c, f"Crash Detected — {b.get('name') or b.get('buildId')}", "h3"))
                head.addStretch(1)
                head.addWidget(label(c, fmt_time(b.get("createdAt")), "muted"))
                cl.addLayout(head)
                err = b.get("launchError") or (b.get("failure") or {}).get("message") or ""
                cl.addWidget(label(c, err[:240], "sub"))
                missing = st.get("missingDeps")
                if missing:
                    row = QHBoxLayout()
                    row.addWidget(label(c, "Missing mods:", "warn"))
                    for m in missing:
                        row.addWidget(pill(c, m, False, "pill-danger"))
                    row.addStretch(1)
                    cl.addLayout(row)
                files = st.get("crashFiles") or []
                if files:
                    row = QHBoxLayout()
                    row.addStretch(1)
                    for f in files[:3]:
                        b2 = button(c, f.rsplit("/", 1)[-1][:30], "btn-dark", "filetext")
                        b2.clicked.connect(lambda _=False, f=f: self.open_evidence.emit(b["buildId"], f.rsplit("/", 1)[-1]))
                        row.addWidget(b2)
                    cl.addLayout(row)
                self._body_lay.addWidget(c)

        run_async(fetch, ok, None)

    def _repairs(self) -> None:
        def fetch():
            builds = self.api.builds()
            repairs = []
            for b in builds[:15]:
                try:
                    rec = self.api.build(b["buildId"])
                except Exception:  # noqa: BLE001
                    continue
                for r in (rec.get("repairs") or [])[-5:]:
                    repairs.append({"build": b.get("name") or b.get("buildId"), "repair": r})
            return repairs

        def ok(repairs):
            clear_layout(self._body_lay)
            if not repairs:
                self._body_lay.addWidget(self._empty_state(
                    "No repairs recorded",
                    "Dependency fixes and compatibility repairs will appear here with their real result.",
                    "wrench",
                ))
                return
            for it in repairs:
                r = it["repair"]
                c = card(self._body)
                row = hbox(c, 12, margins=(16, 12, 16, 12))
                ic = QLabel(c)
                ic.setPixmap(icon_pixmap("wrench", theme.GREEN, 18))
                row.addWidget(ic)
                col = vbox(c, 2)
                col.addWidget(label(c, str(r.get("action") or r.get("summary") or "repair"), "h3"))
                detail = r.get("problem") or r.get("reason") or r.get("result") or ""
                col.addWidget(label(c, f"{detail[:160]} • {it['build']}", "muted"))
                row.addLayout(col, 1)
                ok = (r.get("result") or "").lower()
                row.addWidget(label(c, "resolved" if "pass" in ok else str(r.get("result") or ""), "green" if "pass" in ok else "warn"))
                self._body_lay.addWidget(c)

        run_async(fetch, ok, None)


# ===========================================================================
# Settings
# ===========================================================================
def _state_path() -> str:
    """UI state file: LOCALAPPDATA when frozen (bundle may be read-only),
    the checkout's pyqt/ dir in dev."""
    from engine.core import is_frozen, data_dir
    if is_frozen():
        return str(data_dir() / "state.json")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state.json")


STATE_PATH = _state_path()


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


class SettingsView(QWidget):
    settings_changed = pyqtSignal(dict)
    manage_account_requested = pyqtSignal()

    def __init__(self, api):
        super().__init__()
        self.api = api
        self._sub = "general"
        self._settings: dict = {}
        self._hardware: dict = {}
        self._save_status = None

        outer = QScrollArea(self)
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.Shape.NoFrame)
        outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setProperty("page", "true")
        outer.setWidget(body)
        self.root = vbox(body, 24, margins=(32, 32, 32, 30))
        self.root.setAlignment(Qt.AlignmentFlag.AlignTop)
        settings_head = QWidget(body)
        settings_head_lay = vbox(settings_head, 0, margins=0)
        settings_head_lay.addWidget(label(settings_head, "Launcher Settings", "h1"))
        settings_head_lay.addWidget(label(
            settings_head,
            "Engine behaviors, memory allocation, Java runtimes, and API providers.",
            "small",
        ))
        self.root.addWidget(settings_head)

        row = QHBoxLayout()
        row.setSpacing(24)
        nav = QVBoxLayout()
        nav.setSpacing(4)
        nav.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._nav_btns: dict[str, object] = {}
        nav_specs = [("general", "General", "settings"), ("minecraft", "Minecraft", "globe"),
                     ("java", "Java Runtime", "cpu"), ("providers", "API Providers", "key"),
                     ("ai", "AI Engine", "sparkles"), ("account", "Account", "user"),
                     ("cloud", "Cloud Sync", "cloud"), ("updates", "Updates", "refresh")]
        for tid, tl, icon_name in nav_specs:
            b = pill(body, tl, active=tid == self._sub, cls="settings-nav")
            b.setIcon(icon(icon_name, theme.GREEN if tid == self._sub else theme.MUTED))
            b.clicked.connect(lambda _=False, t=tid: self._set_sub(t))
            b.setFixedWidth(240)
            nav.addWidget(b)
            self._nav_btns[tid] = b
        row.addLayout(nav)

        # The settings panel fills the remaining column height (reference
        # launchers render settings as a full-height surface, not a card that
        # stops mid-window); the nav stays pinned at the top.
        self._panel = card(body)
        self._panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._panel_lay = vbox(self._panel, 14, margins=(24, 24, 24, 24))
        self._panel_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._panel, 1)
        self.root.addLayout(row, 1)

        lay = vbox(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(outer)

    def _set_sub(self, t: str) -> None:
        self._sub = t
        icon_names = {"general": "settings", "minecraft": "globe", "java": "cpu",
                      "providers": "key", "ai": "sparkles", "account": "user",
                      "cloud": "cloud", "updates": "refresh"}
        for tid, b in self._nav_btns.items():
            b.setProperty("active", "true" if tid == t else "false")
            b.setIcon(icon(icon_names[tid], theme.GREEN if tid == t else theme.MUTED))
            theme.polish(b)
        self._render_panel()

    def open_section(self, section: str = "providers") -> None:
        """Open a settings section from another page (for example Discover)."""
        if section in self._nav_btns:
            self._set_sub(section)

    def showEvent(self, event) -> None:  # noqa: N802
        if event is not None:
            super().showEvent(event)

        def fetch():
            return self.api.settings_get(), self.api.hardware()

        def ok(res):
            self._settings, self._hardware = res
            self._render_panel()

        run_async(fetch, ok, None)

    def _save(self, patch: dict, on_done=None) -> None:
        if self._save_status is not None:
            self._save_status.setText("Saving...")
            self._save_status.setProperty("cls", "mono muted")
            theme.polish(self._save_status)

        def fetch():
            return self.api.settings_post(patch)

        def ok(res):
            self._merge_settings(patch)
            if "curseforgeApiKey" in patch:
                configured = bool(res.get("keyConfigured"))
                self._settings["curseforgeKeyConfigured"] = configured
                if not configured:
                    self._settings["curseforgeKeySource"] = "none"
                elif self._settings.get("curseforgeKeySource") != "environment":
                    self._settings["curseforgeKeySource"] = "settings"
                self._settings["curseforgeApiKey"] = "********" if configured else ""
            if self._save_status is not None:
                self._save_status.setText("Saved")
                self._save_status.setProperty("cls", "mono green")
                theme.polish(self._save_status)
            self.settings_changed.emit(patch)
            if on_done:
                on_done(res)

        def err(error):
            if self._save_status is not None:
                self._save_status.setText(f"Could not save: {error}")
                self._save_status.setProperty("cls", "danger")
                theme.polish(self._save_status)

        run_async(fetch, ok, err)

    def _merge_settings(self, patch: dict) -> None:
        def merge(target: dict, update: dict) -> None:
            for key, value in update.items():
                if isinstance(value, dict) and isinstance(target.get(key), dict):
                    merge(target[key], value)
                else:
                    target[key] = value
        merge(self._settings, patch)

    # ------------------------------------------------------------------
    def _render_panel(self) -> None:
        clear_layout(self._panel_lay)
        s = self._settings or {}
        d = s.get("defaults") or {}
        p = s.get("performance") or {}
        hw = self._hardware.get("effective") or {}
        fn = getattr(self, f"_sub_{self._sub}")
        fn(s, d, p, hw)
        status_row = QHBoxLayout()
        status_row.addStretch(1)
        self._save_status = label(self._panel, "", "mono muted")
        status_row.addWidget(self._save_status)
        self._panel_lay.addLayout(status_row)

    # -- General --------------------------------------------------------
    def _sub_general(self, s, d, p, hw) -> None:
        self._panel_lay.addWidget(label(self._panel, "General Options", "h3"))
        st = _load_state()
        for key, title, desc in [
            ("minimizeOnLaunch", "Minimize Launcher on Game Start", "Automatically hide the launcher window when Minecraft loads."),
            ("closeOnLaunch", "Close Launcher after Game Starts", "Completely exit the launcher process to save RAM."),
        ]:
            row = QHBoxLayout()
            col = vbox(self._panel, 2)
            col.addWidget(label(self._panel, title, "sub"))
            col.addWidget(label(self._panel, desc, "muted"))
            row.addLayout(col, 1)
            cb = QCheckBox(self._panel)
            cb.setChecked(bool(st.get(key)))
            cb.stateChanged.connect(lambda st_, k=key: self._set_local(k, st_ == 2))
            row.addWidget(cb)
            self._panel_lay.addLayout(row)
        account_name = st.get("accountName") or "N/A"
        mode = card(self._panel)
        mode_lay = hbox(mode, 12, margins=(14, 12, 14, 12))
        mode_col = vbox(mode, 2)
        mode_col.addWidget(label(mode, "Account Mode", "sub"))
        mode_col.addWidget(label(mode, "The launcher currently uses a local/offline Minecraft profile; Microsoft OAuth is not connected.", "muted"))
        mode_lay.addLayout(mode_col, 1)
        mode_lay.addWidget(label(mode, f"Local: {account_name}", "mono green"))
        self._panel_lay.addWidget(mode)
        self._panel_lay.addWidget(label(self._panel,
            "Note: these are launcher-local preferences. Minecraft/Java/Provider options below persist to the engine's settings.", "muted"))

    def _set_local(self, key: str, val: bool) -> None:
        st = _load_state()
        st[key] = val
        _save_state(st)

    # -- Updates --------------------------------------------------------
    def _sub_updates(self, s, d, p, hw) -> None:
        self._panel_lay.addWidget(label(self._panel, "Updates", "h3"))
        self._panel_lay.addWidget(label(
            self._panel,
            f"Installed version: {APP_VERSION}  ·  the app self-updates through the same "
            f"installer (feed URL below → check → download (SHA-256 verified) → install).",
            "sub"))
        st = _load_state()
        cur = st.get("updateUrl") or updater.update_url()

        self._panel_lay.addWidget(label(self._panel, "Update feed URL", "sub"))
        row = QHBoxLayout()
        self._update_url_box = QLineEdit(self._panel)
        self._update_url_box.setPlaceholderText("https://example.com/update.json")
        self._update_url_box.setText(cur)
        save = button(self._panel, "Save", "btn-dark")
        save.clicked.connect(self._save_update_url)
        row.addWidget(self._update_url_box, 1)
        row.addWidget(save)
        self._panel_lay.addLayout(row)

        chk_row = QHBoxLayout()
        col = vbox(self._panel, 2)
        col.addWidget(label(self._panel, "Check for updates on startup", "sub"))
        col.addWidget(label(
            self._panel,
            "The installed app checks the feed once per day and notifies when a newer version exists.",
            "muted"))
        chk_row.addLayout(col, 1)
        cb = QCheckBox(self._panel)
        cb.setChecked(bool(st.get("autoCheckUpdates", True)))
        cb.stateChanged.connect(lambda st_, k="autoCheckUpdates": self._set_local(k, st_ == 2))
        chk_row.addWidget(cb)
        self._panel_lay.addLayout(chk_row)

        check = button(self._panel, "CHECK FOR UPDATES", "btn-primary", "refresh", theme.BG)
        check.clicked.connect(self._do_update_check)
        self._panel_lay.addWidget(check)
        self._update_status = label(self._panel, "", "sub")
        self._panel_lay.addWidget(self._update_status)

    def _save_update_url(self) -> None:
        st = _load_state()
        st["updateUrl"] = self._update_url_box.text().strip()
        _save_state(st)
        self._render_update_result(True, "Update feed URL saved.")

    def _do_update_check(self) -> None:
        st = _load_state()
        url = self._update_url_box.text().strip() or st.get("updateUrl") or updater.update_url()
        if not url:
            self._render_update_result(False, "No update feed configured — enter a URL above.")
            return
        self._update_status.setText("Checking for updates…")
        self._update_status.setProperty("cls", "")
        theme.polish(self._update_status)

        def work():
            return updater.run_update(url, apply=False)

        def ok(res):
            if not res.get("ok"):
                self._render_update_result(False, f"Check failed: {res.get('error')}")
                return
            if not res.get("available"):
                self._render_update_result(True, f"You are up to date (v{res.get('current')}).")
                return
            # Keep the full notes for the confirmation dialog (below); the
            # status line stays short.
            self._update_notes = (res.get("notes") or "").strip()
            self._update_latest = res.get("latest")
            self._update_url = url
            self._render_update_result(
                True, f"Update v{res.get('latest')} available — review the release notes before installing.")
            btn = button(self._panel, f"⬇ DOWNLOAD & INSTALL v{res.get('latest')}",
                         "btn-primary", "download", theme.BG)
            btn.clicked.connect(self._confirm_update)
            self._panel_lay.addWidget(btn)

        def err(e):
            self._render_update_result(False, f"Check failed: {e}")

        run_async(work, ok, err)

    def _render_update_result(self, ok_: bool, text: str) -> None:
        if not hasattr(self, "_update_status"):
            return
        try:
            self._update_status.setText(text)
            self._update_status.setProperty("cls", "mono green" if ok_ else "danger")
            theme.polish(self._update_status)
        except RuntimeError:
            pass  # panel was rebuilt mid-check (section switched)

    def _confirm_update(self) -> None:
        """Show the release notes and ask before downloading/installing."""
        url = getattr(self, "_update_url", "") or ""
        if not url:
            return
        notes = getattr(self, "_update_notes", "") or ""
        latest = getattr(self, "_update_latest", "?") or "?"
        d = QDialog(self)
        d.setWindowTitle(f"Update to v{latest}")
        d.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        d.resize(560, 420)
        lay = vbox(d, 12, margins=(22, 18, 22, 18))
        lay.addWidget(label(d, f"Update available — v{APP_VERSION} → v{latest}", "h3"))
        lay.addWidget(label(
            d,
            "Review the release notes below, then download and install. The installer "
            "is SHA-256 verified before it runs.",
            "muted",
        ))
        notes_box = QPlainTextEdit(d)
        notes_box.setReadOnly(True)
        notes_box.setPlainText(notes or "(the update feed did not include release notes)")
        notes_box.setMinimumHeight(180)
        lay.addWidget(notes_box, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button(d, "Cancel", "btn-dark")
        cancel.clicked.connect(d.reject)
        go = button(d, f"⬇ DOWNLOAD & INSTALL v{latest}", "btn-primary", "download", theme.BG)
        def apply():
            d.accept()
            self._apply_update(url)
        go.clicked.connect(apply)
        row.addWidget(cancel)
        row.addWidget(go)
        lay.addLayout(row)
        d.exec()

    def _apply_update(self, url: str) -> None:
        from PyQt6.QtWidgets import QApplication

        def work():
            return updater.run_update(url, apply=True)

        def ok(res):
            if res.get("applied"):
                self._render_update_result(
                    True, "Installer launched — the launcher will close while it runs.")
                QTimer.singleShot(1500, QApplication.instance().quit)
            else:
                self._render_update_result(False, f"Download failed: {res.get('error')}")

        run_async(work, ok, lambda e: self._render_update_result(False, f"Update failed: {e}"))

    # -- Minecraft ------------------------------------------------------
    def _sub_minecraft(self, s, d, p, hw) -> None:
        self._panel_lay.addWidget(label(self._panel, "Minecraft & Hardware", "h3"))
        det = self._hardware.get("detected") or {}
        self._panel_lay.addWidget(label(self._panel,
            f"Detected: {det.get('cpu') or '—'} • {det.get('gpu') or '—'} • {det.get('ramGB') or '—'} GB • {det.get('os') or '—'}", "sub"))
        rd = button(self._panel, "↻ Re-detect Hardware", "btn-dark", "refresh")
        rd.clicked.connect(self._redetect)
        self._panel_lay.addWidget(rd)

        for key, title in [("ramGB", "Default RAM (GB) — 0 = auto-detect"), ("targetFps", "Target FPS"),
                           ("resolution", "Screen Resolution")]:
            row = QHBoxLayout()
            col = vbox(self._panel, 2)
            col.addWidget(label(self._panel, title, "sub"))
            if key == "targetFps":
                box = QComboBox(self._panel)
                box.addItems(["30", "60", "120", "144", "240"])
                box.setCurrentText(str(p.get(key, 60)))
                box.currentTextChanged.connect(lambda v, k=key: self._save_perf(k, v))
                row.addLayout(col, 1)
                row.addWidget(box)
            elif key == "resolution":
                box = QComboBox(self._panel)
                box.addItems(["1920x1080", "2560x1440", "3840x2160", "1366x768"])
                box.setCurrentText(p.get(key) or "1920x1080")
                box.currentTextChanged.connect(lambda v, k=key: self._save_perf(k, v))
                row.addLayout(col, 1)
                row.addWidget(box)
            else:
                slider = QSlider(Qt.Orientation.Horizontal, self._panel)
                slider.setRange(0, 16)
                slider.setValue(int(p.get(key, 0)))
                row.addLayout(col, 1)
                row.addWidget(slider)
                value_label = label(self._panel, f"{p.get(key, 0)} GB", "mono")
                value_label.setFixedWidth(50)
                slider.valueChanged.connect(lambda v, output=value_label: output.setText(f"{v} GB"))
                slider.sliderReleased.connect(lambda control=slider, k=key: self._save_perf(k, control.value()))
                row.addWidget(value_label)
            self._panel_lay.addLayout(row)

    def _save_perf(self, key: str, val) -> None:
        try:
            val = int(val)
        except (TypeError, ValueError):
            pass
        self._save({"performance": {key: val}})

    def _redetect(self) -> None:
        def fetch():
            return self.api.hardware_refresh()

        def ok(_res):
            self.showEvent(None)

        run_async(fetch, ok, None)

    # -- Java -----------------------------------------------------------
    def _sub_java(self, s, d, p, hw) -> None:
        self._panel_lay.addWidget(label(self._panel, "Java Runtime", "h3"))
        build = s.get("build") or {}
        row = QHBoxLayout()
        col = vbox(self._panel, 2)
        col.addWidget(label(self._panel, "Automatic Java runtime management", "sub"))
        col.addWidget(label(self._panel, "The engine selects or downloads a compatible Java runtime for each Minecraft version.", "muted"))
        row.addLayout(col, 1)
        automatic = QCheckBox(self._panel)
        automatic.setChecked(bool(build.get("autoInstallJava")))
        automatic.stateChanged.connect(
            lambda state: self._save({"build": {"autoInstallJava": state == 2}})
        )
        row.addWidget(automatic)
        self._panel_lay.addLayout(row)
        self._panel_lay.addWidget(label(
            self._panel,
            "A forced custom Java path is not exposed by the current engine, so this page only shows the real engine setting.",
            "muted",
        ))

    # -- Providers ------------------------------------------------------
    def _sub_providers(self, s, d, p, hw) -> None:
        self._panel_lay.addWidget(label(self._panel, "API Providers", "h3"))
        m = card(self._panel)
        ml = hbox(m, 12, margins=(14, 12, 14, 12))
        ic = QLabel(m)
        ic.setPixmap(icon_pixmap("checkcircle", theme.MODRINTH, 18))
        ml.addWidget(ic)
        col = vbox(m, 2)
        col.addWidget(label(m, "Modrinth REST API v2", "h3"))
        col.addWidget(label(m, "Direct public access — no key required.", "muted"))
        ml.addLayout(col, 1)
        ml.addWidget(label(m, "Public API", "green"))
        self._panel_lay.addWidget(m)

        cf = card(self._panel)
        cfl = vbox(cf, 8, margins=(14, 12, 14, 12))
        row = QHBoxLayout()
        ic2 = QLabel(cf)
        ic2.setPixmap(icon_pixmap("key", theme.CURSEFORGE, 18))
        row.addWidget(ic2)
        row.addWidget(label(cf, "CurseForge API key", "h3"))
        row.addStretch(1)
        key_ok = bool(s.get("curseforgeKeyConfigured"))
        key_source = str(s.get("curseforgeKeySource") or "none")
        source_label = "Environment key" if key_source == "environment" else "Configured" if key_ok else "Not set"
        row.addWidget(label(cf, source_label, "green" if key_ok else "warn"))
        cfl.addLayout(row)
        keybox = QLineEdit(cf)
        keybox.setEchoMode(QLineEdit.EchoMode.Password)
        keybox.setClearButtonEnabled(True)
        keybox.setPlaceholderText("Enter a replacement key..." if key_ok else "Enter your CurseForge API key...")
        keybox.setEnabled(key_source != "environment")
        cfl.addWidget(keybox)
        action_row = QHBoxLayout()
        docs = button(cf, "Get an API key", "btn-dark", "external")
        docs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://docs.curseforge.com/rest-api/")))
        action_row.addWidget(docs)
        test = button(cf, "Test connection", "btn-dark", "wifi")
        action_row.addWidget(test)
        action_row.addStretch(1)
        clear = button(cf, "Remove stored key", "ghost", "x", theme.DANGER)
        clear.setVisible(key_source == "settings")
        action_row.addWidget(clear)
        save = button(cf, "Save key", "btn-primary", "check", theme.BG)
        save.setEnabled(False)
        keybox.textChanged.connect(lambda text: save.setEnabled(bool(text.strip()) and key_source != "environment"))
        def do_save():
            value = keybox.text().strip()
            if not value:
                return
            self._save({"curseforgeApiKey": value}, lambda _res: self._render_panel())
        save.clicked.connect(do_save)
        action_row.addWidget(save)
        cfl.addLayout(action_row)
        connection = label(cf, "Ready to test the public Modrinth catalog and your CurseForge credentials.", "muted")
        connection.setWordWrap(True)
        cfl.addWidget(connection)

        def test_connection():
            test.setEnabled(False)
            test.setText("Testing...")
            connection.setText("Contacting the configured providers...")

            def ok(result):
                sources = {item.get("provider"): item for item in result.get("sources") or []}
                mr = sources.get("modrinth") or {}
                curse = sources.get("curseforge") or {}
                mr_text = "Modrinth connected" if mr.get("ok") else f"Modrinth: {mr.get('error') or 'unavailable'}"
                cf_text = "CurseForge connected" if curse.get("ok") else f"CurseForge: {curse.get('error') or 'not configured'}"
                connection.setText(f"{mr_text}. {cf_text}.")
                connection.setProperty("cls", "green" if mr.get("ok") and curse.get("ok") else "warn")
                theme.polish(connection)
                test.setEnabled(True)
                test.setText("Test connection")

            def err(error):
                connection.setText(f"Connection test failed: {error}")
                connection.setProperty("cls", "danger")
                theme.polish(connection)
                test.setEnabled(True)
                test.setText("Test connection")

            run_async(lambda: self.api.provider_status(True), ok, err)

        test.clicked.connect(test_connection)
        clear.clicked.connect(lambda: self._save({"curseforgeApiKey": ""}, lambda _res: self._render_panel()))
        provider_note = label(
            cf,
            "CurseForge requires its official x-api-key credential. It is stored only in this computer's engine settings; the CF_API_KEY environment variable takes priority.",
            "muted",
        )
        provider_note.setWordWrap(True)
        cfl.addWidget(provider_note)
        self._panel_lay.addWidget(cf)

        # Build sources + budget
        self._panel_lay.addWidget(label(self._panel, "Build Sources & Budget", "h3"))
        b = s.get("build") or {}
        srcs = b.get("sources") or ["modrinth"]
        for prov, name in [("modrinth", "Modrinth"), ("curseforge", "CurseForge")]:
            row = QHBoxLayout()
            row.addWidget(label(self._panel, f"Use {name} in builds", "sub"), 1)
            cb = QCheckBox(self._panel)
            cb.setChecked(prov in srcs)
            cb.stateChanged.connect(lambda st_, prov=prov, control=cb: self._set_source(prov, st_ == 2, control))
            row.addWidget(cb)
            self._panel_lay.addLayout(row)
        budget = b.get("maxTotalDownloadMB") or 600
        row = QHBoxLayout()
        budget_label = label(self._panel, f"Max total download budget: {budget} MB", "sub")
        row.addWidget(budget_label, 1)
        sl = QSlider(Qt.Orientation.Horizontal, self._panel)
        sl.setRange(100, 4000)
        sl.setValue(int(budget))
        sl.valueChanged.connect(lambda value: budget_label.setText(f"Max total download budget: {value} MB"))
        sl.sliderReleased.connect(lambda: self._save({"build": {"maxTotalDownloadMB": sl.value()}}))
        row.addWidget(sl, 1)
        self._panel_lay.addLayout(row)

    def _set_source(self, provider: str, enabled: bool, control: QCheckBox) -> None:
        sources = list((self._settings.get("build") or {}).get("sources") or ["modrinth"])
        updated = [item for item in sources if item != provider]
        if enabled:
            updated.append(provider)
        if not updated:
            control.blockSignals(True)
            control.setChecked(True)
            control.blockSignals(False)
            if self._save_status is not None:
                self._save_status.setText("Keep at least one provider enabled")
                self._save_status.setProperty("cls", "warn")
                theme.polish(self._save_status)
            return
        ordered = [name for name in ("modrinth", "curseforge") if name in updated]
        self._settings.setdefault("build", {})["sources"] = ordered
        self._save({"build": {"sources": ordered}})

    # -- AI -------------------------------------------------------------
    def _sub_ai(self, s, d, p, hw) -> None:
        self._panel_lay.addWidget(label(self._panel, "AI Engine & Repair Rules", "h3"))
        b = s.get("build") or {}
        row = QHBoxLayout()
        row.addWidget(label(self._panel, "Repair mode (auto-fix depth)", "sub"), 1)
        box = QComboBox(self._panel)
        box.addItems(["instant", "standard", "deep"])
        box.setCurrentText(b.get("repairMode") or "standard")
        box.currentTextChanged.connect(lambda v: self._save({"build": {"repairMode": v}}))
        row.addWidget(box)
        self._panel_lay.addLayout(row)
        for key, title in [("autoInstallJava", "Auto-install Java runtimes"), ("downloadAssets", "Download Minecraft assets"),
                           ("serverPack", "Generate server packs")]:
            row = QHBoxLayout()
            row.addWidget(label(self._panel, title, "sub"), 1)
            cb = QCheckBox(self._panel)
            cb.setChecked(bool(b.get(key)))
            cb.stateChanged.connect(lambda st_, k=key: self._save({"build": {k: st_ == 2}}))
            row.addWidget(cb)
            self._panel_lay.addLayout(row)

    # -- Account / Cloud -------------------------------------------------
    def _sub_account(self, s, d, p, hw) -> None:
        self._panel_lay.addWidget(label(self._panel, "Minecraft Account", "h3"))
        st = _load_state()
        name = st.get("accountName") or "N/A"
        microsoft = st.get("accountMode") == "microsoft" and minecraft_auth.has_saved_credential()
        c = card(self._panel)
        cl = vbox(c, 8, margins=(14, 12, 14, 12))
        row = QHBoxLayout()
        row.addWidget(label(c, "Connected profile:" if microsoft else "Selected profile:", "sub"))
        row.addStretch(1)
        row.addWidget(label(c, name, "h3"))
        cl.addLayout(row)
        mode = "Microsoft account • Minecraft: Java Edition" if microsoft else "Offline / local profile"
        cl.addWidget(label(c, mode, "green" if microsoft else "muted"))
        manage = button(c, "MANAGE MINECRAFT ACCOUNT", "btn-primary", "usercheck", theme.BG)
        manage.clicked.connect(self.manage_account_requested.emit)
        cl.addWidget(manage)
        self._panel_lay.addWidget(c)
        note = label(
            self._panel,
            "Microsoft passwords are never entered in this app. Sign-in happens on Microsoft's website, and the refresh credential is encrypted for this Windows user.",
            "muted",
        )
        note.setWordWrap(True)
        self._panel_lay.addWidget(note)

    def _sub_cloud(self, s, d, p, hw) -> None:
        self._panel_lay.addWidget(label(self._panel, "Cloud Synchronization", "h3"))
        c = card(self._panel)
        cl = vbox(c, 8, margins=(14, 12, 14, 12))
        row = QHBoxLayout()
        row.addWidget(label(c, "Status:", "sub"))
        row.addStretch(1)
        row.addWidget(label(c, "Not Connected", "warn"))
        cl.addLayout(row)
        cl.addWidget(label(c, "Builds, exports, and the compatibility database live locally. A shared compatibility service is a designed future extension.", "muted"))
        self._panel_lay.addWidget(c)
