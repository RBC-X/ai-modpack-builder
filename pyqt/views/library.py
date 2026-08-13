"""Library view — instance cards with search/filter/sort, grid and list modes."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QLineEdit, QScrollArea, QVBoxLayout, QWidget)

import theme
from common import (avatar, button, card, clear_layout, fmt_ago, hbox, icon_btn,
                    icon_pixmap, label, pill, vbox)
from common import icon_cache

LOADERS = ["all", "Forge", "NeoForge", "Fabric", "Quilt", "Vanilla"]


class LibraryView(QWidget):
    play_requested = pyqtSignal(str)
    stop_requested = pyqtSignal(str)
    open_detail = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    import_requested = pyqtSignal()
    new_pack_requested = pyqtSignal()
    navigate_ai = pyqtSignal()
    select_build = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.builds: list[dict] = []
        self.selected_id: str | None = None
        self._view_mode = "grid"
        self._loader = "all"
        self._sort = "recent"

        outer = QScrollArea(self)
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.Shape.NoFrame)
        outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setProperty("page", "true")
        outer.setWidget(body)
        self.root = vbox(body, 24, margins=(32, 30, 32, 30))
        self.root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Header
        head = QHBoxLayout()
        head.setSpacing(12)
        col = vbox(body, 2)
        col.addWidget(label(body, "Instance Library", "h1"))
        col.addWidget(label(body, "Manage, configure, and launch your Minecraft modpack instances.", "sub"))
        head.addLayout(col, 1)
        ai = button(body, "BUILD WITH AI", "btn-primary", "sparkles")
        ai.clicked.connect(self.navigate_ai.emit)
        imp = button(body, "IMPORT PACK", "btn-dark", "folder")
        imp.clicked.connect(self.import_requested.emit)
        nw = button(body, "NEW PACK", "btn-dark", "plus")
        nw.clicked.connect(self.new_pack_requested.emit)
        nw.setToolTip("Build your own pack from scratch — pick version/loader/RAM, then fill it from the Mod Browser.")
        head.addWidget(ai)
        head.addWidget(imp)
        head.addWidget(nw)
        self.root.addLayout(head)

        # Filter bar
        bar = card(body)
        bl = hbox(bar, 8, margins=(14, 18, 14, 18))
        self._search = QLineEdit(bar)
        self._search.setPlaceholderText("Search instances...")
        self._search.setFixedWidth(320)
        self._search.textChanged.connect(lambda _: self._render())
        bl.addWidget(self._search)
        self._loader_pills: dict[str, QWidget] = {}
        for f in LOADERS:
            p = pill(bar, f, active=self._loader == f)
            p.clicked.connect(lambda _=False, f=f: self._set_loader(f))
            bl.addWidget(p)
            self._loader_pills[f] = p
        bl.addStretch(1)
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
        self._empty = label(body, "No instances match your filter.", "sub")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.root.addWidget(self._empty)

        # The original port created the scroll area but never placed it in the
        # page layout, leaving Library stuck at its 576 px size hint.
        lay = vbox(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(outer)

    # ------------------------------------------------------------------
    def _set_loader(self, loader: str) -> None:
        self._loader = loader
        self._render_pills()
        self._render()

    def _set_mode(self, mode: str) -> None:
        self._view_mode = mode
        self._render()

    def _on_sort(self, idx: int) -> None:
        self._sort = ["recent", "name", "mods"][idx]
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

    def _render(self) -> None:
        clear_layout(self._grid)
        items = self._filtered()
        self._empty.setVisible(not items)
        if self._view_mode == "grid":
            # Adaptive columns: squarer tiles on wide windows (4-up), fewer on
            # narrow ones. Target ~250 px per card so tiles read square.
            avail = max(200, self.width() - 64)
            cols = max(2, min(4, avail // 250))
            card_w = (avail - (cols - 1) * 16) // cols
            for col in range(cols):
                self._grid.setColumnStretch(col, 1)
            for i, b in enumerate(items):
                self._grid.addWidget(self._grid_card(b, card_w), i // cols, i % cols)
        else:
            for i, b in enumerate(items):
                self._grid.addWidget(self._list_card(b), i, 0)

    # ------------------------------------------------------------------
    def _grid_card(self, b: dict, card_w: int) -> QFrame:
        c = QFrame(self)
        c.setProperty("cls", "card-selected" if b.get("buildId") == self.selected_id else "card")
        c.setMinimumHeight(252)
        theme.polish(c)
        c.setCursor(Qt.CursorShape.PointingHandCursor)
        v = vbox(c, 0, margins=0)

        cover_url = b.get("coverUrl") or b.get("iconUrl")
        test_status = str(b.get("testStatus") or "Not tested")
        status_text = "Running" if b.get("running") else f"Test {test_status}"
        status_cls = "pill-danger" if test_status == "FAIL" and not b.get("running") else "pill"
        status_on = bool(b.get("running") or test_status in {"PASS", "FAIL"})

        # Banner band: the pack's own image fills the tile (CurseForge style),
        # with the status pill overlaid; packs without any image keep the
        # gradient artwork band with avatar + name exactly as before.
        artwork = QFrame(c)
        artwork.setProperty("cls", "artwork")
        artwork.setFixedHeight(132)
        theme.polish(artwork)
        if cover_url:
            grid = QGridLayout(artwork)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(0)
            img = QLabel(artwork)
            img.setPixmap(avatar(b.get("name") or "?", theme.GREEN, 132, 0))
            icon_cache.request(cover_url, img, box=(card_w - 2, 131))
            grid.addWidget(img, 0, 0)
            overlay = QWidget(artwork)
            ol = vbox(overlay, 0, margins=(12, 10, 12, 10))
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(pill(artwork, status_text, status_on, status_cls))
            ol.addLayout(row)
            grid.addWidget(overlay, 0, 0)
        else:
            av = vbox(artwork, 10, margins=(16, 14, 16, 14))
            status_row = QHBoxLayout()
            status_row.addWidget(label(artwork, f"Updated {fmt_ago(b.get('createdAt'))}", "muted"))
            status_row.addStretch(1)
            status_row.addWidget(pill(artwork, status_text, status_on, status_cls))
            av.addLayout(status_row)
            av.addStretch(1)
            top = QHBoxLayout()
            top.setSpacing(12)
            ic = QLabel(artwork)
            ic.setFixedSize(48, 48)
            url = b.get("iconUrl")
            ic.setPixmap(avatar(b.get("name") or "?", theme.GREEN, 48, 10))
            if url:
                icon_cache.request(url, ic, 48)
            top.addWidget(ic)
            col = QVBoxLayout()
            col.setSpacing(2)
            t = label(artwork, b.get("name") or "Untitled", "h2")
            t.setWordWrap(True)
            col.addWidget(t)
            col.addWidget(label(artwork, f"{b.get('mcVersion') or ''} • {(b.get('loader') or '').capitalize()}", "mono"))
            top.addLayout(col, 1)
            av.addLayout(top)
        v.addWidget(artwork)

        body = QWidget(c)
        bv = vbox(body, 8, margins=(14, 10, 14, 10))
        # Banner cards carry the name in the body; fallback cards already show
        # it inside the artwork band — never repeat it.
        if cover_url:
            t = label(body, b.get("name") or "Untitled", "h3")
            t.setWordWrap(True)
            bv.addWidget(t)
        else:
            desc = label(body, (b.get("description") or b.get("request") or ""), "sub")
            desc.setWordWrap(True)
            desc.setMaximumHeight(34)
            bv.addWidget(desc)

        meta = QHBoxLayout()
        meta.setSpacing(8)
        ic2 = QLabel(body)
        ic2.setPixmap(icon_pixmap("layers", theme.BLUE, 14))
        meta.addWidget(ic2)
        meta.addWidget(label(body, f"{b.get('modCount', 0)} Mods", "mono muted"))
        meta.addStretch(1)
        fit = str(b.get("hardwareFit") or "Not estimated")
        if fit.lower() in {"not estimated", "auto", ""}:
            fit_cls = "mono muted"
        else:
            fit_cls = "warn" if fit.lower() in {"heavy", "extreme"} else "mono green"
        fit_label = label(body, fit, fit_cls)
        fit_label.setToolTip(f"Hardware fit from this pack's performance estimate: {fit}")
        meta.addWidget(fit_label)
        bv.addLayout(meta)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        if b.get("running"):
            stop = button(body, "STOP", "btn-danger")
            stop.clicked.connect(lambda: self.stop_requested.emit(b.get("buildId")))
            actions.addWidget(stop, 1)
        else:
            play = button(body, "PLAY", "btn-primary", "play", theme.BG)
            play.clicked.connect(lambda: self.play_requested.emit(b.get("buildId")))
            actions.addWidget(play, 1)
        more = icon_btn(body, "more", "Manage content")
        more.setFixedSize(34, 34)
        more.clicked.connect(lambda: self.open_detail.emit(b.get("buildId")))
        actions.addWidget(more)
        trash = icon_btn(body, "trash", "Delete pack", theme.DANGER if not b.get("running") else theme.TEXT2)
        trash.setFixedSize(34, 34)
        trash.setEnabled(not b.get("running"))
        trash.clicked.connect(lambda: self.delete_requested.emit(b.get("buildId")))
        actions.addWidget(trash)
        bv.addLayout(actions)
        v.addWidget(body)

        c.mousePressEvent = lambda e, bid=b.get("buildId"): self._clicked(e, bid)
        return c

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
        return c

    def _clicked(self, event, bid: str) -> None:
        self.selected_id = bid
        self.select_build.emit(bid)
        self._render()
