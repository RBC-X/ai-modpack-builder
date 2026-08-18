"""Pack Detail — the design's PackDetailView, driven by the real BuildRecord.

Tabs: Overview · Content · Worlds · Logs · Settings. Every number comes from
the backend (selections, visuals, worlds on disk, real log files, exports).
"""
from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout,
                             QLabel, QLineEdit, QPlainTextEdit, QScrollArea,
                             QSlider, QVBoxLayout, QWidget)

import theme
from common import (avatar, button, card, clear_layout, fmt_bytes, fmt_time, hbox,
                    icon_btn, icon_pixmap, label, pill, progress, vbox)
from common import icon_cache
from icons import icon
from views.packdetail_tabs import (ContentTabMixin, LogsTabMixin, OverviewTabMixin,
                                   SettingsTabMixin)

CAT_COLORS = {
    "library": theme.BLUE, "optimization": theme.GREEN, "technology": theme.GREEN,
    "magic": theme.BLUE, "worldgen": theme.GREEN, "mobs": theme.WARNING,
    "utility": theme.TEXT2, "hud": theme.BLUE, "adventure": theme.WARNING,
    "content": theme.TEXT2, "shaders": theme.BLUE, "decorative": theme.GREEN,
}


class PackDetailView(OverviewTabMixin, ContentTabMixin, LogsTabMixin,
                     SettingsTabMixin, QWidget):
    back_requested = pyqtSignal()
    play_requested = pyqtSignal(str)
    stop_requested = pyqtSignal(str)
    remove_mod = pyqtSignal(str, str, object)      # build_id, slug, type|None
    retest_requested = pyqtSignal(str)
    repair_requested = pyqtSignal(str)
    navigate_discover = pyqtSignal()
    ask_ai = pyqtSignal(str, str)                  # build_id, prompt
    rename_requested = pyqtSignal(str, str)
    export_requested = pyqtSignal(str, str)        # build_id, filename
    open_evidence = pyqtSignal(str, str)           # build_id, filename
    status_changed = pyqtSignal(str)               # build_id (re-pull record)
    set_ram = pyqtSignal(str, int)                 # build_id, ram_gb
    set_auto_relaunch = pyqtSignal(str, bool)      # build_id, enabled
    set_shader_preset = pyqtSignal(str, str)       # build_id, preset
    backup_requested = pyqtSignal(str)             # build_id


    def __init__(self, api):
        super().__init__()
        self.api = api
        self.build_id: str | None = None
        self.record: dict | None = None
        self.worlds: list[dict] = []
        self.status: dict | None = None
        self._tab = "overview"
        self._files: list[dict] = []
        self._log_name: str | None = None
        self._mod_search = ""
        self._console: QPlainTextEdit | None = None
        self._files_box: QComboBox | None = None
        self._console_built_for: str | None = None
        self._log_stop: threading.Event | None = None
        self._log_view_serial = 0
        self._load_serial = 0      # guards out-of-order load()/worlds results
        self._live_banner = None
        self._heap_badge: QLabel | None = None
        self._heap_timer = QTimer(self)
        self._heap_timer.setInterval(4000)
        self._heap_timer.timeout.connect(self._refresh_heap_badge)
        self._heap_timer.start()

        outer = QScrollArea(self)
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.Shape.NoFrame)
        outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setProperty("page", "true")
        outer.setWidget(body)
        self.root = vbox(body, 24, margins=(32, 32, 32, 28))
        self.root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Back nav
        top_section = QWidget(body)
        top_section_lay = vbox(top_section, 16, margins=0)
        backrow = QHBoxLayout()
        back = button(top_section, "Back to Library", "back-link", "arrowleft")
        back.setFixedHeight(24)
        back.clicked.connect(self.back_requested.emit)
        backrow.addWidget(back)
        backrow.addStretch(1)
        top_section_lay.addLayout(backrow)

        # Hero (static frame, inner rebuilt)
        self._hero = QFrame(top_section)
        self._hero.setProperty("cls", "hero")
        self._hero.setFixedHeight(280)
        theme.polish(self._hero)
        self._hero_inner = QWidget(self._hero)
        self._hero_lay = vbox(self._hero_inner, 12, margins=(32, 32, 32, 32))
        ho = QVBoxLayout(self._hero)
        ho.setContentsMargins(0, 0, 0, 0)
        ho.addWidget(self._hero_inner)
        top_section_lay.addWidget(self._hero)
        self.root.addWidget(top_section)

        # Tabs
        tabs_frame = QFrame(body)
        tabs_frame.setFixedHeight(42)
        tabs_frame.setProperty("cls", "tabs-bar")
        theme.polish(tabs_frame)
        tabs_row = hbox(tabs_frame, 8, margins=(0, 0, 0, 8))
        self._tab_btns: dict[str, object] = {}
        for tid, tlabel in [("overview", "Overview"), ("content", "Content"),
                            ("worlds", "Worlds"), ("logs", "Logs"), ("settings", "Settings")]:
            p = pill(tabs_frame, tlabel, active=tid == self._tab)
            p.setFixedHeight(34)
            p.setIcon(icon({
                "overview": "layers", "content": "folder", "worlds": "globe",
                "logs": "terminal", "settings": "settings",
            }[tid], theme.GREEN if tid == self._tab else theme.TEXT2))
            p.clicked.connect(lambda _=False, t=tid: self._set_tab(t))
            tabs_row.addWidget(p)
            self._tab_btns[tid] = p
        tabs_row.addStretch(1)
        self.root.addWidget(tabs_frame)

        # Tab body
        self._body = QFrame(body)
        self._body_lay = vbox(self._body, 14)
        self.root.addWidget(self._body)

        lay = vbox(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(outer)

    # ------------------------------------------------------------------
    def _set_tab(self, tab: str) -> None:
        if tab != "logs":
            self._stop_log_stream()
        self._tab = tab
        icon_names = {"overview": "layers", "content": "folder", "worlds": "globe",
                      "logs": "terminal", "settings": "settings"}
        for tid, b in self._tab_btns.items():
            b.setProperty("active", "true" if tid == tab else "false")
            b.setIcon(icon(icon_names[tid], theme.GREEN if tid == tab else theme.TEXT2))
            theme.polish(b)
        self._render_tab()

    def _stop_log_stream(self) -> None:
        self._log_view_serial += 1
        if self._log_stop is not None:
            self._log_stop.set()
            self._log_stop = None
        # The tab body is about to delete the console widget. Drop the Python
        # reference before any already-queued stream callback can touch the
        # deleted Qt object.
        self._console = None
        self._files_box = None
        self._console_built_for = None
        self._live_banner = None

    def _append_console(self, line: str) -> None:
        c = self._console
        if c is None or not line:
            return
        try:
            if c.blockCount() > 4000:
                text = c.toPlainText().split("\n")
                c.setPlainText("\n".join(text[-2000:]))
            c.appendPlainText(line)
        except RuntimeError:
            self._console = None

    def load(self, build_id: str, record: dict | None = None) -> None:
        # Serial token: load() is called on every pack open AND on every refresh
        # tick while a pack is open (_reload_detail). A slow in-flight fetch for
        # an older build must never land after a newer one and overwrite the
        # record/worlds under the wrong header — only the LATEST load applies.
        # (The record is keyed to build_id, so a stale build's result must never
        # render, even if the newer load failed — same semantics as Discover's
        # search serial.)
        serial = self._load_serial = self._load_serial + 1
        self._stop_log_stream()
        self._console_built_for = None
        if build_id != self.build_id:
            self.worlds = []
        self.build_id = build_id
        if record:
            self.record = record
            self._render()
            from common import run_async

            def ok_worlds(worlds):
                if serial != self._load_serial:
                    return  # superseded by a newer load()
                self.worlds = worlds
                self._refresh_tab_labels()
                if self._tab == "worlds":
                    self._render_tab()

            run_async(lambda: self.api.worlds(build_id), ok_worlds, None)
            return
        from common import run_async

        def fetch():
            return self.api.build(build_id), self.api.worlds(build_id)

        def ok(res):
            if serial != self._load_serial:
                return  # superseded by a newer load()
            rec, worlds = res
            self.record = rec
            self.worlds = worlds
            self._render()

        def err(e):
            if serial != self._load_serial:
                return  # superseded by a newer load()
            self.record = {"request": f"Failed to load pack record: {e}"}
            self._render()

        run_async(fetch, ok, err)

    def set_status(self, status: dict) -> None:
        self.status = status
        if self._tab == "overview":
            self._render_hero()
        elif self._tab == "logs" and self._console is not None:
            # SSE stream owns the console while active; only fall back to the
            # status tail (deduped) when the stream dropped.
            if self._log_stop is None or self._log_stop.is_set():
                lines = status.get("gameLogTail") or status.get("logTail") or []
                if lines:
                    known = set(self._console.toPlainText().split("\n")[-60:])
                    new = [l for l in lines if l and l not in known][-80:]
                    if new:
                        self._console.appendPlainText("\n".join(new))

    # ------------------------------------------------------------------
    def _render(self) -> None:
        self._refresh_tab_labels()
        self._render_hero()
        self._render_tab()

    def _refresh_tab_labels(self) -> None:
        record = self.record or {}
        content_count = len(record.get("selections") or [])
        labels = {
            "overview": "Overview",
            "content": f"Content ({content_count})",
            "worlds": f"Worlds ({len(self.worlds)})",
            "logs": "Logs",
            "settings": "Settings",
        }
        for tid, control in self._tab_btns.items():
            control.setText(labels[tid])

    def _render_hero(self) -> None:
        clear_layout(self._hero_lay)
        r = self.record or {}
        reqs = r.get("requirements") or {}
        stats = r.get("packStats") or {}
        lay = self._hero_lay

        row = QHBoxLayout()
        row.setSpacing(8)
        loader = (reqs.get("loader") or "").capitalize()
        target = f"Minecraft {reqs.get('minecraftVersion') or 'auto'} • {loader or 'Auto loader'}"
        row.addWidget(pill(self._hero_inner, target, True, "pill"))
        row.addStretch(1)
        ai = pill(self._hero_inner, "ASK AI", True, "pill")
        ai.setIcon(icon("sparkles", theme.GREEN))
        ai.clicked.connect(self._ask_ai)
        row.addWidget(ai)
        lay.addLayout(row)

        lay.addStretch(1)

        head = QHBoxLayout()
        head.setSpacing(16)
        ic = QLabel(self._hero_inner)
        ic.setFixedSize(64, 64)
        ic.setPixmap(avatar(r.get("name") or "?", theme.GREEN, 64, 12))
        for selected in r.get("selections") or []:
            image_url = self._project_icon_url(selected)
            if image_url:
                icon_cache.request(image_url, ic, 64)
                break
        head.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
        col = vbox(self._hero_inner, 2)
        pack_name = r.get("name") or "Untitled pack"
        title_cls = "pack-title-compact" if len(pack_name) > 28 else "pack-title"
        t = label(self._hero_inner, pack_name, title_cls)
        t.setWordWrap(True)
        t.setMaximumWidth(660)
        col.addWidget(t)
        perf = r.get("perfEstimate") or {}
        ram = reqs.get("ramGB") or perf.get("recommendedAllocationMB", 0) // 1024 or "—"
        meta_text = f"{stats.get('modCount', 0)} Mods  •  RAM: {ram} GB"
        if perf.get("load"):
            meta_text += f"  •  {perf.get('load')} for this PC"
        meta = label(self._hero_inner, meta_text, "mono")
        col.addWidget(meta)
        # Live 'heap fitted to RAM' badge: re-runs the launch-time fit against
        # the RAM free RIGHT NOW (not the pack's fixed fitted value) and
        # refreshes every 4 s while the view is open, so a user sees exactly
        # what the next PLAY will pick on a machine whose free RAM keeps
        # shifting. Clicking it jumps to the Settings RAM slider with the
        # current fit pre-applied.
        self._heap_badge = pill(self._hero_inner, "", False, "pill-link")
        self._heap_badge.setToolTip("Click to jump to the Settings RAM slider with this fit pre-applied")
        self._heap_badge.setMaximumWidth(560)
        self._heap_badge.clicked.connect(self._jump_to_ram_fit)
        col.addWidget(self._heap_badge, 0, Qt.AlignmentFlag.AlignLeft)
        self._refresh_heap_badge()
        head.addLayout(col, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        running = bool((self.status or {}).get("running")) or bool((self.status or {}).get("starting"))
        if running:
            stop = button(self._hero_inner, "■ STOP", "btn-danger")
            stop.setFixedSize(125, 44)
            stop.clicked.connect(lambda: self.stop_requested.emit(self.build_id))
            actions.addWidget(stop)
        else:
            play = button(self._hero_inner, "PLAY", "btn-primary", "play", theme.BG)
            play.setFixedSize(125, 44)
            play.clicked.connect(lambda: self.play_requested.emit(self.build_id))
            actions.addWidget(play)
        wrench = icon_btn(self._hero_inner, "wrench", "Repair & relaunch", theme.TEXT2)
        wrench.setFixedSize(42, 42)
        wrench.clicked.connect(lambda: self.repair_requested.emit(self.build_id))
        share = icon_btn(self._hero_inner, "share", "Export modpack", theme.TEXT2)
        share.setFixedSize(42, 42)
        share.clicked.connect(self._export_menu)
        rename = icon_btn(self._hero_inner, "key", "Rename pack", theme.TEXT2)
        rename.setFixedSize(42, 42)
        rename.clicked.connect(self._rename_dialog)
        actions.addWidget(wrench)
        actions.addWidget(share)
        actions.addWidget(rename)
        head.addLayout(actions)
        lay.addLayout(head)

    def _refresh_heap_badge(self) -> None:
        """Re-run the launch-time heap fit against live free RAM and show it.

        Mirrors launch_pack: requested = fit_xmx_mb(ramGB), then the adaptive
        fit_xmx_to_free_mb down-fits it to what is actually free right now.
        The badge makes the fit visible and self-updates every 4 s so a user
        sees the exact heap the next PLAY would pick.
        """
        if not self.build_id or not self.record or self._heap_badge is None:
            return
        try:
            from engine.hardware import fit_xmx_mb, fit_xmx_to_free_mb
            r = self.record or {}
            reqs = r.get("requirements") or {}
            perf = r.get("perfEstimate") or {}
            ram_gb = int(reqs.get("ramGB") or 0) or int(perf.get("recommendedAllocationMB", 0) // 1024 or 0) or 8
            requested = fit_xmx_mb(ram_gb)
            free = float((self.api.free_ram() or {}).get("freeGb") or 0)
            fitted = fit_xmx_to_free_mb(requested, free) if free else requested
            self._heap_fit_gb = max(2, min(16, round(fitted / 1024)))
            if fitted < requested:
                text = f"Heap fit to RAM: {requested} → {fitted} MB on next launch ({free:.1f} GB free)"
            else:
                text = f"Heap {requested} MB fits free RAM ({free:.1f} GB free)"
            self._heap_badge.setText(text)
            self._heap_badge.setStyleSheet("")
        except Exception:
            pass

    def _jump_to_ram_fit(self) -> None:
        """Open the Settings tab and pre-apply the current free-RAM heap fit to
        the RAM slider, so the user can review and APPLY RAM without
        recomputing the fit themselves."""
        if not self.record:
            return
        self._set_tab("settings")
        if getattr(self, "_ram_slider", None) is None:
            return
        gb = getattr(self, "_heap_fit_gb", None)
        if gb is None:
            return
        try:
            self._ram_slider.setValue(gb)
            if self._ram_label is not None:
                self._ram_label.setText(f"Allocated RAM: {gb} GB (heap fit pre-applied)")
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    def _render_tab(self) -> None:
        clear_layout(self._body_lay)
        if not self.record:
            self._body_lay.addWidget(label(self._body, "Loading pack record…", "muted"))
            return
        if self._tab == "overview":
            self._tab_overview()
        elif self._tab == "content":
            self._tab_content()
        elif self._tab == "worlds":
            self._tab_worlds()
        elif self._tab == "logs":
            self._tab_logs()
        elif self._tab == "settings":
            self._tab_settings()

    def toast_error(self, msg: str) -> None:
        # PackDetail has no toast; surface via status_changed path is complex,
        # so use a modal-free approach: re-emit status to refresh and print.
        print(f"[packdetail] {msg}", flush=True)
