"""AI Builder — the design's AIBuilderView against the real build pipeline.

Build steps stream live over the backend SSE feed (/api/events?buildId=…),
so the timeline shows the ACTUAL stages (interpret → search → select →
resolve → conflict → download → test → export), never a fake timer.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
                             QScrollArea, QSizePolicy, QSlider, QTextEdit,
                             QVBoxLayout, QWidget)

import theme
from common import (button, card, clear_layout, icon_pixmap, label, pill,
                    progress, run_async, vbox)

STAGES = [
    ("interpret", "Analyzing user prompt & hardware capabilities"),
    ("search", "Searching Modrinth & CurseForge database index"),
    ("select", "Selecting primary mods & loader hooks"),
    ("visuals", "Selecting shaders & resource packs for your GPU"),
    ("resolve", "Resolving dependency graphs & transitive libs"),
    ("conflict", "Scanning for conflicts & known-bad combos"),
    ("download", "Downloading & installing mod files"),
    ("test", "Testing & verifying the instance"),
    ("export", "Generating exports & final report"),
]


class AIBuilderView(QWidget):
    build_completed = pyqtSignal(str)      # build_id — refresh library
    play_requested = pyqtSignal(str)

    def __init__(self, api):
        super().__init__()
        self.api = api
        self._steps: list[dict] = []
        self._stages = list(STAGES)
        self._seen: set[str] = set()
        self._completed_build: str | None = None
        # Stream/poll lifecycle (Issue 14): a session generation + stop event
        # bound every background thread. A new build or widget destruction
        # cancels the previous session so stale callbacks can't touch the UI.
        import threading
        self._session = 0
        self._stop_stream = threading.Event()
        self.destroyed.connect(self._cancel_session)

        outer = QScrollArea(self)
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.Shape.NoFrame)
        outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setProperty("page", "true")
        outer.setWidget(body)
        self.root = vbox(body, 24, margins=(32, 26, 32, 32))
        self.root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Header
        header = QWidget(body)
        header.setFixedHeight(142)
        head = vbox(header, 8, margins=(0, 6, 0, 0))
        head.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        mark = QFrame(header)
        mark.setProperty("cls", "logo-badge")
        mark.setFixedSize(44, 44)
        theme.polish(mark)
        mark_lay = vbox(mark, 0, margins=0)
        ic = QLabel(mark)
        ic.setPixmap(icon_pixmap("sparkles", theme.GREEN, 22))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark_lay.addWidget(ic)
        head.addWidget(mark, 0, Qt.AlignmentFlag.AlignHCenter)
        t = label(header, "Build your Minecraft experience", "h1")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(t)
        self._source_desc = label(header, "Describe what you want to play. Loading the engine's configured providers…", "sub")
        self._source_desc.setWordWrap(True)
        self._source_desc.setMaximumWidth(720)
        self._source_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self._source_desc)
        self.root.addWidget(header)

        self._input_card = card(body)
        self._input_card.setMaximumWidth(960)
        self._input_card.setFixedHeight(218)
        self._input_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._input_lay = vbox(self._input_card, 12, margins=(16, 16, 16, 16))
        self._prompt = QTextEdit(self._input_card)
        self._prompt.setPlaceholderText("Describe the Minecraft experience you want to build…")
        self._prompt.setMinimumHeight(112)
        self._prompt.setStyleSheet(
            f"QTextEdit {{ background: transparent; border: 1px solid transparent; "
            f"border-radius: {theme.R_MD}px; padding: 8px; font-size: 14px; }}"
            f"QTextEdit:focus {{ background: {theme.HOVER}; border: 1px solid rgba(57,184,106,0.72); }}"
        )
        self._input_lay.addWidget(self._prompt)

        chip_rows = QVBoxLayout()
        chip_rows.setSpacing(6)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        chips.addWidget(label(self._input_card, "Quick ideas:", "muted"))
        ideas = ["Medieval RPG", "Vanilla+ Enhanced", "Horror Survival", "Create & Automate", "Arcane Magic", "High FPS Performance"]
        for idea in ideas[:5]:
            c = pill(self._input_card, idea, False, "pill")
            c.clicked.connect(lambda _=False, i=idea: self._prompt.setPlainText(f"Build a {i.lower()} modpack with shaders and optimized performance"))
            chips.addWidget(c)
        chips.addStretch(1)
        chip_rows.addLayout(chips)
        chips_last = QHBoxLayout()
        last = pill(self._input_card, ideas[-1], False, "pill")
        last.clicked.connect(lambda _=False: self._prompt.setPlainText(
            "Build a high fps performance modpack with shaders and optimized performance"))
        chips_last.addWidget(last)
        chips_last.addStretch(1)
        chip_rows.addLayout(chips_last)
        self._input_lay.addLayout(chip_rows)

        self._settings_card = card(body)
        self._settings_card.setMaximumWidth(960)
        self._settings_card.setFixedHeight(116)
        self._settings_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._settings_lay = vbox(self._settings_card, 12, margins=(16, 14, 16, 14))
        toprow = QHBoxLayout()
        hw_icon = QLabel(self._settings_card)
        hw_icon.setPixmap(icon_pixmap("cpu", theme.GREEN, 16))
        toprow.addWidget(hw_icon)
        self._hw_label = label(self._settings_card, "Hardware: detecting…", "small")
        toprow.addWidget(self._hw_label)
        toprow.addStretch(1)
        adv = button(self._settings_card, "Advanced Settings ▾", "ghost")
        self._show_adv = False
        adv.clicked.connect(lambda: self._toggle_adv(adv))
        toprow.addWidget(adv)
        self._settings_lay.addLayout(toprow)

        self._adv_grid = QVBoxLayout()
        self._adv_grid.setSpacing(12)
        grid1 = QHBoxLayout()
        grid1.setSpacing(16)
        vcol = QVBoxLayout()
        vcol.setSpacing(4)
        vcol.addWidget(label(self._settings_card, "Minecraft Version", "sub"))
        self._mc_box = QComboBox(self._settings_card)
        self._mc_box.addItems(["auto", "1.20.1", "1.20.4", "1.21.1", "1.19.2"])
        self._mc_box.setCurrentIndex(0)
        vcol.addWidget(self._mc_box)
        grid1.addLayout(vcol, 1)
        lcol = QVBoxLayout()
        lcol.setSpacing(4)
        lcol.addWidget(label(self._settings_card, "Mod Loader", "sub"))
        self._loader_box = QComboBox(self._settings_card)
        self._loader_box.addItems(["auto", "Forge", "Fabric", "NeoForge", "Quilt"])
        lcol.addWidget(self._loader_box)
        grid1.addLayout(lcol, 1)
        self._adv_grid.addLayout(grid1)

        ramrow = QHBoxLayout()
        ramcol = QVBoxLayout()
        ramcol.setSpacing(4)
        self._ram_label = label(self._settings_card, "RAM Allocation: 6 GB", "sub")
        ramcol.addWidget(self._ram_label)
        self._ram = QSlider(Qt.Orientation.Horizontal, self._settings_card)
        self._ram.setRange(3, 12)
        self._ram.setValue(6)
        self._ram.valueChanged.connect(lambda v: self._ram_label.setText(f"RAM Allocation: {v} GB"))
        ramcol.addWidget(self._ram)
        ramrow.addLayout(ramcol, 1)
        self._adv_grid.addLayout(ramrow)

        chkrow = QHBoxLayout()
        chkrow.addWidget(label(self._settings_card, "Include Shaders", "sub"))
        self._shaders_chk = QCheckBox(self._settings_card)
        self._shaders_chk.setChecked(True)
        self._shaders_chk.setStyleSheet(f"QCheckBox::indicator {{ width: 16px; height: 16px; }} QCheckBox::indicator:checked {{ background: {theme.GREEN}; border-radius: 4px; }}")
        chkrow.addWidget(self._shaders_chk)
        chkrow.addStretch(1)
        chkrow.addWidget(label(self._settings_card, "Auto-tune to my PC", "sub"))
        self._autotune_chk = QCheckBox(self._settings_card)
        self._autotune_chk.setChecked(False)
        chkrow.addWidget(self._autotune_chk)
        self._adv_grid.addLayout(chkrow)
        self._adv_grid_widget = QWidget(self._settings_card)
        self._adv_grid_widget.setLayout(self._adv_grid)
        self._adv_grid_widget.setVisible(False)
        self._settings_lay.addWidget(self._adv_grid_widget)

        self._build_btn = button(self._settings_card, "BUILD MODPACK WITH AI", "btn-primary", "sparkles", theme.BG)
        self._build_btn.setMinimumHeight(46)
        self._build_btn.setEnabled(False)
        self._prompt.textChanged.connect(
            lambda: self._build_btn.setEnabled(bool(self._prompt.toPlainText().strip())))
        self._build_btn.clicked.connect(self._start)
        self._settings_lay.addWidget(self._build_btn)
        self._form = QWidget(body)
        self._form.setFixedHeight(354)
        form_lay = vbox(self._form, 20, margins=0)
        form_lay.addWidget(self._input_card, 0, Qt.AlignmentFlag.AlignHCenter)
        form_lay.addWidget(self._settings_card, 0, Qt.AlignmentFlag.AlignHCenter)
        # Keep the form near its explanation and primary action. The nullable
        # stretch handles remain for compatibility with older saved sessions;
        # running/done states use the same top-aligned scroll flow.
        self._form_stretch_top = None
        self._form_stretch_bottom = None
        self.root.addWidget(self._form, 0, Qt.AlignmentFlag.AlignHCenter)

        # Build timeline card
        self._timeline_card = card(body)
        self._timeline_card.setMaximumWidth(960)
        self._timeline_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._timeline_lay = vbox(self._timeline_card, 10, margins=(20, 16, 20, 16))
        self._timeline_card.setVisible(False)
        self.root.addWidget(self._timeline_card, 0, Qt.AlignmentFlag.AlignHCenter)

        # Completed card
        self._done_card = card(body)
        self._done_card.setMaximumWidth(960)
        self._done_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._done_lay = vbox(self._done_card, 14, margins=(30, 26, 30, 26))
        self._done_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._done_card.setVisible(False)
        self.root.addWidget(self._done_card, 0, Qt.AlignmentFlag.AlignHCenter)

        lay = vbox(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(outer)

        self._center_form(True)
        self._load_hardware()

    # ------------------------------------------------------------------
    def seed_prompt(self, prompt: str) -> None:
        """Pre-fill the request from a starter concept / Surprise Me brief."""
        prompt = (prompt or "").strip()
        if prompt:
            self._prompt.setPlainText(prompt)
            self._build_btn.setEnabled(True)

    def _load_hardware(self) -> None:
        def fetch():
            return self.api.hardware(), self.api.settings_get()

        def ok(result):
            hw, settings = result
            eff = hw.get("effective") or {}
            det = hw.get("detected") or {}
            cpu = eff.get("cpu") or det.get("cpu") or "—"
            ram = eff.get("ramGB") or det.get("ramGB") or "—"
            cpu_short = str(cpu).split(" with ", 1)[0]
            self._hw_label.setText(f"Hardware Fit: {cpu_short} / {ram} GB RAM Detected")
            configured = (settings.get("build") or {}).get("sources") or ["modrinth"]
            providers = []
            if "modrinth" in configured:
                providers.append("Modrinth")
            curseforge_ready = "curseforge" in configured and bool(settings.get("curseforgeKeyConfigured"))
            if curseforge_ready:
                providers.append("CurseForge")
            provider_text = " & ".join(providers) or "no online provider"
            suffix = " CurseForge needs an API key in Settings." if "curseforge" in configured and not curseforge_ready else ""
            self._source_desc.setText(
                f"Describe what you want to play. The builder will search {provider_text}, resolve dependency graphs, "
                f"perform compatibility scans, and package it.{suffix}"
            )
            self._stages[1] = ("search", f"Searching {provider_text} provider index")

        run_async(fetch, ok, None)

    def _center_form(self, center: bool) -> None:
        """Keep the builder top-aligned so its primary action stays in view."""
        if self._form_stretch_top is not None:
            self.root.removeItem(self._form_stretch_top)
            self.root.removeItem(self._form_stretch_bottom)
            self._form_stretch_top = None
            self._form_stretch_bottom = None

    def _toggle_adv(self, btn) -> None:
        self._show_adv = not self._show_adv
        self._adv_grid_widget.setVisible(self._show_adv)
        self._settings_card.setFixedHeight(300 if self._show_adv else 116)
        self._form.setFixedHeight(538 if self._show_adv else 354)
        btn.setText("Advanced Settings ▴" if self._show_adv else "Advanced Settings ▾")

    # ------------------------------------------------------------------
    def _cancel_session(self) -> None:
        """Cancel the current build's stream/poll session (new build or the
        widget being destroyed). Callbacks from the old generation are dropped."""
        self._session += 1
        self._stop_stream.set()

    def _start(self) -> None:
        prompt = self._prompt.toPlainText().strip()
        if not prompt:
            return
        # Cancel any previous session before starting a new build.
        import threading
        self._session += 1
        self._stop_stream = threading.Event()
        req = {
            "prompt": prompt,
            "mcVersion": None if self._mc_box.currentText() == "auto" else self._mc_box.currentText(),
            "loader": None if self._loader_box.currentText() == "auto" else self._loader_box.currentText().lower(),
            "ramGB": self._ram.value(),
            "shaders": self._shaders_chk.isChecked(),
            "autoTune": self._autotune_chk.isChecked(),
        }
        req = {k: v for k, v in req.items() if v is not None or k == "autoTune"}
        self._steps = []
        self._seen = set()
        self._timeline_card.setVisible(True)
        self._done_card.setVisible(False)
        self._form.setVisible(False)
        self._center_form(False)
        self._build_btn.setEnabled(False)
        self._render_timeline()
        self._build_btn.setText("BUILDING…")

        def start():
            return self.api.start_build(req)

        def ok(build_id):
            self._completed_build = build_id
            self._stream(build_id)

        def err(e):
            self._fail(f"Build could not start: {e}")

        run_async(start, ok, err)

    def _stream(self, build_id: str) -> None:
        # SSE is consumed in a worker; each event is delivered to the UI thread
        # through the queued-signal bridge (QTimer.singleShot from a worker
        # thread never fires — it has no event loop). The engine keeps a
        # finished build's stream open forever, so a second loop polls the
        # build record for a terminal status and calls _finish.
        #
        # Lifecycle safety (Issue 14): every thread is bound to the current
        # session generation and a stop event. A new build or widget
        # destruction cancels the previous session; callbacks from a stale
        # generation can never touch the UI for a newer build.
        import threading
        import time
        from common import _post

        gen = self._session
        stop = self._stop_stream

        def current() -> bool:
            return gen == self._session and not stop.is_set()

        def consume():
            n = 0
            try:
                for ev in self.api.events(build_id):
                    if not current():
                        break
                    n += 1
                    _post(lambda e, g=gen: self._on_event(e) if g == self._session else None, ev)
            except Exception as e:  # noqa: BLE001
                print(f"[aibuilder-consume] stopped after {n} events: {e}", flush=True)
            print(f"[aibuilder-consume] stream ended, {n} events read", flush=True)

        threading.Thread(target=consume, daemon=True).start()

        def worker():
            delay = 1.0
            deadline = time.time() + 45 * 60  # hard cap so a hung engine can't spin forever
            while current():
                try:
                    rec = self.api.build(build_id)
                except Exception as e:  # noqa: BLE001
                    rec = {}
                    print(f"[aibuilder-poll] {e}", flush=True)
                if rec.get("status") in ("done", "failed", "repaired", "stopped"):
                    break
                if time.time() > deadline:
                    print("[aibuilder-poll] deadline reached without terminal status", flush=True)
                    rec = {}
                    break
                time.sleep(delay)
                delay = min(delay * 2, 8.0)  # bounded backoff on transient errors
            stop.set()  # tell the event consumer to stop reading too
            print(f"[aibuilder-poll] terminal status: {rec.get('status')}", flush=True)
            time.sleep(0.6)  # let the last events flush through the bridge
            if gen == self._session:
                _post(lambda record: self._finish(build_id, record), rec)

        threading.Thread(target=worker, daemon=True).start()

    def _on_event(self, ev: dict) -> None:
        stage = ev.get("stage") or ""
        status = ev.get("status") or ""
        detail = ev.get("message") or ev.get("detail") or ""
        progress = ev.get("progress")
        if status == "done" and stage:
            self._mark_done(stage, detail)
        elif status == "failed" and stage:
            self._mark_failed(stage, detail)
        elif stage:
            self._mark_active(stage, detail)
        if isinstance(progress, (int, float)):
            pass  # stages carry the detail

    def _idx(self, stage: str) -> int:
        # alias the engine's early stages onto the timeline
        if stage in ("init", "parse", "hardware"):
            return 0
        if stage in ("reconcile", "config", "perf", "system", "report", "import"):
            return 6
        for i, (sid, _label) in enumerate(self._stages):
            if stage.startswith(sid) or sid.startswith(stage) or stage == sid:
                return i
        # fuzzy: any stage word inside the event stage
        for i, (sid, _label) in enumerate(self._stages):
            if stage and sid in stage:
                return i
        return -1

    def _mark_active(self, stage: str, detail: str) -> None:
        idx = self._idx(stage)
        if idx < 0:
            idx = len(self._steps)
        while len(self._steps) <= idx:
            stage_index = len(self._steps)
            stage_label = self._stages[stage_index][1] if stage_index < len(self._stages) else (detail or stage)
            self._steps.append({"label": stage_label, "status": "pending", "detail": ""})
        self._steps[idx]["status"] = "in_progress"
        self._steps[idx]["detail"] = detail
        self._render_timeline()

    def _mark_done(self, stage: str, detail: str) -> None:
        idx = self._idx(stage)
        if idx < 0:
            return
        self._steps[idx]["status"] = "completed"
        if detail:
            self._steps[idx]["detail"] = detail
        self._render_timeline()

    def _mark_failed(self, stage: str, detail: str) -> None:
        idx = self._idx(stage)
        if idx >= 0:
            self._steps[idx]["status"] = "failed"
            self._steps[idx]["detail"] = detail
        self._render_timeline()

    @staticmethod
    def _terminal_outcome(record: dict) -> dict:
        """One authoritative terminal state for a build record.

        Prefers record['testResult'] — the engine's current result — over the
        test list; falls back to the latest recorded test. Both _finish and
        _show_done use this so the timeline, done card, badge and Play
        availability can never disagree (Issue 13).
        """
        if record.get("testResult"):
            return record["testResult"]
        tests = record.get("tests") or []
        return tests[-1] if tests else {}

    @staticmethod
    def _build_failed(record: dict) -> bool:
        if record.get("status") == "failed":
            return True
        res = AIBuilderView._terminal_outcome(record)
        return bool(res and res.get("status") == "FAIL")

    def _finish(self, build_id: str, record: dict | None = None) -> None:
        self._build_btn.setEnabled(True)
        self._build_btn.setText("BUILD MODPACK WITH AI")
        record = record or {}
        failed = self._build_failed(record)
        for step in self._steps:
            if failed:
                # explicit failed stays failed; anything still in flight is
                # terminal-failed with the build.
                if step["status"] == "in_progress":
                    step["status"] = "failed"
            else:
                # A terminal successful build record is authoritative evidence
                # that every pipeline stage completed even if an SSE event was
                # missed during a reconnect (Issue 12): pending AND in_progress
                # stages all resolve to completed.
                if step["status"] in ("pending", "in_progress"):
                    step["status"] = "completed"
        self._render_timeline()
        self._show_done(build_id, record)
        self.build_completed.emit(build_id)

    def _fail(self, msg: str) -> None:
        self._build_btn.setEnabled(True)
        self._build_btn.setText("BUILD MODPACK WITH AI")
        self._form.setVisible(True)
        self._center_form(True)
        self._timeline_card.setVisible(False)
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "Build failed", msg)

    # ------------------------------------------------------------------
    def _render_timeline(self) -> None:
        clear_layout(self._timeline_lay)
        for s in self._steps:
            row = QHBoxLayout()
            row.setSpacing(10)
            ic = QLabel(self._timeline_card)
            st = s["status"]
            if st == "completed":
                ic.setPixmap(icon_pixmap("checkcircle", theme.GREEN, 16))
            elif st == "in_progress":
                ic.setPixmap(icon_pixmap("refresh", theme.BLUE, 16))
            elif st == "failed":
                ic.setPixmap(icon_pixmap("alert", theme.DANGER, 16))
            else:
                ic.setPixmap(icon_pixmap("clock", theme.MUTED, 16))
            row.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(1)
            t = label(self._timeline_card, s["label"], "sub")
            if st == "completed":
                t.setProperty("cls", "sub green")
                theme.polish(t)
            col.addWidget(t)
            if s.get("detail"):
                col.addWidget(label(self._timeline_card, s["detail"][:140], "muted"))
            row.addLayout(col, 1)
            self._timeline_lay.addLayout(row)

    def _show_done(self, build_id: str, record: dict | None = None) -> None:
        from common import clear_layout
        clear_layout(self._done_lay)
        record = record or {}
        res = self._terminal_outcome(record)
        test_status = str(res.get("status") or "NOT RECORDED")
        test_level = str(res.get("level") or "")
        failed = self._build_failed(record)
        ic = QLabel(self._done_card)
        ic.setPixmap(icon_pixmap("alert" if failed else "checkcircle", theme.DANGER if failed else theme.GREEN, 44))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._done_lay.addWidget(ic)
        badge_text = "BUILD FAILED" if failed else f"PACK READY • {test_status}" + (f" ({test_level})" if test_level else "")
        badge = label(self._done_card, badge_text, "warn" if failed else "green")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._done_lay.addWidget(badge)
        t = label(self._done_card, "Build needs attention" if failed else "Build complete", "h1")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._done_lay.addWidget(t)
        if failed:
            failure = record.get("failure") or {}
            import json
            fr = record.get("finalReport")
            if isinstance(fr, dict):
                fr = json.dumps(fr, indent=2)
            message = failure.get("message") or fr or "The engine recorded a failed build. Open it in the Library to inspect the real report and logs."
        else:
            message = "The pack is in your Library — open it to inspect mods, exports, and test results."
        p = label(self._done_card, message, "sub")
        p.setWordWrap(True)
        p.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._done_lay.addWidget(p)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if not failed:
            play = button(self._done_card, "PLAY NOW", "btn-primary", "play", theme.BG)
            play.clicked.connect(lambda: self.play_requested.emit(build_id))
            row.addWidget(play)
        again = button(self._done_card, "Build Another Pack", "btn-dark")
        again.clicked.connect(self._reset)
        row.addWidget(again)
        self._done_lay.addLayout(row)
        self._done_card.setVisible(True)

    def _reset(self) -> None:
        self._done_card.setVisible(False)
        self._timeline_card.setVisible(False)
        self._form.setVisible(True)
        self._center_form(True)
        self._prompt.setPlainText("")
        self._steps = []
