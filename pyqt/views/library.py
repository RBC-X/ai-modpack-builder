"""Library view — instance cards with search/filter/sort, grid and list modes."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QLineEdit, QScrollArea, QVBoxLayout, QWidget)

import theme
from common import (avatar, button, card, clear_layout, fmt_ago, hbox, icon_btn,
                    label, pill, vbox)
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

    def _render(self) -> None:
        clear_layout(self._grid)
        items = self._filtered()
        self._empty.setVisible(not items)
        if self._view_mode == "grid":
            # Adaptive columns driven by the density preset: compact targets
            # ~205 px tiles (5-up on wide windows), cozy ~250 px (4-up).
            p = DENSITY_PARAMS[self._density]
            avail = max(200, self.width() - 64)
            cols = max(2, min(p["cols"], avail // p["target"]))
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
        return c

    def _clicked(self, event, bid: str) -> None:
        self.selected_id = bid
        self.select_build.emit(bid)
        self._render()
