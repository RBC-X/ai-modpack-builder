"""Home view — hero showcase of the selected pack + recently played + hardware."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit,
                             QPushButton, QScrollArea, QVBoxLayout, QWidget)

import theme
from common import (avatar, button, card, clear_layout, fmt_ago, hbox, icon_btn,
                    icon_pixmap, label, pill, vbox)
from icons import ICONS

# Rotating example prompts shown when the hero field is empty (§26). They
# seed a coherent brief — never a fake mod list.
PROMPT_IDEAS = [
    "A dark medieval RPG with dangerous bosses and magic.",
    "Cozy farming and exploration for multiplayer.",
    "Realistic survival that runs well on an 8 GB laptop.",
    "Create-focused industrial civilization.",
]


class HomeView(QWidget):
    play_requested = pyqtSignal(str)
    stop_requested = pyqtSignal(str)
    open_detail = pyqtSignal(str)
    navigate = pyqtSignal(str)
    import_requested = pyqtSignal()
    select_build = pyqtSignal(str)
    seed_requested = pyqtSignal(str)      # composed concept brief → AI Builder

    def __init__(self, hardware: dict | None = None):
        super().__init__()
        self.builds: list[dict] = []
        self.selected_id: str | None = None
        self.hardware = hardware
        self._hero_icon: QLabel | None = None
        self._idea_idx = 0
        self._idea_timer: QTimer | None = None

        outer = QScrollArea(self)
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.Shape.NoFrame)
        outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setProperty("page", "true")
        outer.setWidget(body)
        self.root = vbox(body, 32, margins=(32, 32, 32, 32))
        self.root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Signature prompt card — "What kind of Minecraft experience do you
        # want?" (§24-25). Always first on Home so a new user knows what the
        # product does within five seconds (§223). Seeding navigates to the
        # AI Builder with the brief pre-filled.
        self._prompt_card = card(body)
        self._prompt_card.setProperty("cls", "search-panel")
        theme.polish(self._prompt_card)
        self._prompt_lay = vbox(self._prompt_card, 14, margins=(24, 20, 24, 20))
        prompt_head = QHBoxLayout()
        prompt_mark = QLabel(self._prompt_card)
        prompt_mark.setPixmap(icon_pixmap("sparkles", theme.GREEN, 20))
        prompt_head.addWidget(prompt_mark)
        prompt_title = label(self._prompt_card, "What kind of Minecraft experience do you want?", "h2")
        prompt_head.addWidget(prompt_title)
        prompt_head.addStretch(1)
        self._prompt_lay.addLayout(prompt_head)

        prompt_row = QHBoxLayout()
        prompt_row.setSpacing(10)
        self._prompt = QPlainTextEdit(self._prompt_card)
        self._prompt.setPlaceholderText(PROMPT_IDEAS[0])
        self._prompt.setFixedHeight(64)
        self._prompt.setStyleSheet(
            f"QPlainTextEdit {{ background: {theme.HOVER}; border: 1px solid {theme.BORDER}; "
            f"border-radius: {theme.R_MD}px; padding: 8px 12px; font-size: {theme.T_BODY}px; }}"
            f"QPlainTextEdit:focus {{ border: 1px solid rgba(57,184,106,0.5); }}"
        )
        prompt_row.addWidget(self._prompt, 1)
        create = button(self._prompt_card, "CREATE EXPERIENCE", "btn-primary", "sparkles", theme.BG)
        create.setMinimumSize(theme.H_LG + 130, theme.H_LG)
        create.clicked.connect(self._create_from_prompt)
        prompt_row.addWidget(create)
        self._prompt_lay.addLayout(prompt_row)

        self._prompt_hint = label(self._prompt_card,
                                  "AI picks compatible mods, resolves dependencies, tests the game, and repairs crashes — just describe the experience.",
                                  "muted")
        self._prompt_hint.setWordWrap(True)
        self._prompt_lay.addWidget(self._prompt_hint)
        self.root.addWidget(self._prompt_card)

        # Rotating suggestion when empty — slow (one idea per 6s, §26).
        self._idea_timer = QTimer(self)
        self._idea_timer.setInterval(6000)
        self._idea_timer.timeout.connect(self._rotate_idea)
        self._idea_timer.start()

        self._hero = QFrame(body)
        self._hero.setProperty("cls", "hero")
        self._hero.setFixedHeight(368)
        theme.polish(self._hero)
        self._hero_inner = QWidget(self._hero)
        self._hero_lay = vbox(self._hero_inner, 14, margins=(40, 40, 40, 40))
        hero_out = QVBoxLayout(self._hero)
        hero_out.setContentsMargins(0, 0, 0, 0)
        hero_out.addWidget(self._hero_inner)
        self.root.addWidget(self._hero)

        # Starter experiences — curated, editable concept templates that seed
        # the AI Builder (always visible, even on an empty library).
        self._starter_section = QWidget(body)
        self._build_starter_section()
        self.root.addWidget(self._starter_section)

        # Keep the outer 32px section rhythm while using the reference's
        # tighter 16px gap between the recent heading and its cards.
        self._recent_section = QWidget(body)
        recent_section_lay = vbox(self._recent_section, 16, margins=0)
        self._recent_header = QWidget(self._recent_section)
        recent_head = hbox(self._recent_header, 8, margins=0)
        self._recent_title = label(self._recent_header, "Recent Builds", "h2")
        recent_head.addWidget(self._recent_title)
        recent_head.addStretch(1)
        self._view_all = button(self._recent_header, "View All Library", "ghost")
        self._view_all.clicked.connect(lambda: self.navigate.emit("library"))
        recent_head.addWidget(self._view_all)
        recent_section_lay.addWidget(self._recent_header)
        self._recent_grid = QGridLayout()
        self._recent_grid.setSpacing(16)
        recent_section_lay.addLayout(self._recent_grid)
        self.root.addWidget(self._recent_section)

        self._empty = self._build_empty(body)
        self.root.addWidget(self._empty)

        self._bottom = QFrame(body)
        self._bottom.setProperty("cls", "")
        self._bottom_inner = QWidget(self._bottom)
        self._bottom_lay = QGridLayout(self._bottom_inner)
        self._bottom_lay.setContentsMargins(0, 0, 0, 0)
        self._bottom_lay.setSpacing(16)
        self._bottom_lay.setColumnStretch(0, 2)
        self._bottom_lay.setColumnStretch(1, 1)
        bot_out = QVBoxLayout(self._bottom)
        bot_out.setContentsMargins(0, 0, 0, 0)
        bot_out.addWidget(self._bottom_inner)
        self.root.addWidget(self._bottom)

        lay = vbox(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(outer)

    # ------------------------------------------------------------------
    def _create_from_prompt(self) -> None:
        """Seed the AI Builder with the typed brief (or a rotating idea if empty)."""
        text = self._prompt.toPlainText().strip()
        if not text:
            text = PROMPT_IDEAS[self._idea_idx % len(PROMPT_IDEAS)]
        self.seed_requested.emit(text)

    def _rotate_idea(self) -> None:
        """Slowly cycle the empty-field suggestion (§26 — never aggressive)."""
        self._idea_idx = (self._idea_idx + 1) % len(PROMPT_IDEAS)
        self._prompt.setPlaceholderText(PROMPT_IDEAS[self._idea_idx])

    # ------------------------------------------------------------------
    def _build_empty(self, parent: QWidget) -> QFrame:
        c = card(parent)
        inner = vbox(c, 16, margins=(40, 40, 40, 40))
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel(c)
        ic.setPixmap(icon_pixmap("sparkles", theme.GREEN, 40))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(ic)
        t = label(c, "Your library is empty", "h2")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(t)
        s = label(c, "Build your first AI modpack, import an existing .mrpack, or discover popular community modpacks.", "sub")
        s.setWordWrap(True)
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(s)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b1 = button(c, "BUILD WITH AI", "btn-primary", "sparkles")
        b1.clicked.connect(lambda: self.navigate.emit("ai-builder"))
        b2 = button(c, "IMPORT MODPACK", "btn-dark", "folder")
        b2.clicked.connect(self.import_requested.emit)
        b3 = button(c, "DISCOVER PACKS", "btn-dark")
        b3.clicked.connect(lambda: self.navigate.emit("discover"))
        row.addWidget(b1)
        row.addWidget(b2)
        row.addWidget(b3)
        inner.addLayout(row)
        c.setVisible(False)
        return c

    # ------------------------------------------------------------------
    # Starter experiences + Surprise Me
    # ------------------------------------------------------------------
    def _build_starter_section(self) -> None:
        import engine.concepts as concepts
        lay = vbox(self._starter_section, 14, margins=0)
        header = QWidget(self._starter_section)
        head = hbox(header, 8, margins=0)
        head.addWidget(label(header, "Starter Experiences", "h2"))
        head.addStretch(1)
        surprise = button(header, "SURPRISE ME", "btn-primary", "sparkles", theme.BG)
        surprise.setToolTip("Roll a fresh, coherent creative concept you can edit before building.")
        surprise.clicked.connect(self._surprise_me)
        head.addWidget(surprise)
        lay.addWidget(header)
        grid = QGridLayout()
        grid.setSpacing(14)
        for i, c in enumerate(concepts.STARTER_CONCEPTS):
            grid.setColumnStretch(i % 3, 1)
            grid.addWidget(self._concept_card(c), i // 3, i % 3)
        lay.addLayout(grid)

    def _concept_card(self, concept: dict) -> QFrame:
        c = card(self._starter_section, hover=True)
        c.setMinimumHeight(138)
        c.setCursor(Qt.CursorShape.PointingHandCursor)
        row = hbox(c, 12, margins=(16, 14, 16, 14))
        ic = QLabel(c)
        ic.setFixedSize(40, 40)
        ic.setPixmap(icon_pixmap(concept.get("icon") or "sparkles", theme.GREEN, 22))
        row.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        col = vbox(c, 3)
        t = label(c, concept.get("title") or "?", "h3")
        col.addWidget(t)
        tag = label(c, concept.get("tagline") or "", "muted")
        tag.setWordWrap(True)
        col.addWidget(tag)
        use = label(c, "Use template →", "small green")
        use.setStyleSheet(f"QLabel {{ color: {theme.GREEN}; font-weight: 600; }}")
        col.addWidget(use)
        row.addLayout(col, 1)
        c.mousePressEvent = lambda e, cp=concept: self._open_concept_editor(cp)
        return c

    def _surprise_me(self) -> None:
        import engine.concepts as concepts
        concept = concepts.surprise_me(hardware=self.hardware)
        self._open_concept_editor(concept, rollable=True)

    def _open_concept_editor(self, concept: dict, rollable: bool = False) -> None:
        """Editable concept preview: brief + prompt; BUILD seeds the AI Builder."""
        from PyQt6.QtWidgets import QDialog, QPlainTextEdit, QScrollArea
        import engine.concepts as concepts
        d = QDialog(self)
        d.setWindowTitle("Starter experience")
        d.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        d.resize(640, 600)
        dlay = vbox(d, 12, margins=(22, 18, 22, 18))
        self._ce_title = label(d, "", "h2")
        self._ce_title.setWordWrap(True)
        dlay.addWidget(self._ce_title)
        self._ce_tagline = label(d, "", "muted")
        self._ce_tagline.setWordWrap(True)
        dlay.addWidget(self._ce_tagline)

        scroll = QScrollArea(d)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(230)
        brief_host = QWidget()
        self._ce_brief = vbox(brief_host, 6, margins=(2, 2, 2, 2))
        scroll.setWidget(brief_host)
        dlay.addWidget(scroll)

        dlay.addWidget(label(d, "Prompt sent to the AI builder (edit freely):", "muted"))
        self._ce_prompt = QPlainTextEdit(d)
        self._ce_prompt.setMinimumHeight(120)
        dlay.addWidget(self._ce_prompt, 1)
        self._ce_note = label(d, "The brief is a template — you can change anything before building.", "muted")
        dlay.addWidget(self._ce_note)

        def apply(c: dict) -> None:
            self._ce_title.setText(c.get("title") or "")
            tag = c.get("tagline") or ""
            if c.get("seedConcept"):
                tag = c["seedConcept"]
            self._ce_tagline.setText(tag)
            clear_layout(self._ce_brief)
            for lab, val in concepts.brief_lines(c):
                row = QHBoxLayout()
                row.setSpacing(8)
                row.addWidget(label(brief_host, lab, "muted"))
                row.addStretch(1)
                row.addWidget(label(brief_host, val, "small"), 3)
                self._ce_brief.addLayout(row)
            self._ce_prompt.setPlainText(c.get("prompt") or "")

        apply(concept)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button(d, "Cancel", "btn-dark")
        cancel.clicked.connect(d.reject)
        row.addWidget(cancel)
        if rollable:
            reroll = button(d, "RE-ROLL", "btn-dark", "refresh")
            reroll.clicked.connect(lambda: apply(concepts.surprise_me(hardware=self.hardware)))
            row.addWidget(reroll)
        go = button(d, "BUILD WITH AI", "btn-primary", "sparkles", theme.BG)
        go.clicked.connect(lambda: (self.seed_requested.emit(self._ce_prompt.toPlainText().strip()),
                                    d.accept()))
        row.addWidget(go)
        dlay.addLayout(row)
        d.exec()

    # ------------------------------------------------------------------
    def set_hardware(self, hardware: dict | None) -> None:
        self.hardware = hardware
        self._render()

    def set_builds(self, builds: list[dict]) -> None:
        self.builds = builds
        if self.selected_id not in [b.get("buildId") for b in builds] and builds:
            self.selected_id = builds[0].get("buildId")
        self._render()

    def selected(self) -> dict | None:
        for b in self.builds:
            if b.get("buildId") == self.selected_id:
                return b
        return self.builds[0] if self.builds else None

    def _render(self) -> None:
        sel = self.selected()
        empty = not self.builds or sel is None
        self._hero.setVisible(not empty)
        self._recent_section.setVisible(not empty)
        self._empty.setVisible(empty)
        self._bottom.setVisible(not empty)
        if empty:
            return
        self._view_all.setText(f"View All Library ({len(self.builds)})  →")
        self._render_hero(sel)
        self._render_recent()

        # Bottom row: hardware recommendation + updates
        self._render_bottom(sel)

    def _render_hero(self, b: dict) -> None:
        clear_layout(self._hero_lay)
        hero_lay = self._hero_lay

        running = bool(b.get("running"))
        self._hero.setProperty("cls", "hero-running" if running else "hero")
        theme.polish(self._hero)

        # top badges
        badges = QHBoxLayout()
        badges.setSpacing(8)
        mc = b.get("mcVersion") or b.get("minecraftVersion") or ""
        loader = (b.get("loader") or "").capitalize()
        loader_version = b.get("loaderVersion") or ""
        loader_text = f"{loader} {loader_version}".strip()
        version_badge = pill(self._hero_inner, f"Minecraft {mc} • {loader_text}", True, "pill")
        version_badge.setFixedHeight(26)
        badges.addWidget(version_badge)
        mods_badge = pill(self._hero_inner, f"{b.get('modCount', 0)} Mods", False, "pill",
                          "layers", theme.BLUE)
        mods_badge.setFixedHeight(26)
        badges.addWidget(mods_badge)
        fit = b.get("hardwareFit") or b.get("ramTarget") or "Hardware detected"
        fit_suffix = " for this PC" if b.get("hardwareFit") else ""
        hardware_badge = pill(self._hero_inner, f"{fit}{fit_suffix}", False, "pill",
                              "cpu", theme.GREEN)
        hardware_badge.setFixedHeight(26)
        badges.addWidget(hardware_badge)
        badges.addStretch(1)
        hero_lay.addLayout(badges)

        hero_lay.addStretch(1)

        # title and real build description. The reference hero keeps this area
        # typographic; pack artwork remains visible in the Library cards.
        name_row = QHBoxLayout()
        name_col = QVBoxLayout()
        name_col.setSpacing(8)
        t = label(self._hero_inner, b.get("name") or "Untitled pack", "banner-title")
        t.setWordWrap(True)
        t.setMaximumWidth(760)
        name_col.addWidget(t)
        desc = label(self._hero_inner, (b.get("description") or b.get("request") or ""), "sub")
        desc.setWordWrap(True)
        desc.setMaximumWidth(576)
        name_col.addWidget(desc)
        name_row.addLayout(name_col, 1)
        name_row.addStretch(1)
        hero_lay.addLayout(name_row)

        hero_lay.addStretch(1)

        # actions
        actions = QHBoxLayout()
        actions.setSpacing(12)
        if running:
            stop = button(self._hero_inner, "■ STOP GAME", "btn-danger")
            stop.clicked.connect(lambda: self.stop_requested.emit(b.get("buildId")))
            actions.addWidget(stop)
        else:
            play = button(self._hero_inner, "PLAY", "btn-primary", "play", theme.BG)
            play.setMinimumSize(160, 48)
            play.clicked.connect(lambda: self.play_requested.emit(b.get("buildId")))
            actions.addWidget(play)
        more = icon_btn(self._hero_inner, "more", "Instance options", theme.TEXT2)
        more.setFixedSize(48, 48)
        more.clicked.connect(lambda: self._more_menu(b))
        actions.addWidget(more)
        actions.addStretch(1)
        hero_lay.addLayout(actions)

    def _more_menu(self, b: dict) -> None:
        from PyQt6.QtWidgets import QMenu
        m = QMenu(self._hero)
        m.setStyleSheet(f"QMenu {{ background: {theme.HOVER2}; color: {theme.TEXT}; border: 1px solid {theme.BORDER2}; border-radius: 8px; padding: 4px; }}"
                        f"QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}"
                        f"QMenu::item:selected {{ background: {theme.GREEN_DARK}; }}")
        a1 = m.addAction("  Open Pack Content")
        a1.triggered.connect(lambda: self.open_detail.emit(b.get("buildId")))
        a2 = m.addAction("  Repair Dependencies")
        a2.triggered.connect(lambda: self.open_detail.emit(b.get("buildId")))
        a3 = m.addAction("  Export Modpack")
        a3.triggered.connect(lambda: self.open_detail.emit(b.get("buildId")))
        a4 = m.addAction("  Rename Pack…")
        a4.triggered.connect(lambda: self.open_detail.emit(b.get("buildId")))
        m.exec(self._hero.mapToGlobal(self._hero.rect().bottomLeft()))

    def _render_recent(self) -> None:
        while self._recent_grid.count():
            item = self._recent_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for i, b in enumerate(self.builds[:3]):
            r = i // 3
            c = i % 3
            self._recent_grid.setColumnStretch(c, 1)
            self._recent_grid.addWidget(self._recent_card(b), r, c)

    def _recent_card(self, b: dict) -> QFrame:
        c = QFrame(self)
        c.setProperty("cls", "card-selected" if b.get("buildId") == self.selected_id else "card")
        c.setMinimumHeight(112)
        theme.polish(c)
        c.setCursor(Qt.CursorShape.PointingHandCursor)
        row = hbox(c, 14, margins=(16, 16, 16, 16))
        ic = QLabel(c)
        ic.setFixedSize(64, 64)
        url = b.get("iconUrl")
        ic.setPixmap(avatar(b.get("name") or "?", theme.GREEN, 64, 11))
        if url:
            from common import icon_cache
            icon_cache.request(url, ic, 64)
        row.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
        col = vbox(c, 2)
        t = label(c, b.get("name") or "Untitled", "h3")
        t.setWordWrap(True)
        col.addWidget(t)
        meta = label(c, f"{b.get('mcVersion') or ''} • {(b.get('loader') or '').capitalize()}", "mono")
        col.addWidget(meta)
        meta2 = label(c, f"{b.get('modCount', 0)} Mods • {fmt_ago(b.get('createdAt'))}", "muted")
        col.addWidget(meta2)
        row.addLayout(col, 1)
        play = icon_btn(c, "play", "Play instance", theme.GREEN)
        play.setProperty("cls", "iconbtn")
        play.setStyleSheet(f"QPushButton[cls=\"iconbtn\"] {{ background: {theme.HOVER}; border: 1px solid {theme.BORDER}; border-radius: 8px; padding: 8px; }}")
        play.clicked.connect(lambda: self.play_requested.emit(b.get("buildId")))
        row.addWidget(play, 0, Qt.AlignmentFlag.AlignVCenter)

        c.mousePressEvent = lambda e, bid=b.get("buildId"): self._card_clicked(e, bid)
        return c

    def _card_clicked(self, event, bid: str) -> None:
        self.selected_id = bid
        self.select_build.emit(bid)
        self._render()

    def _render_bottom(self, b: dict) -> None:
        clear_layout(self._bottom_lay)
        grid = self._bottom_lay

        # Hardware recommendation card
        hw = card(self._bottom)
        hwl = vbox(hw, 10, margins=(20, 18, 20, 18))
        row = QHBoxLayout()
        row.setSpacing(8)
        ic = QLabel(hw)
        ic.setPixmap(icon_pixmap("cpu", theme.GREEN, 18))
        row.addWidget(ic)
        row.addWidget(label(hw, "Recommended for Your Hardware", "h3"))
        row.addStretch(1)
        det = self.hardware or {}
        cpu = str(det.get("cpu") or "Unknown CPU")
        cpu_short = cpu.split(" with ", 1)[0]
        hw_summary = label(hw, f"{cpu_short} / {det.get('ramGB', '—')} GB RAM", "mono muted")
        hw_summary.setToolTip(f"{cpu} / {det.get('gpu', 'Unknown GPU')}")
        row.addWidget(hw_summary)
        hwl.addLayout(row)
        ram = det.get("ramGB")
        rec = (f"Detected {ram} GB RAM. AI Builder uses this profile to choose compatible performance mods, "
               "RAM allocation, shaders, and pack size.") if ram else (
               "Open Settings to detect your hardware before building an optimized pack.")
        rec_label = label(hw, rec, "sub")
        rec_label.setWordWrap(True)
        hwl.addWidget(rec_label)
        b1 = button(hw, "Build AI Optimized Pack", "btn-dark", "sparkles")
        b1.clicked.connect(lambda: self.navigate.emit("ai-builder"))
        hwl.addWidget(b1)

        # Updates card
        up = card(self._bottom)
        upl = vbox(up, 10, margins=(20, 18, 20, 18))
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        ic2 = QLabel(up)
        ic2.setPixmap(icon_pixmap("alert", theme.WARNING, 18))
        row2.addWidget(ic2)
        row2.addWidget(label(up, "Pack Status", "h3"))
        row2.addStretch(1)
        upl.addLayout(row2)
        status = b.get("launchPhase")
        if status:
            status_text = f"{b.get('name')} is {status} right now."
        else:
            status_text = (f"{b.get('name')} is idle. Latest test: "
                           f"{b.get('testStatus') or '—'} ({b.get('testLevel') or '—'}).")
        status_label = label(up, status_text, "sub")
        status_label.setWordWrap(True)
        upl.addWidget(status_label)
        b2 = button(up, "Open Pack Content", "btn-dark")
        b2.clicked.connect(lambda: self.open_detail.emit(b.get("buildId")))
        upl.addWidget(b2)

        grid.addWidget(hw, 0, 0)
        grid.addWidget(up, 0, 1)
