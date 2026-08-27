"""Production content browser backed by the real Modrinth + CurseForge APIs.

The page supports popularity browsing, debounced/stale-safe search, provider,
content, loader and Minecraft filters, provider-hosted imagery, compatible
version selection, and real add/import actions against a chosen pack.
"""
from __future__ import annotations

import math
import time
from collections import OrderedDict

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                             QLineEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

import theme
from common import (avatar, button, card, clear_layout, fmt_ago, fmt_downloads,
                    hbox, icon_btn, icon_pixmap, label, make_clickable, pill,
                    run_async, vbox)
from common import icon_cache
from icons import icon
from views.misc import _load_state, _save_state

PAGE_SIZE_CHOICES = [24, 48, 96]

# A provider can answer 200 with an empty result set during a momentary
# catalog/network blip (no hits, no error). Bounded retries with backoff
# recover those; real failures raise or carry `error` and return at once.
RETRY_EMPTY_ATTEMPTS = 3
RETRY_BACKOFF_MS = 500


TYPES = [
    ("mod", "Mods"),
    ("modpack", "Modpacks"),
    ("shader", "Shaders"),
    ("resourcepack", "Resource packs"),
    ("world", "Worlds"),
    ("all", "All content"),
]
PROVIDERS = [("all", "All sources"), ("modrinth", "Modrinth"), ("curseforge", "CurseForge")]
LOADERS = ["all", "fabric", "forge", "neoforge", "quilt"]
VERSIONS = ["auto", "1.21.1", "1.20.6", "1.20.4", "1.20.1", "1.19.2"]


class DiscoverView(QWidget):
    add_mod = pyqtSignal(str, str, str, object, object)  # build, provider, project, version, type
    import_pack = pyqtSignal(str, str)
    open_settings = pyqtSignal()
    search_retry = pyqtSignal(int)  # attempt number (1-based) of a retry

    def __init__(self, api):
        super().__init__()
        self.api = api
        self.builds: list[dict] = []
        self._type = "mod"
        self._provider = "all"
        self._loader = "all"
        self._version = "auto"
        # Page memory per browsing context: "returning to Discover restores
        # where you were" — the last page for each (content type, provider,
        # loader, MC version, page size) combination is remembered across tab
        # switches and app restarts (persisted in the UI state file).
        self._base_page_size = 48
        self._page_size = 48  # effective size from the last result (merged = sum)
        self._remembered = self._load_remembered()
        self._sorts = self._load_sorts()
        self._sort = self._sorts.get(self._type, "downloads")
        self._page = int(self._remembered.get(self._ctx_key(), 0) or 0)
        self._more = False
        self._total = 0
        self._hits: list[dict] = []
        self._selected: dict | None = None
        self._drawer: QFrame | None = None
        self._target_id: str | None = None
        self._search_serial = 0
        # A provider blip recovered by the bounded retry is surfaced in the
        # status line (the search runs off-thread, so a queued signal carries
        # the notice back to the main thread).
        self.search_retry.connect(self._on_search_retry)
        self._drawer_serial = 0
        self._detail_serial = 0
        self._last_columns = 3
        self._cache: OrderedDict[tuple, dict] = OrderedDict()

        outer = QScrollArea(self)
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.Shape.NoFrame)
        outer.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setProperty("page", "true")
        outer.setWidget(body)
        self._scroll = outer
        self.root = vbox(body, 22, margins=(32, 30, 32, 32))
        self.root.setAlignment(Qt.AlignmentFlag.AlignTop)

        heading = QWidget(body)
        heading_lay = hbox(heading, 12, margins=0)
        heading_col = vbox(heading, 1)
        # Kept as attributes: scoped subclasses (Add Content) retitle the page
        # and prepend controls (a back button) into the same heading row.
        self.heading_row = heading
        self._heading_col = heading_col
        self._heading_title = label(heading, "Discover content", "h1")
        self._heading_sub = label(
            heading,
            "Browse real projects, inspect their artwork and compatibility, then add them to a pack.",
            "small",
        )
        # Single-line QLabels carry their full text as the layout minimum —
        # without wrapping, this heading alone forced a ~1244 px page minimum
        # and hid ~450 px of controls at the app's minimum window width.
        self._heading_sub.setWordWrap(True)
        heading_col.addWidget(self._heading_title)
        heading_col.addWidget(self._heading_sub)
        heading_lay.addLayout(heading_col, 1)
        self._catalog_badge = pill(heading, "Live catalogs", True, "pill", "wifi", theme.GREEN)
        self._catalog_badge.setToolTip("Results come from the live provider APIs or their verified local cache.")
        heading_lay.addWidget(self._catalog_badge, 0, Qt.AlignmentFlag.AlignTop)
        self.root.addWidget(heading)

        controls = card(body)
        controls.setProperty("cls", "search-panel")
        theme.polish(controls)
        controls_lay = vbox(controls, 14, margins=(16, 15, 16, 15))

        search_row = QHBoxLayout()
        search_row.setSpacing(10)
        self._search = QLineEdit(controls)
        self._search.setPlaceholderText("Search for a mod, shader, resource pack, or modpack…")
        self._search.addAction(icon("search", theme.MUTED, 17), QLineEdit.ActionPosition.LeadingPosition)
        self._search.setMinimumHeight(42)
        self._search.setClearButtonEnabled(True)
        search_row.addWidget(self._search, 1)
        self._provider_btns: dict[str, object] = {}
        for provider_id, provider_label in PROVIDERS:
            source_btn = pill(controls, provider_label, provider_id == self._provider, "source-pill")
            source_btn.setProperty("provider", provider_id)
            source_btn.clicked.connect(lambda _=False, p=provider_id: self._set_provider(p))
            theme.polish(source_btn)
            search_row.addWidget(source_btn)
            self._provider_btns[provider_id] = source_btn
        controls_lay.addLayout(search_row)

        # Filter rows: content-type pills on one line, the loader/version/
        # page-size/sort dropdowns on the second — the same two-tier filter
        # layout the reference launchers (CurseForge / Modrinth) use. A single
        # non-wrapping row of six pills plus four fixed-width combos was ~1160
        # px of minimum width, which overflowed every window below ~1400 px.
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self._type_btns: dict[str, object] = {}
        for type_id, type_label in TYPES:
            type_btn = pill(controls, type_label, type_id == self._type)
            type_btn.clicked.connect(lambda _=False, t=type_id: self._set_type(t))
            filter_row.addWidget(type_btn)
            self._type_btns[type_id] = type_btn
        filter_row.addStretch(1)
        controls_lay.addLayout(filter_row)

        combo_row = QHBoxLayout()
        combo_row.setSpacing(8)
        self._loader_box = QComboBox(controls)
        self._loader_box.addItems(["All loaders", "Fabric", "Forge", "NeoForge", "Quilt"])
        self._loader_box.setMinimumWidth(126)
        self._loader_box.currentIndexChanged.connect(self._on_filter)
        combo_row.addWidget(self._loader_box)
        self._ver_box = QComboBox(controls)
        self._ver_box.addItems(["All MC versions"] + VERSIONS[1:])
        self._ver_box.setMinimumWidth(144)
        self._ver_box.currentIndexChanged.connect(self._on_filter)
        combo_row.addWidget(self._ver_box)
        self._page_size_box = QComboBox(controls)
        self._page_size_box.addItems([f"{n} per page" for n in PAGE_SIZE_CHOICES])
        self._page_size_box.setCurrentIndex(PAGE_SIZE_CHOICES.index(self._base_page_size))
        self._page_size_box.setMinimumWidth(120)
        self._page_size_box.setToolTip(
            "Results per page. CurseForge caps pages at 50; Modrinth returns more, "
            "so merged pages combine each source's own limit.")
        self._page_size_box.currentIndexChanged.connect(self._on_page_size)
        combo_row.addWidget(self._page_size_box)
        # Sort picker: downloads / recently updated / name (per content type).
        self._sort_box = QComboBox(controls)
        self._sort_box.addItems(["Most downloaded", "Recently updated", "Name (A–Z)"])
        self._sort_box.setCurrentText({"downloads": "Most downloaded",
                                       "updated": "Recently updated",
                                       "name": "Name (A–Z)"}.get(self._sort, "Most downloaded"))
        self._sort_box.setMinimumWidth(160)
        self._sort_box.setToolTip(
            "Sort order for this content type. Modrinth name-sorts client-side "
            "(no server-side title index); CurseForge uses its native sort fields.")
        self._sort_box.currentIndexChanged.connect(self._on_sort)
        combo_row.addWidget(self._sort_box)
        combo_row.addStretch(1)
        controls_lay.addLayout(combo_row)
        self.root.addWidget(controls)

        self._result_bar = QFrame(body)
        self._result_bar.setProperty("cls", "status-banner")
        theme.polish(self._result_bar)
        result_lay = hbox(self._result_bar, 10, margins=(13, 9, 13, 9))
        self._status_icon = QLabel(self._result_bar)
        self._status_icon.setPixmap(icon_pixmap("refresh", theme.BLUE, 15))
        result_lay.addWidget(self._status_icon)
        self._status = label(self._result_bar, "Loading live catalogs…", "small")
        self._status.setWordWrap(True)
        result_lay.addWidget(self._status, 1)
        self._setup_btn = button(self._result_bar, "Set up CurseForge", "ghost", "key", theme.CURSEFORGE)
        self._setup_btn.clicked.connect(self.open_settings.emit)
        self._setup_btn.hide()
        result_lay.addWidget(self._setup_btn)
        self.root.addWidget(self._result_bar)

        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(16)
        self.root.addLayout(self._grid)

        # Pagination: next/prev across provider results. Always visible; the
        # Next button enables only when a full page came back (more may exist),
        # and resets to page 0 on any new search/filter change. Kept compact:
        # this row is the widest fixed-minimum element on the page, and every
        # pixel of slack keeps zero hidden overflow at the smallest window.
        pager = card(body)
        pager_lay = hbox(pager, 8, margins=(14, 9, 14, 9))
        self._pager_status = label(pager, "Page 1", "muted")
        pager_lay.addWidget(self._pager_status)
        # Results-count + "more may exist" hint: explains exactly why the Next
        # button is disabled on a short final page (no more pages) vs enabled
        # (a full page came back — more results may exist).
        self._more_hint = label(pager, "", "small")
        pager_lay.addWidget(self._more_hint)
        pager_lay.addStretch(1)
        # Jump-to-page: a spin box that skips straight to any page of a large
        # catalog (total ÷ page size), applying immediately on arrows/Enter.
        # Disabled while the real total is unknown — we never guess.
        # The jump control explains itself via its tooltip (a separate
        # "Jump to" label cost ~94 px of always-on minimum width).
        self._jump_spin = QSpinBox(pager)
        self._jump_spin.setRange(1, 1)
        self._jump_spin.setMinimumWidth(92)
        self._jump_spin.setKeyboardTracking(False)
        self._jump_spin.setToolTip(
            "Skip to any page (arrows or Enter apply immediately). "
            "The total comes from the provider catalog.")
        self._jump_spin.valueChanged.connect(self._on_jump_edit)
        pager_lay.addWidget(self._jump_spin)
        self._prev_btn = button(pager, "← Prev", "btn-dark", "arrowleft")
        self._prev_btn.setEnabled(False)
        self._prev_btn.clicked.connect(self._go_prev)
        pager_lay.addWidget(self._prev_btn)
        self._next_btn = button(pager, "Next →", "btn-primary", "arrowright", theme.BG)
        self._next_btn.setEnabled(False)
        self._next_btn.clicked.connect(self._go_next)
        pager_lay.addWidget(self._next_btn)
        self.root.addWidget(pager)
        self._updating_jump = False

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(280)
        self._debounce.timeout.connect(self._search_now)
        self._search.textChanged.connect(self._reset_page_on_search)

        page_lay = vbox(self)
        page_lay.setContentsMargins(0, 0, 0, 0)
        page_lay.addWidget(outer)

    # ------------------------------------------------------------------
    def set_builds(self, builds: list[dict]) -> None:
        self.builds = builds
        ids = {build.get("buildId") for build in builds}
        if self._target_id not in ids:
            self._target_id = builds[0].get("buildId") if builds else None

    def invalidate_cache(self) -> None:
        """Refresh provider configuration and results after Settings changes."""
        self._cache.clear()
        if self.isVisible():
            self._search_now()

    @staticmethod
    def _load_sorts() -> dict:
        """Last chosen sort per content type (persisted in the UI state file)."""
        raw = _load_state().get("discoverSorts") or {}
        return {str(k): str(v) for k, v in raw.items()}

    def _remember_sort(self) -> None:
        if self._sorts.get(self._type) == self._sort:
            return
        self._sorts[self._type] = self._sort
        st = _load_state()
        st["discoverSorts"] = dict(self._sorts)
        _save_state(st)

    @staticmethod
    def _load_remembered() -> dict:
        """Load remembered pages, migrating legacy type-only keys ("mod")
        to the full context form ("mod|all|all|auto|48")."""
        raw = _load_state().get("discoverPages") or {}
        remembered: dict = {}
        for key, value in raw.items():
            if "|" in str(key):
                remembered[str(key)] = int(value or 0)
            else:
                remembered[f"{key}|all|all|auto|48"] = int(value or 0)
        return remembered

    def _ctx_key(self, content_type: str = None, provider: str = None,
                 loader: str = None, version: str = None, sort: str = None) -> str:
        """The exact browsing context (content type + provider + loader + MC
        version + page size + sort) that owns a remembered page."""
        return "|".join([
            content_type or self._type, provider or self._provider,
            loader or self._loader, version or self._version,
            str(self._base_page_size), sort or self._sort,
        ])

    def _remember_page(self) -> None:
        """Persist the current page for the current browsing context (no-op
        when unchanged, so the per-keystroke search reset doesn't churn disk)."""
        key = self._ctx_key()
        if self._remembered.get(key) == self._page:
            return
        self._remembered[key] = self._page
        st = _load_state()
        st["discoverPages"] = dict(self._remembered)
        _save_state(st)

    def _on_sort(self) -> None:
        """Change the sort for the current content type; remember it per type
        and re-run the search from page 0 (a different order re-ranks the
        whole catalog, so the old page position is meaningless)."""
        text = self._sort_box.currentText()
        new_sort = {"Most downloaded": "downloads",
                    "Recently updated": "updated",
                    "Name (A–Z)": "name"}.get(text, "downloads")
        if new_sort == self._sort:
            return
        self._sort = new_sort
        self._remember_sort()
        self._page = 0
        self._remember_page()
        self._search_now()

    def _set_provider(self, provider: str) -> None:
        self._remember_page()
        self._provider = provider
        self._page = int(self._remembered.get(self._ctx_key(), 0) or 0)
        for provider_id, control in self._provider_btns.items():
            control.setProperty("active", "true" if provider_id == provider else "false")
            theme.polish(control)
        self._search_now()

    def _set_type(self, content_type: str) -> None:
        self._remember_page()
        self._remember_sort()
        self._type = content_type
        self._sort = self._sorts.get(content_type, "downloads")
        self._sort_box.setCurrentText({"downloads": "Most downloaded",
                                       "updated": "Recently updated",
                                       "name": "Name (A–Z)"}.get(self._sort, "Most downloaded"))
        self._page = int(self._remembered.get(self._ctx_key(), 0) or 0)
        for type_id, control in self._type_btns.items():
            control.setProperty("active", "true" if type_id == content_type else "false")
            theme.polish(control)
        # Loader filters do not apply to visual content or worlds; retain the
        # user's choice, but make the disabled state explicit.
        self._loader_box.setEnabled(content_type in ("mod", "modpack", "all"))
        self._search_now()

    def _on_filter(self, _idx: int) -> None:
        self._remember_page()
        self._loader = LOADERS[self._loader_box.currentIndex()]
        # Version combos carry data values in scoped subclasses (a pack's MC
        # version may sit outside the global list); plain Discover entries
        # have no userData, so fall back to the positional mapping.
        data = self._ver_box.currentData()
        self._version = data if data is not None else VERSIONS[self._ver_box.currentIndex()]
        self._page = int(self._remembered.get(self._ctx_key(), 0) or 0)
        self._search_now()

    def _on_page_size(self, _idx: int) -> None:
        """Per-provider page-size control: CurseForge caps at 50, Modrinth
        returns more — the engine merges each source's own page size. A
        changed page size is a NEW browsing context, so it starts at page 1
        without clobbering the remembered page of the old context."""
        self._remember_page()
        self._base_page_size = PAGE_SIZE_CHOICES[self._page_size_box.currentIndex()]
        self._page = 0
        self._remember_page()
        self._search_now()

    def _go_next(self) -> None:
        if self._hits and self._more:
            self._page += 1
            self._remember_page()
            self._search_now()

    def _go_prev(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._remember_page()
            self._search_now()

    def _reset_page_on_search(self, _text: str) -> None:
        if self._page != 0:
            self._page = 0
            self._remember_page()

    def showEvent(self, event) -> None:  # noqa: N802
        if event is not None:
            super().showEvent(event)
        if not self._hits:
            self._search_now()

    # ------------------------------------------------------------------
    def _search_key(self) -> tuple:
        return (self._search.text().strip().lower(), self._provider, self._type,
                self._version, self._loader, self._page, self._base_page_size, self._sort)

    def _search_now(self) -> None:
        query = self._search.text().strip()
        cache_key = self._search_key()
        self._search_serial += 1
        serial = self._search_serial

        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            self._apply_results(query, cached, cached=True)
            return

        self._show_loading()

        def fetch():
            result = None
            for attempt in range(RETRY_EMPTY_ATTEMPTS):
                result = self.api.search(q=query, provider=self._provider, mc=self._version,
                                         loader=self._loader, type=self._type,
                                         offset=self._page * self._page_size,
                                         page_size=self._base_page_size, sort=self._sort)
                if result.get("hits") or result.get("error"):
                    return result
                if attempt < RETRY_EMPTY_ATTEMPTS - 1:
                    self.search_retry.emit(attempt + 1)
                    time.sleep(RETRY_BACKOFF_MS * (attempt + 1) / 1000.0)
            return result

        def ok(result):
            if serial != self._search_serial:
                return
            self._cache[cache_key] = result
            self._cache.move_to_end(cache_key)
            while len(self._cache) > 32:
                self._cache.popitem(last=False)
            self._apply_results(query, result)

        def err(error):
            if serial != self._search_serial:
                return
            self._hits = []
            self._status_icon.setPixmap(icon_pixmap("alert", theme.DANGER, 15))
            self._status.setText(str(error))
            self._setup_btn.setVisible("curseforge" in str(error).lower() and "key" in str(error).lower())
            self._render_grid()

        run_async(fetch, ok, err)

    def _show_loading(self) -> None:
        self._status_icon.setPixmap(icon_pixmap("refresh", theme.BLUE, 15))
        source = "both catalogs" if self._provider == "all" else self._provider.capitalize()
        self._status.setText(f"Searching {source} with the selected compatibility filters…")
        self._setup_btn.hide()

    def _on_search_retry(self, attempt: int) -> None:
        """A provider answered 200 with an empty result set; tell the user the
        search is retrying rather than silently waiting out the backoff."""
        source = "both catalogs" if self._provider == "all" else self._provider.capitalize()
        self._status_icon.setPixmap(icon_pixmap("refresh", theme.WARNING, 15))
        self._status.setText(
            f"Searching {source} — no results yet, retrying (attempt {attempt + 1} of "
            f"{RETRY_EMPTY_ATTEMPTS})…"
        )
        clear_layout(self._grid)
        columns = self._column_count()
        for col in range(columns):
            self._grid.setColumnStretch(col, 1)
        for index in range(columns * 2):
            self._grid.addWidget(self._skeleton_card(), index // columns, index % columns)

    def _apply_results(self, query: str, result: dict, cached: bool = False) -> None:
        self._hits = result.get("hits") or []
        # Effective page size comes from the engine (merged = sum of per-source
        # sizes; single source = that source's clamped size) — label math and
        # the "more may exist" hint both depend on it.
        self._page_size = int(result.get("page_size") or self._page_size)
        self._more = bool(result.get("more"))
        self._total = int(result.get("total") or 0)
        sources = result.get("sources") or []
        key_needed = any(
            source.get("provider") == "curseforge"
            and not source.get("available")
            and "key" in str(source.get("error") or "").lower()
            for source in sources
        )
        self._setup_btn.setVisible(key_needed)

        source_parts = []
        for source in sources:
            name = "CurseForge" if source.get("provider") == "curseforge" else "Modrinth"
            if source.get("ok"):
                source_parts.append(f"{name} {source.get('count', 0)}")
            elif source.get("available"):
                source_parts.append(f"{name} unavailable")
            else:
                source_parts.append(f"{name} not configured")
        source_summary = " · ".join(source_parts)
        if result.get("browse"):
            lead = f"Popular {self._type.replace('resourcepack', 'resource pack')} content"
        else:
            lead = f"{len(self._hits)} results for “{query}”"
        if not self._hits and result.get("error"):
            lead = str(result.get("error"))
        cache_note = " · instant cache" if cached else ""
        self._status.setText(f"{lead} · {source_summary}{cache_note}".strip(" ·"))
        self._update_pager()
        self._status_icon.setPixmap(icon_pixmap(
            "checkcircle" if self._hits else "alert",
            theme.GREEN if self._hits else theme.WARNING,
            15,
        ))
        self._render_grid()

    def _usable(self) -> int:
        """Available content width from the SCROLL VIEWPORT (minus page
        margins), so the grid reflows against the width the user can actually
        see rather than the widget's nominal size."""
        vp = self._scroll.viewport().width() if self._scroll else self.width()
        return max(320, vp - 64)

    def _column_count(self) -> int:
        """Grid columns from the real viewport. Thresholds respect the real
        per-card layout minimum (~380 px: image + title block + action row),
        so N columns can never demand more width than the viewport has —
        previously fixed breakpoints let 2–3 columns force hidden horizontal
        overflow at the app's minimum window size. One column is a supported
        layout below ~760 px of content."""
        width = self._usable()
        if width >= 1480:
            return 4
        if width >= 1120:
            return 3
        if width >= 760:
            return 2
        return 1

    def _update_pager(self) -> None:
        """Prev/Next enablement + page label + "more may exist" hint, driven
        by the engine's real `more` signal (a full page came back) so a short
        final page never looks like more content exists. When the real total
        is known, also show the total-page estimate (total ÷ page size) and
        arm the jump-to-page spin box."""
        has_page = bool(self._hits)
        self._prev_btn.setEnabled(self._page > 0)
        self._next_btn.setEnabled(has_page and self._more)
        page_label = f"Page {self._page + 1}"
        pages = 0
        if self._total:
            # Total-page estimate from the real provider total. Uses the
            # effective (merged/clamped) page size so the math matches how
            # offsets are computed.
            pages = max(1, math.ceil(self._total / max(1, self._page_size)))
            start = self._page * self._page_size + 1
            end = start + len(self._hits) - 1
            page_label += f" · showing {start}–{end} of {self._total}"
            if pages > 1:
                page_label += f" ({pages} pages)"
        elif has_page:
            start = self._page * self._page_size + 1
            end = start + len(self._hits) - 1
            page_label += f" · showing {start}–{end}"
        self._pager_status.setText(page_label)
        if not has_page:
            hint = "no results"
        elif self._more:
            hint = f"{len(self._hits)} results shown — more may exist"
        elif self._total:
            hint = f"all {self._total} results — end of catalog"
        else:
            hint = f"all {len(self._hits)} results — end of catalog"
        self._more_hint.setText(hint)
        self._next_btn.setToolTip(
            "More results may exist — load the next page." if self._more
            else f"No more pages — this page returned fewer than {self._page_size} results.")
        # Jump control: enabled only with a real total and more than one page.
        self._updating_jump = True
        self._jump_spin.setRange(1, max(1, pages))
        self._jump_spin.setEnabled(pages > 1)
        self._jump_spin.setSuffix(f" / {pages}" if pages else "")
        self._jump_spin.setValue(self._page + 1)
        self._updating_jump = False

    def _on_jump_edit(self, value: int) -> None:
        """Immediate jump-to-page: any committed value (arrows or Enter)
        that differs from the current page navigates there directly. Guarded
        by _updating_jump so programmatic setValue in _update_pager and the
        page-memory restore path never re-trigger a search."""
        if self._updating_jump:
            return
        target = value - 1
        if target >= 0 and target != self._page:
            self._page = target
            self._remember_page()
            self._search_now()

    def _render_grid(self) -> None:
        clear_layout(self._grid)
        columns = self._column_count()
        self._last_columns = columns
        for col in range(columns):
            self._grid.setColumnStretch(col, 1)
        for index, hit in enumerate(self._hits):
            self._grid.addWidget(self._card(hit), index // columns, index % columns)
        if not self._hits:
            empty = card(self)
            empty.setProperty("cls", "empty-state")
            theme.polish(empty)
            empty_lay = vbox(empty, 10, margins=(28, 28, 28, 28))
            empty_icon = QLabel(empty)
            empty_icon.setPixmap(icon_pixmap("search", theme.MUTED, 28))
            empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lay.addWidget(empty_icon)
            empty_title = label(empty, "No compatible projects found", "h2")
            empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lay.addWidget(empty_title)
            empty_copy = label(empty, "Try another Minecraft version, loader, content type, or source.", "sub")
            empty_copy.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lay.addWidget(empty_copy)
            self._grid.addWidget(empty, 0, 0, 1, columns)

    def _skeleton_card(self) -> QFrame:
        skeleton = QFrame(self)
        skeleton.setProperty("cls", "skeleton")
        theme.polish(skeleton)
        skeleton.setMinimumHeight(218)
        loading_lay = vbox(skeleton, 12, margins=(16, 16, 16, 16))
        loading_lay.addWidget(label(skeleton, "Loading project artwork…", "muted"))
        loading_lay.addStretch(1)
        loading_lay.addWidget(label(skeleton, "Checking versions and source status", "mono muted"))
        return skeleton

    def _provider_badge(self, parent: QWidget, provider: str):
        control = pill(parent, "CurseForge" if provider == "curseforge" else "Modrinth", False, "provider-pill")
        control.setProperty("provider", provider)
        theme.polish(control)
        return control

    def _card(self, hit: dict) -> QFrame:
        project_card = card(self, hover=True)
        project_card.setProperty("provider", hit.get("provider") or "modrinth")
        project_card.setCursor(Qt.CursorShape.PointingHandCursor)
        project_card.setMinimumHeight(218)
        theme.polish(project_card)
        card_lay = vbox(project_card, 11, margins=(15, 14, 15, 14))

        top = QHBoxLayout()
        top.setSpacing(12)
        image_frame = QFrame(project_card)
        image_frame.setProperty("cls", "image-frame")
        image_frame.setFixedSize(66, 66)
        theme.polish(image_frame)
        image_lay = vbox(image_frame, margins=5)
        image_label = QLabel(image_frame)
        image_label.setFixedSize(56, 56)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setPixmap(avatar(hit.get("title") or "?", theme.GREEN, 56, 9))
        if hit.get("iconUrl"):
            icon_cache.request(hit["iconUrl"], image_label, 56, box=(56, 56))
        image_lay.addWidget(image_label)
        top.addWidget(image_frame)

        title_col = vbox(project_card, 2)
        title = label(project_card, hit.get("title") or hit.get("slug") or "Unknown project", "h3")
        title.setWordWrap(True)
        title_col.addWidget(title)
        author = label(project_card, f"by {hit.get('author') or 'Unknown creator'}", "mono muted")
        author.setWordWrap(True)  # long creator names must not widen the card's layout minimum
        title_col.addWidget(author)
        modified = fmt_ago(hit.get("dateModified"))
        updated = label(project_card, f"Updated {modified}", "muted")
        updated.setProperty("allowTextClip", True)
        updated.setToolTip(updated.text())
        updated.setWordWrap(True)
        title_col.addWidget(updated)
        top.addLayout(title_col, 1)
        top.addWidget(self._provider_badge(project_card, hit.get("provider") or "modrinth"),
                      0, Qt.AlignmentFlag.AlignTop)
        card_lay.addLayout(top)

        description = label(project_card, hit.get("description") or "No project summary is available.", "sub")
        description.setWordWrap(True)
        description.setMinimumHeight(38)
        description.setMaximumHeight(42)
        card_lay.addWidget(description)

        categories = [str(value).replace("-", " ") for value in (hit.get("categories") or [])[:2]]
        if categories:
            tag_row = QHBoxLayout()
            tag_row.setSpacing(6)
            for value in categories:
                tag_row.addWidget(pill(project_card, value[:18], False, "tag-pill"))
            tag_row.addStretch(1)
            card_lay.addLayout(tag_row)
        card_lay.addStretch(1)

        bottom = QHBoxLayout()
        bottom.setSpacing(7)
        download_icon = QLabel(project_card)
        download_icon.setPixmap(icon_pixmap("download", theme.BLUE, 14))
        bottom.addWidget(download_icon)
        bottom.addWidget(label(project_card, f"{fmt_downloads(hit.get('downloads'))} downloads", "muted"))
        bottom.addStretch(1)
        content_type = str(hit.get("projectType") or "mod")
        action_text = "Install pack" if content_type == "modpack" else "Add to pack"
        action = button(project_card, action_text, "btn-dark", "download" if content_type == "modpack" else "plus", theme.GREEN)
        action.clicked.connect(lambda _=False, selected=hit: self._action(selected))
        bottom.addWidget(action)
        card_lay.addLayout(bottom)

        project_card.mousePressEvent = lambda event, selected=hit: self._open_drawer(selected)
        make_clickable(project_card, lambda: self._open_drawer(hit),
                       name=f"Details for {hit.get('title') or hit.get('slug') or 'project'}")
        return project_card

    # ------------------------------------------------------------------
    def _action(self, hit: dict) -> None:
        if (hit.get("projectType") or "mod") == "modpack":
            self.import_pack.emit(hit.get("provider") or "modrinth", hit.get("projectId") or hit.get("slug"))
            return
        if not self._target_id:
            self._open_drawer(hit)
            return
        self.add_mod.emit(self._target_id, hit.get("provider") or "modrinth",
                          hit.get("projectId") or hit.get("slug"), None, hit.get("projectType"))

    def _open_drawer(self, hit: dict) -> None:
        self._selected = hit
        self._drawer_serial += 1
        serial = self._drawer_serial
        if self._drawer is not None:
            self._drawer.hide()
            self._drawer.deleteLater()

        drawer = QFrame(self)
        drawer.setProperty("cls", "drawer")
        theme.polish(drawer)
        # The drawer must never be wider than the viewport it sits on (its
        # close button lives in the header and its primary action at the
        # bottom of a scroll area, so both stay reachable at any width).
        drawer.setFixedWidth(min(500, max(340, self._usable())))
        drawer_outer = vbox(drawer, 0, margins=0)
        scroll = QScrollArea(drawer)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(scroll)
        content.setProperty("drawerPage", "true")
        scroll.setWidget(content)
        drawer_lay = vbox(content, 15, margins=(20, 18, 20, 22))
        drawer_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        drawer_outer.addWidget(scroll)

        head = QHBoxLayout()
        head.setSpacing(13)
        image_frame = QFrame(content)
        image_frame.setProperty("cls", "image-frame")
        image_frame.setFixedSize(78, 78)
        theme.polish(image_frame)
        image_lay = vbox(image_frame, margins=5)
        project_icon = QLabel(image_frame)
        project_icon.setFixedSize(68, 68)
        project_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        project_icon.setPixmap(avatar(hit.get("title") or "?", theme.GREEN, 68, 11))
        if hit.get("iconUrl"):
            icon_cache.request(hit["iconUrl"], project_icon, 68, box=(68, 68))
        image_lay.addWidget(project_icon)
        head.addWidget(image_frame)
        title_col = vbox(content, 3)
        title = label(content, hit.get("title") or "Unknown project", "h2")
        title.setWordWrap(True)
        title_col.addWidget(title)
        title_col.addWidget(label(content, f"by {hit.get('author') or 'Unknown creator'}", "mono muted"))
        title_col.addWidget(label(content, f"{fmt_downloads(hit.get('downloads'))} downloads", "small"))
        head.addLayout(title_col, 1)
        close = icon_btn(content, "x", "Close")
        close.clicked.connect(self._close_drawer)
        head.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        drawer_lay.addLayout(head)

        badges = QHBoxLayout()
        badges.setSpacing(7)
        badges.addWidget(self._provider_badge(content, hit.get("provider") or "modrinth"))
        badges.addWidget(pill(content, str(hit.get("projectType") or "mod").replace("resourcepack", "resource pack"), True))
        badges.addStretch(1)
        drawer_lay.addLayout(badges)

        self._drawer_description = label(content, hit.get("description") or "Loading project details…", "sub")
        self._drawer_description.setWordWrap(True)
        drawer_lay.addWidget(self._drawer_description)

        self._gallery_title = label(content, "Project images", "h3")
        drawer_lay.addWidget(self._gallery_title)
        gallery_widget = QWidget(content)
        self._gallery_lay = QGridLayout(gallery_widget)
        self._gallery_lay.setContentsMargins(0, 0, 0, 0)
        self._gallery_lay.setSpacing(8)
        drawer_lay.addWidget(gallery_widget)
        self._render_gallery(hit.get("gallery") or [])

        # Creator-linked videos (parsed from the project's own listing text)
        # and an honest pointer to where community discussion lives — neither
        # public provider API serves comments or a video feed directly.
        self._videos_title = label(content, "Videos", "h3")
        self._videos_title.hide()
        drawer_lay.addWidget(self._videos_title)
        self._videos_row = QWidget(content)
        videos_lay = QHBoxLayout(self._videos_row)
        videos_lay.setContentsMargins(0, 0, 0, 0)
        videos_lay.setSpacing(8)
        self._videos_row.hide()
        drawer_lay.addWidget(self._videos_row)
        provider_name = "CurseForge" if (hit.get("provider") or "") == "curseforge" else "Modrinth"
        community = label(
            content,
            f"Comments live on {provider_name} — “Open project page” below takes you to the discussion.",
            "muted",
        )
        community.setWordWrap(True)
        drawer_lay.addWidget(community)

        version_head = QHBoxLayout()
        version_head.addWidget(label(content, "Compatible version", "h3"))
        version_head.addStretch(1)
        self._detail_status = label(content, "Checking provider metadata…", "mono muted")
        version_head.addWidget(self._detail_status)
        drawer_lay.addLayout(version_head)
        self._version_box = QComboBox(content)
        self._version_box.addItem("Latest compatible version", None)
        drawer_lay.addWidget(self._version_box)

        project_type = hit.get("projectType") or "mod"
        if project_type not in ("modpack", "world"):
            target_row = QHBoxLayout()
            # Ref kept so scoped subclasses can hide the whole selector.
            self._target_label = label(content, "Add to", "small")
            target_row.addWidget(self._target_label)
            self._target_box = QComboBox(content)
            for build in self.builds:
                self._target_box.addItem(
                    f"{build.get('name')} · MC {build.get('mcVersion') or ''} · {build.get('loader') or ''}",
                    build.get("buildId"),
                )
            if self._target_id:
                target_index = self._target_box.findData(self._target_id)
                if target_index >= 0:
                    self._target_box.setCurrentIndex(target_index)
            self._target_box.currentIndexChanged.connect(
                lambda index, selected=hit, token=serial: self._target_changed(index, selected, token))
            target_row.addWidget(self._target_box, 1)
            drawer_lay.addLayout(target_row)

        actions = QHBoxLayout()
        actions.setSpacing(9)
        website = button(content, "Open project page", "btn-dark", "external")
        website.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(hit.get("url") or "")))
        actions.addWidget(website)
        if project_type == "modpack":
            primary = button(content, "Install to library", "btn-primary", "download", theme.BG)
            primary.clicked.connect(lambda: self.import_pack.emit(
                hit.get("provider") or "modrinth", hit.get("projectId") or hit.get("slug")))
        elif project_type == "world":
            primary = button(content, "Open world page", "btn-primary", "external", theme.BG)
            primary.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(hit.get("url") or "")))
        else:
            primary = button(content, "Add to pack", "btn-primary", "plus", theme.BG)
            primary.setEnabled(bool(self.builds))
            primary.setToolTip("Create or import a pack first." if not self.builds else "Resolve dependencies and add this content.")
            primary.clicked.connect(lambda: self._add_selected(hit))
        self._drawer_primary = primary
        actions.addWidget(primary, 1)
        drawer_lay.addLayout(actions)
        drawer_lay.addStretch(1)

        self._drawer = drawer
        self._drawer.show()
        self._reposition_drawer()
        self._drawer.raise_()

        target = self._target_build()
        detail_mc = target.get("mcVersion") if target else self._version
        detail_loader = target.get("loader") if target else self._loader
        self._load_drawer_details(hit, serial, detail_mc or self._version, detail_loader or self._loader)

    def _target_build(self) -> dict | None:
        return next((build for build in self.builds if build.get("buildId") == self._target_id), None)

    def _target_changed(self, index: int, hit: dict, serial: int) -> None:
        if not hasattr(self, "_target_box"):
            return
        self._target_id = self._target_box.itemData(index)
        target = self._target_build()
        self._load_drawer_details(
            hit,
            serial,
            (target or {}).get("mcVersion") or self._version,
            (target or {}).get("loader") or self._loader,
        )

    def _load_drawer_details(self, hit: dict, serial: int, mc: str, loader_name: str) -> None:
        if serial != self._drawer_serial or self._drawer is None:
            return
        self._detail_serial += 1
        detail_token = self._detail_serial
        self._detail_status.setText(f"Checking {mc or 'all versions'} / {loader_name or 'all loaders'}…")
        self._version_box.setEnabled(False)
        if getattr(self, "_drawer_primary", None) is not None and hit.get("projectType") not in ("modpack", "world"):
            self._drawer_primary.setEnabled(False)

        def fetch_details():
            return self.api.project_details(
                hit.get("provider") or "modrinth",
                hit.get("projectId") or hit.get("slug"),
                mc,
                loader_name,
            )

        def details_ok(result):
            if (serial != self._drawer_serial or detail_token != self._detail_serial
                    or self._drawer is None):
                return
            project = result.get("project") or {}
            self._drawer_description.setText(project.get("description") or hit.get("description") or "No description available.")
            self._render_gallery(project.get("gallery") or hit.get("gallery") or [])
            self._render_videos(project.get("videos") or [])
            versions = result.get("versions") or []
            self._version_box.clear()
            if not versions:
                self._version_box.addItem("No compatible versions", None)
                self._version_box.setEnabled(False)
                self._detail_status.setText(f"No match for {mc} / {loader_name}")
                if getattr(self, "_drawer_primary", None) is not None and hit.get("projectType") not in ("modpack", "world"):
                    self._drawer_primary.setEnabled(False)
                    self._drawer_primary.setToolTip("This project has no file compatible with the selected pack.")
            else:
                self._version_box.setEnabled(True)
                for version in versions:
                    loaders = ", ".join(version.get("loaders") or [])
                    suffix = f" · {loaders}" if loaders else ""
                    self._version_box.addItem(
                        f"{version.get('versionNumber') or version.get('name')} · {version.get('releaseChannel', 'release')}{suffix}",
                        version.get("versionId"),
                    )
                self._detail_status.setText(f"{len(versions)} for {mc} / {loader_name}")
                if getattr(self, "_drawer_primary", None) is not None and hit.get("projectType") not in ("modpack", "world"):
                    self._drawer_primary.setEnabled(bool(self.builds))
                    self._drawer_primary.setToolTip("Resolve dependencies and add this compatible file.")

        def details_err(error):
            if (serial == self._drawer_serial and detail_token == self._detail_serial
                    and self._drawer is not None):
                self._detail_status.setText("Details unavailable")
                self._detail_status.setToolTip(str(error))
                if getattr(self, "_drawer_primary", None) is not None and hit.get("projectType") not in ("modpack", "world"):
                    self._drawer_primary.setEnabled(False)

        run_async(fetch_details, details_ok, details_err)

    def _render_gallery(self, gallery: list[dict]) -> None:
        clear_layout(self._gallery_lay)
        images = [item for item in gallery if item.get("thumbnailUrl") or item.get("url")][:3]
        self._gallery_title.setVisible(bool(images))
        if not images:
            return
        # Tile widths come from the actual drawer width so three screenshots
        # exactly fill the row, and each provider image is cover-cropped into
        # its tile — no letterbox gaps, no oversized overflow.
        inner = min(500, max(340, self._usable())) - 40  # drawer width - page margins
        spacing = self._gallery_lay.spacing() or 8
        tile_w = max(90, (inner - spacing * 2) // 3)
        label_w, label_h = tile_w - 8, 78
        for index, item in enumerate(images):
            image_frame = QFrame(self)
            image_frame.setProperty("cls", "gallery-frame")
            theme.polish(image_frame)
            image_frame.setFixedSize(tile_w, 86)
            frame_lay = vbox(image_frame, margins=4)
            image_label = QLabel(image_frame)
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image_label.setFixedSize(label_w, label_h)
            image_label.setPixmap(avatar(item.get("title") or "Image", theme.BLUE, 48, 8))
            icon_cache.request(item.get("thumbnailUrl") or item.get("url"), image_label,
                               size=label_h, box=(label_w, label_h))
            image_label.setToolTip(item.get("title") or item.get("description") or "Project screenshot")
            frame_lay.addWidget(image_label)
            self._gallery_lay.addWidget(image_frame, 0, index)
            self._gallery_lay.setColumnStretch(index, 1)

    def _render_videos(self, videos: list[dict]) -> None:
        """Fill the Videos row with external watch buttons (host-labeled).
        Called from the details callback; empty lists hide the whole section."""
        lay = self._videos_row.layout()
        while lay.count():
            item = lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        videos = [v for v in (videos or []) if v.get("url")][:4]
        self._videos_title.setVisible(bool(videos))
        self._videos_row.setVisible(bool(videos))
        for video in videos:
            chip = button(self._videos_row, f"Watch on {video.get('host')}", "btn-dark", "external")
            chip.clicked.connect(lambda _=False, url=video["url"]: QDesktopServices.openUrl(QUrl(url)))
            lay.addWidget(chip, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)

    def _add_selected(self, hit: dict) -> None:
        version_id = self._version_box.currentData() if hasattr(self, "_version_box") else None
        self.add_mod.emit(self._target_id or "", hit.get("provider") or "modrinth",
                          hit.get("projectId") or hit.get("slug"), version_id, hit.get("projectType"))
        self._close_drawer()

    def _close_drawer(self) -> None:
        self._drawer_serial += 1
        if self._drawer is not None:
            self._drawer.hide()
            self._drawer.deleteLater()
            self._drawer = None

    def _reposition_drawer(self) -> None:
        if self._drawer is None:
            return
        width = self._drawer.width()
        self._drawer.setGeometry(self.width() - width, 0, width, self.height())
        self._drawer.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        columns = self._column_count()
        if columns != self._last_columns and self._hits:
            self._render_grid()
        self._reposition_drawer()
        # The pager's "more may exist" hint is the first thing to give up
        # when the row is tight — Prev/Next and the jump box stay reachable.
        if hasattr(self, "_more_hint"):
            self._more_hint.setVisible(self._usable() >= 860)
