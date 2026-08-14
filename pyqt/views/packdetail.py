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

CAT_COLORS = {
    "library": theme.BLUE, "optimization": theme.GREEN, "technology": theme.GREEN,
    "magic": theme.BLUE, "worldgen": theme.GREEN, "mobs": theme.WARNING,
    "utility": theme.TEXT2, "hud": theme.BLUE, "adventure": theme.WARNING,
    "content": theme.TEXT2, "shaders": theme.BLUE, "decorative": theme.GREEN,
}


class PackDetailView(QWidget):
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
            rec, worlds = res
            self.record = rec
            self.worlds = worlds
            self._render()

        def err(e):
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

    # -- Overview ------------------------------------------------------
    def _tab_overview(self) -> None:
        r = self.record or {}
        self._body_lay.addWidget(self._health_card())
        grid = QHBoxLayout()
        grid.setSpacing(24)

        left = QVBoxLayout()
        left.setSpacing(24)

        about = card(self._body)
        al = vbox(about, 8, margins=(20, 16, 20, 16))
        al.addWidget(label(about, "About this Modpack", "h3"))
        import json
        fr = r.get("finalReport")
        if isinstance(fr, dict):
            fr = json.dumps(fr, indent=2)
        about_text = label(about, fr or r.get("request") or "", "sub")
        about_text.setWordWrap(True)
        al.addWidget(about_text)
        left.addWidget(about)
        left.addWidget(self._modifications_card())
        grid.addLayout(left, 68)

        grid.addWidget(self._specs_card(), 33)
        self._body_lay.addLayout(grid)

    # -- Pack Health (explainable score) -------------------------------
    def _health_card(self):
        """Persistent health dashboard: status + weighted, explainable score.

        Every metric is a deterministic function of the real record (test
        result, conflicts, perf estimate, content, identity, update check)
        plus the Last Known Good snapshot and this machine's hardware. Each
        metric has a Why popup with the exact reasons.
        """
        c = card(self._body)
        self._health_lay = vbox(c, 10, margins=(20, 16, 20, 16))
        self._health_metrics_lay = QVBoxLayout()
        self._health_flags_lay = QVBoxLayout()
        self._health_actions = QHBoxLayout()
        self._health_lay.addWidget(label(c, "Calculating pack health…", "muted"))
        self._health = None

        from common import run_async

        def fetch():
            return self.api.pack_health(self.build_id) if self.build_id else {}

        def ok(h):
            if self._tab != "overview":
                return
            self._health = h
            clear_layout(self._health_lay)
            self._fill_health(c, h)

        def err(e):
            print(f"[packdetail-health] {e}", flush=True)

        run_async(fetch, ok, err)
        return c

    def _fill_health(self, c, h: dict) -> None:
        lay = self._health_lay
        status = h.get("statusLabel") or "Unknown"
        color_cls = h.get("statusColor") or "muted"
        score = h.get("score", 0)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(label(c, "Pack Health", "h3"))
        head.addStretch(1)
        st = label(c, f"{status} · {score}/100", "mono")
        st.setProperty("cls", f"mono {color_cls}")
        theme.polish(st)
        head.addWidget(st)
        lay.addLayout(head)

        for key in ("stability", "compatibility", "performance", "content", "theme", "maintenance"):
            m = (h.get("metrics") or {}).get(key)
            if not m:
                continue
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(label(c, m.get("label", key), "sub"), 1)
            bar = progress(c, int(m.get("score") or 0), thin=True)
            s = int(m.get("score") or 0)
            if s < 40:
                bar.setProperty("error", "true")
            elif s < 60:
                bar.setProperty("warn", "true")
            theme.polish(bar)
            bar.setFixedWidth(150)
            row.addWidget(bar)
            row.addWidget(label(c, str(s), "mono"))
            why = icon_btn(c, "info", f"Why {m.get('label')} {s}?", theme.MUTED)
            why.setFixedSize(26, 26)
            why.clicked.connect(lambda _=False, m=m: self._why_metric(m))
            row.addWidget(why)
            lay.addLayout(row)

        flags = h.get("flags") or []
        if flags:
            lay.addSpacing(4)
            for fl in flags:
                frow = QHBoxLayout()
                frow.setSpacing(8)
                sev = fl.get("severity") or "info"
                ic = QLabel(c)
                ic.setPixmap(icon_pixmap(
                    "alert" if sev in ("error", "warning") else "info",
                    theme.DANGER if sev == "error" else theme.WARNING if sev == "warning" else theme.BLUE, 14))
                frow.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
                txt = label(c, fl.get("text") or "", "small")
                txt.setWordWrap(True)
                frow.addWidget(txt, 1)
                lay.addLayout(frow)

        # Actions: real update check + restore LKG on a broken/problem pack.
        lay.addSpacing(6)
        act = QHBoxLayout()
        act.setSpacing(10)
        upd = button(c, "CHECK MOD UPDATES", "btn-dark", "refresh")
        upd.clicked.connect(self._check_updates)
        act.addWidget(upd)
        sig = h.get("signals") or {}
        if sig.get("hasLkg") and h.get("status") in ("broken", "problems"):
            rb = button(c, "↺ RESTORE LAST KNOWN GOOD", "btn-danger", "refresh")
            rb.clicked.connect(self._restore_lkg)
            act.addWidget(rb)
        act.addStretch(1)
        up_note = (f"{sig.get('updatesAvailable', 0)} update(s) known"
                   if sig.get("updatesCheckedAt") else "Update check not run yet")
        act.addWidget(label(c, up_note, "muted"))
        lay.addLayout(act)
        lay.addWidget(label(c, "Score is computed from real test results, the Last Known Good snapshot, "
                              "conflict scans, the performance estimate, pack content and mod-update data — "
                              "click the info icon on any metric for the exact reasons.", "muted"))

    def _why_metric(self, m: dict) -> None:
        from PyQt6.QtWidgets import QMessageBox
        reasons = m.get("reasons") or []
        body = "\n".join(f"• {r}" for r in reasons) or "No recorded reasons."
        QMessageBox.information(
            self, f"Why {m.get('label')} {m.get('score')}?",
            f"{m.get('label')} scores {m.get('score')}/100 (weight {int((m.get('weight') or 0) * 100)}% of the overall score).\n\n{body}",
        )

    def _check_updates(self) -> None:
        from common import run_async
        if not self.build_id:
            return

        def fetch():
            return self.api.check_pack_updates(self.build_id)

        def ok(res):
            if self.build_id:
                self.status_changed.emit(self.build_id)

        def err(e):
            print(f"[packdetail-updates] {e}", flush=True)

        run_async(fetch, ok, err)

    def _modifications_card(self):
        r = self.record or {}
        c = card(self._body)
        cl = vbox(c, 8, margins=(20, 16, 20, 16))
        cl.addWidget(label(c, "Recent Modifications", "h3"))
        changed = False
        for rep in (r.get("repairs") or [])[-4:]:
            changed = True
            row = QHBoxLayout()
            ic = QLabel(c)
            ic.setPixmap(icon_pixmap("clock", theme.GREEN, 14))
            row.addWidget(ic)
            row.addWidget(label(c, str(rep.get("action") or rep.get("summary") or "repair"), "sub"))
            row.addStretch(1)
            cl.addLayout(row)
        for ch in (r.get("configChanges") or [])[-3:]:
            changed = True
            row = QHBoxLayout()
            ic = QLabel(c)
            ic.setPixmap(icon_pixmap("wrench", theme.GREEN, 14))
            row.addWidget(ic)
            row.addWidget(label(c, f"Config: {ch.get('targetFile', '')}", "sub"))
            row.addStretch(1)
            cl.addLayout(row)
        if not changed:
            cl.addWidget(label(c, "No automated repairs or config changes recorded.", "muted"))
        return c

    def _specs_card(self):
        r = self.record or {}
        reqs = r.get("requirements") or {}
        stats = r.get("packStats") or {}
        perf = r.get("perfEstimate") or {}
        c = card(self._body)
        cl = vbox(c, 8, margins=(20, 16, 20, 16))
        cl.addWidget(label(c, "Pack Specifications", "h3"))
        tests = r.get("tests") or [{}]
        first_test = tests[0] if tests else {}
        sc = r.get("shaderChoice") or {}
        rpc = r.get("resourcePackChoice") or {}
        shader_val = (f"{sc['title']} ({sc.get('preset', '')} preset)" if sc.get("title")
                      else ("—" if not sc else f"none — {str(sc.get('reason', ''))[:44]}"))
        rp_val = (rpc.get("title") if rpc.get("title")
                  else ("—" if not rpc else f"none — {str(rpc.get('reason', ''))[:44]}"))
        rows = [
            ("Minecraft", str(reqs.get("minecraftVersion") or "auto")),
            ("Mod Loader", (reqs.get("loader") or "auto").capitalize()),
            ("Active Mods", f"{stats.get('modCount', 0)} Mods"),
            ("Shader", shader_val),
            ("Resource Pack", rp_val),
            ("Allocated RAM", f"{reqs.get('ramGB') or perf.get('recommendedAllocationMB', 0) // 1024} GB"),
            ("Est. RAM", fmt_bytes(perf.get("estimatedRamMB", 0) * 1024 * 1024)),
            ("Load", str(perf.get("load") or "—")),
            ("Confidence", f"{perf.get('confidence', 0)}%"),
            ("Test", f"{first_test.get('status', '—')} ({first_test.get('level', '—')})"),
        ]
        for k, v in rows:
            row = QHBoxLayout()
            row.addWidget(label(c, k, "sub"))
            row.addStretch(1)
            val = label(c, v, "mono")
            val.setProperty("cls", "mono green" if "PASS" in v else "mono")
            theme.polish(val)
            row.addWidget(val)
            cl.addLayout(row)
        return c

    # -- Content -------------------------------------------------------
    def _tab_content(self) -> None:
        r = self.record or {}
        self._content_rows: list[tuple[QWidget, str]] = []
        toolbar = card(self._body)
        tl = hbox(toolbar, 12, margins=(14, 12, 14, 12))
        self._mod_search_box = QLineEdit(toolbar)
        self._mod_search_box.setPlaceholderText("Search installed mods...")
        self._mod_search_box.setFixedWidth(280)
        self._mod_search_box.setText(self._mod_search)
        self._mod_search_box.textChanged.connect(self._filter_mod_rows)
        tl.addWidget(self._mod_search_box)
        tl.addStretch(1)
        retest = button(toolbar, "RE-TEST", "btn-dark", "refresh")
        retest.clicked.connect(lambda: self.retest_requested.emit(self.build_id))
        tl.addWidget(retest)
        more = button(toolbar, "INSTALL MORE CONTENT", "btn-primary", "plus", theme.BG)
        more.clicked.connect(self.navigate_discover.emit)
        tl.addWidget(more)
        self._body_lay.addWidget(toolbar)

        # header row
        head = QFrame(self._body)
        head.setProperty("cls", "panel")
        theme.polish(head)
        hl = hbox(head, 8, margins=(16, 8, 16, 8))
        hl.addWidget(label(head, "Mod Name", "muted"), 5)
        hl.addWidget(label(head, "Version & Author", "muted"), 3)
        hl.addWidget(label(head, "Provider", "muted"), 2)
        hl.addWidget(label(head, "", "muted"), 1)
        self._body_lay.addWidget(head)

        mods = []
        for s in r.get("selections") or []:
            mods.append(s)

        for s in mods:
            row_widget = self._mod_row(s)
            search_text = f"{s.get('title') or ''} {s.get('slug') or ''}".lower()
            self._content_rows.append((row_widget, search_text))
            self._body_lay.addWidget(row_widget)

        # Visuals
        visuals = r.get("visualSelections") or {}
        shaders = visuals.get("shaders") or []
        rps = visuals.get("resourcePacks") or []
        if shaders:
            h = label(self._body, f"Shader Packs ({len(shaders)})", "h3")
            self._body_lay.addWidget(h)
            for v in shaders:
                self._body_lay.addWidget(self._visual_row(v, "shader"))
        if rps:
            h = label(self._body, f"Resource Packs ({len(rps)})", "h3")
            self._body_lay.addWidget(h)
            for v in rps:
                self._body_lay.addWidget(self._visual_row(v, "resourcepack"))
        if not mods and not shaders and not rps:
            self._body_lay.addWidget(label(self._body, "No content installed in this pack.", "muted"))
        self._filter_mod_rows(self._mod_search)

    def _filter_mod_rows(self, text: str) -> None:
        self._mod_search = text
        query = text.strip().lower()
        for row_widget, searchable in getattr(self, "_content_rows", []):
            row_widget.setVisible(not query or query in searchable)

    def _mod_row(self, s: dict) -> QFrame:
        c = QFrame(self._body)
        c.setProperty("cls", "row")
        theme.polish(c)
        row = hbox(c, 8, margins=(16, 10, 16, 10))
        ic = QLabel(c)
        ic.setFixedSize(40, 40)
        self._load_mod_icon(s, ic)
        row.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)

        namecol = QVBoxLayout()
        namecol.setSpacing(1)
        nr = QHBoxLayout()
        nr.setSpacing(6)
        nr.addWidget(label(c, s.get("title") or s.get("slug") or "?", "h3"))
        feats = (s.get("featureIds") or [])
        cat = feats[0] if feats else None
        if cat:
            nr.addWidget(pill(c, cat[:14], False, "pill"))
        for dep in (s.get("dependencies") or []):
            if dep.get("kind") == "required":
                nr.addWidget(pill(c, f"Req by {dep.get('key', '')}", False, "pill-danger"))
        namecol.addLayout(nr)
        why = (s.get("reason") or "No selection explanation was recorded")[:220]
        why_label = label(c, f"Why selected: {why}", "muted")
        why_label.setToolTip(s.get("reason") or why)
        namecol.addWidget(why_label)
        row.addLayout(namecol, 5)

        vcol = vbox(c, 1)
        vcol.addWidget(label(c, s.get("versionNumber") or "", "mono"))
        vcol.addWidget(label(c, f"MC {', '.join((s.get('minecraftVersions') or [])[:2])}", "muted"))
        row.addLayout(vcol, 3)

        prov = s.get("provider") or ""
        provider_badge = pill(c, "CurseForge" if prov == "curseforge" else "Modrinth", False, "provider-pill")
        provider_badge.setProperty("provider", prov)
        theme.polish(provider_badge)
        row.addWidget(provider_badge, 2)
        rm = icon_btn(c, "trash", "Uninstall mod", theme.MUTED)
        rm.clicked.connect(lambda: self.remove_mod.emit(self.build_id, s.get("slug"), None))
        row.addWidget(rm, 0, Qt.AlignmentFlag.AlignTop)
        return c

    def _load_mod_icon(self, s: dict, ic: QLabel) -> None:
        ic.setPixmap(avatar((s.get("title") or "?"), theme.GREEN, 40, 8))
        image_url = self._project_icon_url(s)
        if image_url:
            icon_cache.request(image_url, ic, 40)

    def _project_icon_url(self, selection: dict) -> str | None:
        provider = selection.get("provider")
        project_id = selection.get("projectId")
        key = selection.get("key") or (f"{provider}:{project_id}" if provider and project_id else "")
        nodes = ((self.record or {}).get("graph") or {}).get("nodes") or {}
        project = (nodes.get(key) or {}).get("project") or {}
        if project.get("iconUrl"):
            return str(project["iconUrl"])
        if provider == "modrinth" and project_id:
            return f"https://cdn.modrinth.com/data/{project_id}/icon.png"
        return None

    def _visual_row(self, v: dict, vtype: str) -> QFrame:
        c = QFrame(self._body)
        c.setProperty("cls", "row")
        theme.polish(c)
        row = hbox(c, 10, margins=(16, 10, 16, 10))
        ic = QLabel(c)
        ic.setFixedSize(28, 28)
        ic.setPixmap(icon_pixmap("sun" if vtype == "shader" else "layers", theme.BLUE, 24))
        row.addWidget(ic)
        col = vbox(c, 1)
        col.addWidget(label(c, v.get("title") or v.get("slug") or "?", "h3"))
        col.addWidget(label(c, f"{v.get('versionNumber') or ''} • {vtype}", "muted"))
        row.addLayout(col, 1)
        rm = icon_btn(c, "trash", "Remove", theme.MUTED)
        rm.clicked.connect(lambda: self.remove_mod.emit(self.build_id, v.get("slug"), vtype))
        row.addWidget(rm)
        return c

    # -- Worlds --------------------------------------------------------
    def _tab_worlds(self) -> None:
        if not self.worlds:
            self._body_lay.addWidget(label(self._body, "No worlds created in this instance yet.", "muted"))
            return
        for w in self.worlds:
            c = card(self._body)
            row = hbox(c, 14, margins=(16, 12, 16, 12))
            ic = QLabel(c)
            ic.setPixmap(icon_pixmap("globe", theme.GREEN, 22))
            row.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
            col = vbox(c, 2)
            col.addWidget(label(c, w.get("name") or "?", "h3"))
            col.addWidget(label(c, f"{w.get('sizeMB', 0)} MB • modified {fmt_time(w.get('lastModified'))}", "mono"))
            row.addLayout(col, 1)
            play = button(c, "Play World", "btn-primary", "play", theme.BG)
            play.clicked.connect(lambda: self.play_requested.emit(self.build_id))
            row.addWidget(play, 0, Qt.AlignmentFlag.AlignVCenter)
            self._body_lay.addWidget(c)

    # -- Logs ----------------------------------------------------------
    def _tab_logs(self) -> None:
        # Build the console once per build; the SSE stream owns it afterwards.
        if self._console is not None and self._console_built_for == self.build_id:
            return
        self._log_view_serial += 1
        view_serial = self._log_view_serial
        self._console_built_for = self.build_id

        console = card(self._body)
        cl = vbox(console, 10, margins=(14, 12, 14, 12))
        head = QHBoxLayout()
        head.addWidget(label(console, "Instance logs — live game output and recorded engine logs", "h3"))
        head.addStretch(1)
        self._files_box = QComboBox(console)
        self._files_box.currentIndexChanged.connect(self._load_log)
        head.addWidget(self._files_box, 1)
        copy = button(console, "Copy", "btn-dark", "copy")
        copy.clicked.connect(self._copy_log)
        head.addWidget(copy)
        cl.addLayout(head)

        self._live_banner = label(console, "", "danger")
        self._live_banner.setWordWrap(True)
        self._live_banner.hide()
        cl.addWidget(self._live_banner)

        self._console = QPlainTextEdit(console)
        self._console.setProperty("cls", "console")
        self._console.setReadOnly(True)
        self._console.setMinimumHeight(300)
        cl.addWidget(self._console)
        self._body_lay.addWidget(console)

        st = self.status or {}
        lines = st.get("gameLogTail") or st.get("logTail") or []
        if lines:
            self._console.setPlainText("\n".join(lines[-120:]))
        else:
            self._console.setPlainText("[engine] No live log yet — launch the pack to stream logs. Log files below are also viewable.\n")

        # Live SSE stream: new lines of latest.log / launch-play.log arrive as
        # they are written (no polling). Falls back to the status tail if the
        # stream drops.
        if self.build_id:
            from common import start_stream
            self._log_stop = threading.Event()
            stream_stop = self._log_stop
            gen = self.api.game_log_stream(self.build_id)

            def read_once():
                return [next(gen)]

            def on_events(evs):
                if stream_stop.is_set() or self._log_stop is not stream_stop:
                    return
                for ev in evs:
                    kind = ev.get("type") or "line"
                    line = ev.get("line", "")
                    if kind == "crash":
                        self._append_console(f"[CRASH] {line}")
                        try:
                            if self._live_banner is not None:
                                self._live_banner.setText(f"\u26a0  {line}")
                                self._live_banner.show()
                        except RuntimeError:
                            self._live_banner = None
                    elif kind == "menu":
                        self._append_console(f"[MENU] {line}")
                    else:
                        self._append_console(line)

            start_stream(read_once, on_events, self._log_stop)

        from common import run_async

        def fetch():
            files = self.api.files(self.build_id) if self.build_id else []
            # Export archives are real files, but they are not readable logs;
            # including them here caused a truthful ZIP path to open as a
            # nonexistent log endpoint and display an HTTP 404.
            return [f for f in files if f.get("path", "").startswith("logs/")
                    or "crash-reports" in f.get("path", "")
                    or "hs_err" in f.get("path", "")]

        def ok(files):
            if self._tab != "logs" or view_serial != self._log_view_serial or self._files_box is None:
                return
            self._files = files
            try:
                self._files_box.clear()
                for f in files[:40]:
                    self._files_box.addItem(f.get("path", ""))
                if files and self._log_name in [f.get("path") for f in files]:
                    self._files_box.setCurrentText(self._log_name)
            except RuntimeError:
                self._files_box = None

        run_async(fetch, ok, None)

    def _load_log(self, idx: int) -> None:
        if idx < 0 or not self._files or self._tab != "logs":
            return
        f = self._files[idx]
        self._log_name = f.get("path", "")
        log_name = self._log_name
        build_id = self.build_id
        view_serial = self._log_view_serial
        from common import run_async

        def fetch():
            name = log_name
            if "crash-reports" in name or name.endswith(".txt"):
                return self.api.evidence(build_id, name.rsplit("/", 1)[-1])
            return self.api.log(build_id, name.rsplit("/", 1)[-1])

        def ok(text):
            if self._tab != "logs" or view_serial != self._log_view_serial or self._console is None:
                return
            try:
                self._console.setPlainText(text[-4000:])
            except RuntimeError:
                self._console = None

        def err(error):
            if self._tab != "logs" or view_serial != self._log_view_serial or self._console is None:
                return
            try:
                self._console.setPlainText(f"[error] {error}")
            except RuntimeError:
                self._console = None

        run_async(fetch, ok, err)

    def _copy_log(self) -> None:
        from PyQt6.QtWidgets import QApplication
        if self._console is not None:
            QApplication.clipboard().setText(self._console.toPlainText())

    # -- Settings ------------------------------------------------------
    def _tab_settings(self) -> None:
        r = self.record or {}
        c = card(self._body)
        cl = vbox(c, 12, margins=(20, 18, 20, 18))
        cl.addWidget(label(c, "Instance Memory & Runtime", "h3"))
        reqs = r.get("requirements") or {}
        perf = r.get("perfEstimate") or {}
        cur_ram = int(reqs.get("ramGB") or perf.get("recommendedAllocationMB", 0) // 1024 or 8)
        self._ram_label = label(c, f"Allocated RAM: {cur_ram} GB", "sub")
        cl.addWidget(self._ram_label)
        self._ram_slider = QSlider(Qt.Orientation.Horizontal, c)
        self._ram_slider.setRange(2, 16)
        self._ram_slider.setValue(cur_ram)
        self._ram_slider.valueChanged.connect(lambda v: self._ram_label.setText(f"Allocated RAM: {v} GB"))
        cl.addWidget(self._ram_slider)
        self._ram_save = button(c, "APPLY RAM (NEXT LAUNCH)", "btn-primary", "check", theme.BG)
        self._ram_save.clicked.connect(self._save_ram)
        cl.addWidget(self._ram_save)
        cl.addWidget(label(c, f"Estimated: {fmt_bytes(perf.get('estimatedRamMB', 0) * 1024 * 1024)} · "
                              f"confidence {perf.get('confidence', 0)}% · recommended {perf.get('recommendedAllocationMB', 0) // 1024} GB", "muted"))
        cl.addWidget(label(c, "Changing RAM updates the pack record and applies on the next launch (stop the pack first if it is running).", "muted"))

        sep0 = QFrame(c)
        sep0.setFixedHeight(1)
        sep0.setProperty("cls", "sep")
        theme.polish(sep0)
        cl.addWidget(sep0)
        cl.addWidget(label(c, "Runtime Resilience", "h3"))
        ar = bool((r.get("settings") or {}).get("autoRelaunch", False))
        self._relaunch_chk = QCheckBox(c)
        self._relaunch_chk.setText("Auto-relaunch on silent close")
        self._relaunch_chk.setToolTip(
            'If the game closes on its own WITHOUT a crash (no crash report, no "Stopping!" '
            'window-close) within 2 minutes of the main menu, relaunch it once with 20% less RAM.')
        self._relaunch_chk.setChecked(ar)
        self._relaunch_chk.setStyleSheet(
            f"QCheckBox {{ color: {theme.TEXT}; font-size: 13px; }}"
            f"QCheckBox::indicator {{ width: 16px; height: 16px; }}"
            f"QCheckBox::indicator:checked {{ background: {theme.GREEN}; border-radius: 4px; }}")
        self._relaunch_chk.toggled.connect(self._save_auto_relaunch)
        cl.addWidget(self._relaunch_chk)
        self._relaunch_hint = label(
            c, "ON: a silently-dying game relaunches itself once at a lower RAM allocation.", "muted")
        cl.addWidget(self._relaunch_hint)
        cl.addWidget(label(c, "Recoveries are logged in the launch overlay and launch-state.json.", "muted"))

        # ---- Pack Identity & Recovery (snapshots / Last Known Good)
        sep3 = QFrame(c)
        sep3.setFixedHeight(1)
        sep3.setProperty("cls", "sep")
        theme.polish(sep3)
        cl.addWidget(sep3)
        cl.addWidget(label(c, "Pack Identity & Recovery", "h3"))
        ident = r.get("identity") or {}
        if ident.get("coreTheme"):
            cl.addWidget(label(c, f"Theme: {ident.get('coreTheme')}", "sub"))
        goals = ident.get("primaryGoals") or []
        if goals:
            cl.addWidget(label(c, "Primary goals: " + ", ".join(goals), "muted"))
        locked = ident.get("lockedMods") or []
        if locked:
            cl.addWidget(label(c, "Locked mods: " + ", ".join(locked), "muted"))
        snapshots = self.api.snapshots(self.build_id) if self.build_id else []
        lkg = None
        if self.build_id:
            try:
                lkg = self.api.last_known_good(self.build_id)
            except Exception:  # noqa: BLE001
                lkg = None
        if lkg:
            cl.addWidget(label(c, f"🟢 Last Known Good: {lkg.get('createdAt')} · {lkg.get('modCount')} mods", "mono green"))
        elif snapshots:
            cl.addWidget(label(c, "No validated Last Known Good yet — snapshots below still protect the pack.", "muted"))
        else:
            cl.addWidget(label(c, "Every successful test auto-creates a Last Known Good snapshot you can restore.", "muted"))
        if self.build_id and lkg:
            rb = button(c, "↺ RESTORE LAST KNOWN GOOD", "btn-dark", "refresh")
            rb.clicked.connect(self._restore_lkg)
            cl.addWidget(rb)
        if snapshots:
            srow = QHBoxLayout()
            srow.setSpacing(8)
            box = QComboBox(c)
            for s in snapshots:
                kind = {"last-known-good": "LKG", "before-ai-edit": "AI", "manual": "Manual",
                        "superseded-lkg": "old LKG"}.get(s.get("kind"), s.get("kind") or "")
                box.addItem(f"[{kind}] {s.get('label')} · {s.get('createdAt')}", s.get("snapshotId"))
            srow.addWidget(box, 1)
            rs = button(c, "RESTORE SNAPSHOT", "btn-dark", "refresh")
            rs.clicked.connect(lambda: self._restore_snapshot(box.currentData()))
            srow.addWidget(rs)
            cl.addLayout(srow)
            cl.addWidget(label(c, "Restoring takes a snapshot of the current state first — nothing is lost.", "muted"))

        sep2 = QFrame(c)
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {theme.BORDER};")
        cl.addWidget(sep2)
        cl.addWidget(label(c, "Shader Preset", "h3"))
        sc = r.get("shaderChoice") or {}
        cur = sc.get("preset")
        if not cur:
            cur = "balanced"
        if r.get("requirements") and not (r["requirements"].get("shaders")):
            cl.addWidget(label(c, "This pack has no shader selected. Picking one below installs it and re-tests the pack.", "muted"))
        elif sc.get("title"):
            prov = f" via {sc['provider']}" if sc.get("provider") else ""
            cl.addWidget(label(c, f"Current: {sc['title']} ({sc.get('preset', '')} preset on {sc.get('gpuTier', '?')} GPU{prov})", "sub"))
            cl.addWidget(label(c, f"{sc.get('reason', '')}", "muted"))
        else:
            cl.addWidget(label(c, f"No shader installed — {sc.get('reason', '')}", "muted"))
        preset_row = QHBoxLayout()
        self._shader_combo = QComboBox(c)
        self._shader_combo.addItems(["performance", "balanced", "cinematic"])
        self._shader_combo.setCurrentText(cur)
        preset_row.addWidget(self._shader_combo, 1)
        apply = button(c, "SWAP SHADER & RE-TEST", "btn-primary", "wand", theme.BG)
        apply.clicked.connect(self._save_shader_preset)
        preset_row.addWidget(apply)
        cl.addLayout(preset_row)
        cl.addWidget(label(c, "Re-runs the visuals step for this GPU, downloads the new shader pack, installs it into shaderpacks/, and re-tests the pack with a real launch. The swap is validated, not just recorded.", "muted"))

        sep = QFrame(c)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {theme.BORDER};")
        cl.addWidget(sep)
        cl.addWidget(label(c, "Save Pack", "h3"))
        cl.addWidget(label(c, "Backs up this pack's worlds + configs + visuals into an export ZIP — safe to keep after renaming or editing the pack.", "muted"))
        bsave = button(c, "SAVE PACK (BACKUP WORLDS)", "btn-primary", "save", theme.BG)
        bsave.clicked.connect(lambda: self.backup_requested.emit(self.build_id))
        cl.addWidget(bsave)
        self._backup_status = label(c, "", "sub")
        cl.addWidget(self._backup_status)

        sep = QFrame(c)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {theme.BORDER};")
        cl.addWidget(sep)
        cl.addWidget(label(c, "Exports", "h3"))
        for ex in (r.get("exports") or []):
            row = QHBoxLayout()
            row.addWidget(label(c, ex.get("kind", ""), "mono"))
            row.addWidget(label(c, fmt_bytes(ex.get("sizeBytes")), "muted"))
            row.addStretch(1)
            if ex.get("validated"):
                row.addWidget(label(c, "validated", "green"))
            dl = button(c, "Save", "btn-dark", "download")
            dl.clicked.connect(lambda _=False, fn=(ex.get("path") or "").rsplit("/", 1)[-1]:
                               self.export_requested.emit(self.build_id, fn))
            row.addWidget(dl)
            cl.addLayout(row)
        if not (r.get("exports") or []):
            cl.addWidget(label(c, "No exports generated yet.", "muted"))

        sep2 = QFrame(c)
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {theme.BORDER};")
        cl.addWidget(sep2)
        cl.addWidget(label(c, "Rename Pack", "h3"))
        rrow = QHBoxLayout()
        self._name_box = QLineEdit(c)
        self._name_box.setText(r.get("name") or "")
        rrow.addWidget(self._name_box, 1)
        save = button(c, "Save Name", "btn-primary", "check", theme.BG)
        save.clicked.connect(self._save_name)
        rrow.addWidget(save)
        cl.addLayout(rrow)
        self._body_lay.addWidget(c)

    def _save_name(self) -> None:
        name = self._name_box.text().strip()
        if name and self.build_id:
            self.rename_requested.emit(self.build_id, name)

    def _save_ram(self) -> None:
        if self.build_id:
            self.set_ram.emit(self.build_id, self._ram_slider.value())

    def _restore_lkg(self) -> None:
        if not self.build_id:
            return
        lkg = None
        try:
            lkg = self.api.last_known_good(self.build_id)
        except Exception:  # noqa: BLE001
            pass
        if not lkg:
            return
        d = QDialog(self)
        d.setWindowTitle("Restore Last Known Good")
        d.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        d.resize(460, 210)
        lay = vbox(d, 12, margins=(20, 18, 20, 18))
        lay.addWidget(label(d, "Restore Last Known Good?", "h3"))
        lay.addWidget(label(d, f"This pack's last validated state ({lkg.get('createdAt')}, "
                              f"{lkg.get('modCount')} mods on {lkg.get('minecraftVersion')} "
                              f"{lkg.get('loader')}) will be restored.", "muted"))
        lay.addWidget(label(d, "The current state is snapshotted first, so nothing is lost.", "muted"))
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button(d, "Cancel", "btn-dark")
        cancel.clicked.connect(d.reject)
        go = button(d, "RESTORE", "btn-primary", "refresh", theme.BG)
        go.clicked.connect(d.accept)
        row.addWidget(cancel)
        row.addWidget(go)
        lay.addLayout(row)
        if d.exec() != QDialog.DialogCode.Accepted:
            return

        def fetch():
            return self.api.restore_last_known_good(self.build_id)

        def ok(res):
            if self.build_id:
                self.status_changed.emit(self.build_id)

        def err(e):
            self.toast_error(f"Restore failed: {e}")

        run_async(fetch, ok, err)

    def _restore_snapshot(self, snapshot_id: str) -> None:
        if not self.build_id or not snapshot_id:
            return

        def fetch():
            return self.api.restore_snapshot(self.build_id, snapshot_id)

        def ok(res):
            if self.build_id:
                self.status_changed.emit(self.build_id)

        def err(e):
            self.toast_error(f"Restore failed: {e}")

        run_async(fetch, ok, err)

    def toast_error(self, msg: str) -> None:
        # PackDetail has no toast; surface via status_changed path is complex,
        # so use a modal-free approach: re-emit status to refresh and print.
        print(f"[packdetail] {msg}", flush=True)

    def _save_auto_relaunch(self, enabled: bool) -> None:
        if self.build_id:
            self.set_auto_relaunch.emit(self.build_id, bool(enabled))

    def _save_shader_preset(self) -> None:
        if self.build_id:
            self.set_shader_preset.emit(self.build_id, self._shader_combo.currentText())

    # -- dialogs -------------------------------------------------------
    def _ask_ai(self) -> None:
        d = QDialog(self)
        d.setWindowTitle("Ask AI to modify this pack")
        d.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        d.resize(480, 260)
        lay = vbox(d, 12, margins=(20, 18, 20, 18))
        lay.addWidget(label(d, f"Ask AI to modify {self.record.get('name', 'this pack')}", "h3"))
        box = QPlainTextEdit(d)
        box.setPlaceholderText("e.g. Add Create mod with dependencies, optimize RAM usage, add magic spells...")
        box.setMinimumHeight(90)
        lay.addWidget(box)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button(d, "Cancel", "btn-dark")
        cancel.clicked.connect(d.reject)
        go = button(d, "APPLY AI CHANGES", "btn-primary", "sparkles", theme.BG)
        def apply():
            prompt = box.toPlainText().strip()
            if prompt:
                self.ask_ai.emit(self.build_id, prompt)
            d.accept()
        go.clicked.connect(apply)
        row.addWidget(cancel)
        row.addWidget(go)
        lay.addLayout(row)
        d.exec()

    def _rename_dialog(self) -> None:
        d = QDialog(self)
        d.setWindowTitle("Rename pack")
        d.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        d.resize(380, 140)
        lay = vbox(d, 12, margins=(20, 18, 20, 18))
        lay.addWidget(label(d, "New pack name", "h3"))
        box = QLineEdit(d)
        box.setText((self.record or {}).get("name") or "")
        lay.addWidget(box)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button(d, "Cancel", "btn-dark")
        cancel.clicked.connect(d.reject)
        go = button(d, "Save", "btn-primary", "check", theme.BG)
        def apply():
            n = box.text().strip()
            if n:
                self.rename_requested.emit(self.build_id, n)
            d.accept()
        go.clicked.connect(apply)
        row.addWidget(cancel)
        row.addWidget(go)
        lay.addLayout(row)
        d.exec()

    def _export_menu(self) -> None:
        r = self.record or {}
        exports = r.get("exports") or []
        if not exports:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No exports", "This pack has no export artifacts yet.")
            return
        from PyQt6.QtWidgets import QMenu
        m = QMenu(self)
        m.setStyleSheet(f"QMenu {{ background: {theme.HOVER2}; color: {theme.TEXT}; border: 1px solid {theme.BORDER2}; border-radius: 8px; padding: 4px; }}"
                        f"QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}"
                        f"QMenu::item:selected {{ background: {theme.GREEN_DARK}; }}")
        for ex in exports:
            fn = (ex.get("path") or "").rsplit("/", 1)[-1]
            a = m.addAction(f"Save {ex.get('kind')} ({fn})")
            a.triggered.connect(lambda _=False, fn=fn: self.export_requested.emit(self.build_id, fn))
        m.exec(self._hero_inner.mapToGlobal(self._hero_inner.rect().bottomRight()))
