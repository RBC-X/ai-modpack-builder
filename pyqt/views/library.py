"""Library view — instance cards with search/filter/sort, grid and list modes."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QLineEdit, QScrollArea, QSizePolicy, QVBoxLayout,
                             QWidget)

import theme
from common import (avatar, button, card, clear_layout, fmt_ago, hbox, icon_btn,
                    icon_cache, icon_pixmap, label, make_clickable, pill, vbox)
from views.misc import _load_state, _save_state
from views.packcard import DENSITY_PARAMS, build_pack_card

LOADERS = ["all", "Forge", "NeoForge", "Fabric", "Quilt", "Vanilla"]


class LibraryView(QWidget):
    play_requested = pyqtSignal(str)
    stop_requested = pyqtSignal(str)
    open_detail = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    import_requested = pyqtSignal()
    new_pack_requested = pyqtSignal()
    navigate_ai = pyqtSignal()
    navigate_discover = pyqtSignal()
    select_build = pyqtSignal(str)
    density_changed = pyqtSignal(str)     # 'cozy' | 'compact' (Home mirrors it)

    def __init__(self):
        super().__init__()
        self.builds: list[dict] = []
        self.selected_id: str | None = None
        self._view_mode = "grid"
        self._loader = "all"
        self._sort = "recent"
        # Grid density is a per-user preference, remembered in the UI state file.
        self._density = "compact" if str(_load_state().get("libraryDensity", "cozy")) == "compact" else "cozy"

        outer = QScrollArea(self)
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.Shape.NoFrame)
        outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setProperty("page", "true")
        outer.setWidget(body)
        self._scroll = outer
        self.root = vbox(body, 24, margins=(32, 30, 32, 30))
        self.root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Header: title + actions. On narrow viewports the actions wrap to a
        # second row instead of forcing the page wider than the viewport.
        self._head_row = QHBoxLayout()
        self._head_row.setSpacing(12)
        col = vbox(body, 2)
        col.addWidget(label(body, "Instance Library", "h1"))
        sub = label(body, "Manage, configure, and launch your Minecraft modpack instances.", "sub")
        sub.setWordWrap(True)
        col.addWidget(sub)
        self._head_row.addLayout(col, 1)
        ai = button(body, "BUILD WITH AI", "btn-primary", "sparkles")
        ai.clicked.connect(self.navigate_ai.emit)
        imp = button(body, "IMPORT PACK", "btn-dark", "folder")
        imp.clicked.connect(self.import_requested.emit)
        nw = button(body, "NEW PACK", "btn-dark", "plus")
        nw.clicked.connect(self.new_pack_requested.emit)
        nw.setToolTip("Build your own pack from scratch — pick version/loader/RAM, then fill it from the Mod Browser.")
        self._ai_btn, self._imp_btn, self._nw_btn = ai, imp, nw
        self._head_row.addWidget(ai)
        self._head_row.addWidget(imp)
        self._head_row.addWidget(nw)
        self.root.addLayout(self._head_row)
        # Wrapped-actions row (visible only when the header is too narrow):
        # same buttons, left-aligned under the title. A widget can live in
        # only one layout at a time, so _reflow_header moves them between rows.
        self._head_actions = QHBoxLayout()
        self._head_actions.setSpacing(10)
        self._head_actions.addWidget(ai)
        self._head_actions.addWidget(imp)
        self._head_actions.addWidget(nw)
        self._head_actions.addStretch(1)
        self.root.addLayout(self._head_actions)
        self._header_wide = True

        # Filter bar
        bar = card(body)
        bl = hbox(bar, 8, margins=(14, 18, 14, 18))
        self._search = QLineEdit(bar)
        self._search.setPlaceholderText("Search instances...")
        self._search.setMinimumWidth(140)
        self._search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._search.textChanged.connect(lambda _: self._render())
        bl.addWidget(self._search, 1)
        # Loader filter: shown as pills on wide windows, collapsed to a
        # dropdown on narrow ones (Issue 21 — the bar must not clip).
        self._loader_pills: dict[str, QWidget] = {}
        self._loader_row = QHBoxLayout()
        self._loader_row.setSpacing(8)
        for f in LOADERS:
            p = pill(bar, f, active=self._loader == f)
            p.clicked.connect(lambda _=False, f=f: self._set_loader(f))
            self._loader_row.addWidget(p)
            self._loader_pills[f] = p
        bl.addLayout(self._loader_row)
        self._loader_box = QComboBox(bar)
        self._loader_box.addItems(LOADERS)
        self._loader_box.setCurrentText(self._loader)
        self._loader_box.currentTextChanged.connect(self._set_loader)
        self._loader_box.setToolTip("Loader filter (collapsed on narrow windows)")
        self._loader_box.setVisible(False)
        bl.addWidget(self._loader_box)
        bl.addStretch(1)
        self._density_box = QComboBox(bar)
        self._density_box.addItems(["Cozy", "Compact"])
        self._density_box.setCurrentText("Compact" if self._density == "compact" else "Cozy")
        self._density_box.setToolTip("Grid density — Cozy (larger tiles, 4-up) or Compact (smaller tiles, 5-up). Remembered for this user.")
        self._density_box.currentTextChanged.connect(self._set_density)
        bl.addWidget(self._density_box)
        self._sort_box = QComboBox(bar)
        self._sort_box.addItems(["Newest Builds", "Name", "Mod Count"])
        self._sort_box.currentIndexChanged.connect(self._on_sort)
        bl.addWidget(self._sort_box)
        g = icon_btn(bar, "grid", "Grid view", theme.GREEN if self._view_mode == "grid" else theme.TEXT2)
        g.clicked.connect(lambda: self._set_mode("grid"))
        l = icon_btn(bar, "list", "List view", theme.GREEN if self._view_mode == "list" else theme.TEXT2)
        l.clicked.connect(lambda: self._set_mode("list"))
        bl.addWidget(g)
        bl.addWidget(l)
        self._view_btns = (g, l)
        self.root.addWidget(bar)

        self._grid = QGridLayout()
        self._grid.setSpacing(16)
        self.root.addLayout(self._grid)
        self._empty = QFrame(body)
        self._empty.setProperty("cls", "empty-state")
        self._empty.setMinimumHeight(258)
        theme.polish(self._empty)
        empty_lay = vbox(self._empty, 12, margins=(32, 30, 32, 30))
        empty_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_mark = QFrame(self._empty)
        empty_mark.setProperty("cls", "logo-badge")
        empty_mark.setFixedSize(52, 52)
        theme.polish(empty_mark)
        mark_lay = vbox(empty_mark, 0, margins=0)
        mark_icon = QLabel(empty_mark)
        mark_icon.setPixmap(icon_pixmap("package", theme.GREEN, 26))
        mark_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark_lay.addWidget(mark_icon)
        empty_lay.addWidget(empty_mark, 0, Qt.AlignmentFlag.AlignHCenter)
        self._empty_title = label(self._empty, "Your first modpack starts here", "h2")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lay.addWidget(self._empty_title)
        self._empty_desc = label(
            self._empty,
            "Describe an experience for the AI builder, import an existing pack, or browse real projects.",
            "sub",
        )
        self._empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_desc.setWordWrap(True)
        self._empty_desc.setMaximumWidth(620)
        empty_lay.addWidget(self._empty_desc)
        self._empty_actions = QWidget(self._empty)
        actions = hbox(self._empty_actions, 10, margins=0)
        build_empty = button(self._empty_actions, "BUILD WITH AI", "btn-primary", "sparkles")
        build_empty.clicked.connect(self.navigate_ai.emit)
        actions.addWidget(build_empty)
        import_empty = button(self._empty_actions, "IMPORT PACK", "btn-dark", "folder")
        import_empty.clicked.connect(self.import_requested.emit)
        actions.addWidget(import_empty)
        discover_empty = button(self._empty_actions, "BROWSE PROJECTS", "btn-dark", "compass")
        discover_empty.clicked.connect(self.navigate_discover.emit)
        actions.addWidget(discover_empty)
        empty_lay.addWidget(self._empty_actions, 0, Qt.AlignmentFlag.AlignHCenter)
        self._empty_clear = button(self._empty, "CLEAR FILTERS", "btn-dark", "refresh")
        self._empty_clear.clicked.connect(self._clear_filters)
        self._empty_clear.setVisible(False)
        empty_lay.addWidget(self._empty_clear, 0, Qt.AlignmentFlag.AlignHCenter)
        self.root.addWidget(self._empty)
        self._last_cols: int | None = None
        self._last_card_w: int | None = None
        self._last_avail: int | None = None
        self._settle_passes = 0
        self._pills_wide = True
        self._reflow_armed = False
        self._update_filter_layout()

        # The original port created the scroll area but never placed it in the
        # page layout, leaving Library stuck at its 576 px size hint.
        lay = vbox(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(outer)

    def _arm_reflow(self) -> None:
        """Defer one reflow pass to the next event-loop iteration. Both
        resize and show can change the scroll viewport AFTER the event returns
        (a vertical scrollbar appears once content overflows, narrowing the
        usable width), so measuring synchronously can compute tiles from a
        stale width."""
        if not hasattr(self, "_reflow_armed"):
            return
        if not self._reflow_armed:
            self._reflow_armed = True
            QTimer.singleShot(0, self._reflow_later)

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Debounced reflow, deferred to the next event-loop pass: mid-resize
        the scroll viewport can still report its PREVIOUS width, so measuring
        it synchronously and re-rendering right away can both miss a change
        and recompute fixed-width tiles from a stale width. Deferring lets the
        layout settle first, then re-measures and re-renders only when the
        column count or the computed card width actually changed."""
        super().resizeEvent(event)
        self._arm_reflow()

    def showEvent(self, event) -> None:  # noqa: N802
        """Re-measure when the page becomes visible: the previous render may
        have been computed before THIS page's scrollbar appeared or the
        sidebar state changed, leaving stale fixed-width tiles."""
        super().showEvent(event)
        self._arm_reflow()

    def _reflow_later(self) -> None:
        self._reflow_armed = False
        self._update_filter_layout()
        self._reflow_header(self._usable() >= 920)
        if self._view_mode != "grid":
            return
        avail = self._usable()
        cols = self._grid_cols()
        card_w = self._card_width(cols)
        # Re-render whenever the available width changed AT ALL (not just on a
        # column-count change): the vertical scrollbar can appear between
        # layout passes and narrow the viewport by a few pixels, and a stale
        # tile width that wide overflows the body. A bounded settle loop
        # re-measures once more after a change so the final pass reads the
        # fully settled viewport.
        avail_changed = avail != self._last_avail
        self._last_avail = avail
        width_changed = card_w != self._last_card_w
        if cols != self._last_cols or width_changed:
            self._last_cols = cols
            self._last_card_w = card_w
            self._render()
        if avail_changed and self._settle_passes < 3:
            self._settle_passes += 1
            self._reflow_armed = True
            QTimer.singleShot(0, self._reflow_later)
        else:
            self._settle_passes = 0

    def _usable(self) -> int:
        """Available content width, minus page margins and a reservation for
        the vertical scrollbar.

        A populated grid is always taller than the viewport, so the vertical
        scrollbar appears — AFTER the first layout pass — and narrows the
        scroll viewport by its extent. Reading the viewport width therefore
        races the scrollbar: tiles rendered from the pre-scrollbar width come
        out a few pixels too wide and the body clips. The view's own width
        is stable across scrollbar appearance, so subtracting the scrollbar
        extent up front makes the tile math deterministic: the rendered grid
        fits with or without a scrollbar present, with no oscillation."""
        width = self.width()
        if width <= 0 and self._scroll is not None:
            width = self._scroll.viewport().width()
        sb = 15
        if self._scroll is not None:
            sb = self._scroll.verticalScrollBar().sizeHint().width()
            sb = max(12, min(24, sb))
        return max(200, width - sb - 64)

    def _grid_cols(self) -> int:
        p = DENSITY_PARAMS[self._density]
        avail = self._usable()
        return max(1, min(p["cols"], avail // p["target"]))

    def _reflow_header(self, wide: bool) -> None:
        """Header actions sit beside the title on wide windows and wrap onto
        their own left-aligned row on narrow ones, so the header never forces
        the page wider than the viewport."""
        if wide == self._header_wide:
            return
        self._header_wide = wide
        buttons = (self._ai_btn, self._imp_btn, self._nw_btn)
        if wide:
            for w in buttons:
                self._head_actions.removeWidget(w)
            for w in buttons:
                self._head_row.addWidget(w)
        else:
            for w in buttons:
                self._head_row.removeWidget(w)
            for w in buttons:
                self._head_actions.addWidget(w)

    def _update_filter_layout(self) -> None:
        """Pills on wide windows, loader dropdown on narrow ones."""
        wide = self.width() >= 1120
        if wide == self._pills_wide:
            return
        self._pills_wide = wide
        for p in self._loader_pills.values():
            p.setVisible(wide)
        self._loader_box.setVisible(not wide)
        # Keep the dropdown in sync with the current loader filter.
        self._loader_box.setCurrentText(self._loader)

    # ------------------------------------------------------------------
    def _set_loader(self, loader: str) -> None:
        self._loader = loader
        self._render_pills()
        self._render()

    def _clear_filters(self) -> None:
        """Restore the complete Library after a zero-result search/filter."""
        self._search.clear()
        self._loader = "all"
        self._loader_box.setCurrentText("all")
        self._render_pills()
        self._render()

    def _set_mode(self, mode: str) -> None:
        self._view_mode = mode
        self._render()

    def _on_sort(self, idx: int) -> None:
        self._sort = ["recent", "name", "mods"][idx]
        self._render()

    def _set_density(self, text: str) -> None:
        """Switch grid density, persist it per user, and mirror it to Home so
        both surfaces stay visually consistent immediately."""
        density = "compact" if text == "Compact" else "cozy"
        if density == self._density:
            return
        self._density = density
        st = _load_state()
        st["libraryDensity"] = density
        _save_state(st)
        self.density_changed.emit(density)
        self._render()

    def _render_pills(self) -> None:
        for loader, control in self._loader_pills.items():
            control.setProperty("active", "true" if loader == self._loader else "false")
            theme.polish(control)

    # ------------------------------------------------------------------
    def set_builds(self, builds: list[dict]) -> None:
        self.builds = builds
        ids = {b.get("buildId") for b in builds}
        if self.selected_id not in ids:
            self.selected_id = builds[0].get("buildId") if builds else None
        self._render()

    def selected(self) -> dict | None:
        for b in self.builds:
            if b.get("buildId") == self.selected_id:
                return b
        return self.builds[0] if self.builds else None

    def _filtered(self) -> list[dict]:
        q = self._search.text().strip().lower()
        out = []
        for b in self.builds:
            name = (b.get("name") or "").lower()
            req = (b.get("request") or "").lower()
            if q and q not in name and q not in req:
                continue
            loader = (b.get("loader") or "").lower()
            if self._loader != "all" and loader != self._loader.lower():
                continue
            out.append(b)
        if self._sort == "name":
            out.sort(key=lambda b: (b.get("name") or "").lower())
        elif self._sort == "mods":
            out.sort(key=lambda b: b.get("modCount") or 0, reverse=True)
        else:
            out.sort(key=lambda b: b.get("createdAt") or "", reverse=True)
        return out

    def _card_width(self, cols: int) -> int:
        avail = self._usable()
        return (avail - (cols - 1) * 16) // cols

    def _render(self) -> None:
        clear_layout(self._grid)
        items = self._filtered()
        self._empty.setVisible(not items)
        if not items:
            truly_empty = not self.builds
            self._empty_title.setText(
                "Your first modpack starts here" if truly_empty else "No instances match these filters"
            )
            self._empty_desc.setText(
                "Describe an experience for the AI builder, import an existing pack, or browse real projects."
                if truly_empty else
                "Try a different search or loader. Your existing instances are still safely stored."
            )
            self._empty_actions.setVisible(truly_empty)
            self._empty_clear.setVisible(not truly_empty)
        if self._view_mode == "grid":
            # Adaptive columns driven by the density preset: compact targets
            # ~205 px tiles (5-up on wide windows), cozy ~250 px (4-up). The
            # available width comes from the real scroll viewport so the grid
            # never overflows when a vertical scrollbar appears.
            cols = self._grid_cols()
            self._last_cols = cols
            card_w = self._card_width(cols)
            self._last_card_w = card_w
            for col in range(cols):
                self._grid.setColumnStretch(col, 1)
            for i, b in enumerate(items):
                self._grid.addWidget(self._grid_card(b, card_w), i // cols, i % cols)
        else:
            for i, b in enumerate(items):
                self._grid.addWidget(self._list_card(b), i, 0)

    # ------------------------------------------------------------------
    def _grid_card(self, b: dict, card_w: int) -> QFrame:
        """Square tile with cover artwork — shared with the Home recent row so
        both surfaces stay visually identical (see views/packcard.py)."""
        return build_pack_card(
            self, b, card_w,
            density=self._density,
            selected=b.get("buildId") == self.selected_id,
            on_click=lambda e, bid=b.get("buildId"): self._clicked(e, bid),
            on_play=lambda bid=b.get("buildId"): self.play_requested.emit(bid),
            on_stop=lambda bid=b.get("buildId"): self.stop_requested.emit(bid),
            on_open=lambda bid=b.get("buildId"): self.open_detail.emit(bid),
            on_delete=lambda bid=b.get("buildId"): self.delete_requested.emit(bid),
        )

    def _list_card(self, b: dict) -> QFrame:
        c = QFrame(self)
        c.setProperty("cls", "row")
        theme.polish(c)
        row = hbox(c, 14, margins=(14, 12, 14, 12))
        ic = QLabel(c)
        ic.setFixedSize(44, 44)
        url = b.get("iconUrl")
        ic.setPixmap(avatar(b.get("name") or "?", theme.GREEN, 44, 8))
        if url:
            icon_cache.request(url, ic, 44)
        row.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
        col = vbox(c, 2)
        t = label(c, b.get("name") or "Untitled", "h3")
        col.addWidget(t)
        col.addWidget(label(c, f"MC {b.get('mcVersion') or ''} • {(b.get('loader') or '').capitalize()} • {b.get('modCount', 0)} Mods • {fmt_ago(b.get('createdAt'))}", "mono"))
        row.addLayout(col, 1)
        manage = button(c, "Manage", "btn-dark")
        manage.clicked.connect(lambda: self.open_detail.emit(b.get("buildId")))
        row.addWidget(manage)
        if b.get("running"):
            stop = button(c, "STOP", "btn-danger")
            stop.clicked.connect(lambda: self.stop_requested.emit(b.get("buildId")))
            row.addWidget(stop)
        else:
            play = button(c, "PLAY", "btn-primary", "play", theme.BG)
            play.clicked.connect(lambda: self.play_requested.emit(b.get("buildId")))
            row.addWidget(play)
        if b.get("running"):
            trash = icon_btn(c, "trash", "Stop the pack before deleting", theme.TEXT2)
        else:
            trash = icon_btn(c, "trash", "Delete pack", theme.DANGER)
        trash.setFixedSize(36, 36)
        trash.setEnabled(not b.get("running"))
        trash.clicked.connect(lambda: self.delete_requested.emit(b.get("buildId")))
        row.addWidget(trash)
        c.mousePressEvent = lambda e, bid=b.get("buildId"): self._clicked(e, bid)
        make_clickable(c, lambda: self._clicked(None, b.get("buildId")),
                       name=f"Select {b.get('name') or 'pack'}")
        return c

    def _clicked(self, event, bid: str) -> None:
        self.selected_id = bid
        self.select_build.emit(bid)
        self._render()
