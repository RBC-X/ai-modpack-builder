"""AI Modpack Builder — PyQt6 desktop client and launcher shell.

The launcher IS the engine: the full Python engine (pyqt/engine/) runs
in-process inside this app. No Node server, no localhost, no second process.

Run:  pyqt/.venv/Scripts/python -m pyqt.main
(or:  python pyqt/main.py)
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QKeyEvent
from PyQt6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel,
                             QMainWindow, QMessageBox, QPushButton, QStackedWidget,
                             QSizeGrip, QTextEdit, QVBoxLayout, QWidget)

import theme
import minecraft_auth
from engine.bridge import PyEngine
from common import (avatar, button, hbox, icon_cache, icon_pixmap, label, pill,
                    run_async, vbox)
from icons import icon
from views.aibuilder import AIBuilderView
from views.discover import DiscoverView
from views.addcontent import AddContentView
from views.home import HomeView
from views.library import LibraryView
from views.misc import ActivityView, DownloadsView, SettingsView
from views.overlays import (AccountModal, CrashDrawer, ImportModal, ImportOverlay,
                            LaunchOverlay, NewPackDialog)
from views.packdetail import PackDetailView
from views.health_mixin import HealthMixin
from views.launch_mixin import LaunchMixin
from views.topbar import AppTopBar

NAV = [
    ("home", "Home", "home"),
    ("library", "Library", "library"),
    ("discover", "Discover", "compass"),
    ("ai-builder", "AI Builder", "sparkles"),
    ("downloads", "Downloads", "download"),
    ("activity", "Activity", "activity"),
    ("settings", "Settings", "settings"),
]

TITLES = {k: v.title() for k, v, _ in NAV}
ATTR_BY_NAV = {nid: nid.replace("-", "") for nid, _l, _i in NAV}


class MainWindow(HealthMixin, LaunchMixin, QMainWindow):
    def __init__(self, api: PyEngine):
        super().__init__()
        self.api = api
        self.builds: list[dict] = []
        self.records: dict[str, dict] = {}
        self._refresh_gen = 0
        self._refresh_applied = 0
        self.active_nav = "home"
        self.detail_pack_id: str | None = None
        self._launching: str | None = None
        self._launch_ui_applied = False
        self._online = False
        self._inprocess = isinstance(api, PyEngine)
        self._hardware: dict | None = None
        self._restart_pending = False
        self._restart_attempts = 0
        self._retry_in = 0

        self.setWindowTitle("AI Modpack Builder")
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "app.ico")))
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.resize(1365, 840)
        self.setMinimumSize(1080, 700)
        self.setStyleSheet(theme.QSS)

        # overlays (created before the sidebar wires its account button)
        self.account_modal = AccountModal(self)
        self.import_modal = ImportModal(self)
        self.new_pack_dialog = NewPackDialog(self)
        self.launch_overlay = LaunchOverlay(self, api)
        self.import_overlay = ImportOverlay(self)
        self.crash_drawer = CrashDrawer(self, api)
        self._palette: QDialog | None = None

        # central layout: sidebar | right column
        central = QWidget()
        central.setObjectName("appRoot")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        self.sidebar = self._build_sidebar()
        root.addWidget(self.sidebar)

        right = QWidget()
        right.setObjectName("appRight")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.topbar = self._build_topbar()
        rl.addWidget(self.topbar)

        self.stack = QStackedWidget()
        self.home = HomeView()
        self.library = LibraryView()
        self.discover = DiscoverView(api)
        # Pack-scoped content browser: opened from Pack Detail's ADD CONTENT
        # (not a sidebar destination) and bound to one pack at a time.
        self.addcontent = AddContentView(api)
        self.aibuilder = AIBuilderView(api)
        self.downloads = DownloadsView(api)
        self.activity = ActivityView(api)
        # Settings is a floating overlay, not a stack page: it lays on top of
        # whichever page is underneath (see _set_nav / show_overlay).
        self.settings = SettingsView(api, self)
        self.packdetail = PackDetailView(api)
        for w in (self.home, self.library, self.discover, self.aibuilder,
                  self.downloads, self.activity, self.packdetail, self.addcontent):
            self.stack.addWidget(w)
        rl.addWidget(self.stack, 1)
        root.addWidget(right, 1)

        self._wire()
        self._set_nav("home")
        self._refresh_account_block()
        self._statusbar_setup()
        self._timers()
        self._bootstrap()

    # ------------------------------------------------------------------
    def _statusbar_setup(self) -> None:
        # The reference has no permanently reserved bottom strip. Keep engine
        # messages available as a transient floating toast instead.
        self._toast_serial = 0
        self._toast = label(self.centralWidget(), "", "toast")
        self._toast.setWordWrap(True)
        self._toast.setMaximumWidth(560)
        self._toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._toast.hide()
        # Rich update toast: title + markdown-rendered release notes + action.
        # Interactive (no WA_TransparentForMouseEvents) so Review works.
        self._update_toast_serial = 0
        self._update_toast = QFrame(self.centralWidget())
        self._update_toast.setProperty("cls", "toast-frame")
        self._update_toast.setMaximumWidth(560)
        theme.polish(self._update_toast)
        utl = vbox(self._update_toast, 8, margins=(14, 12, 14, 12))
        self._update_toast_title = label(self._update_toast, "", "toast-title")
        utl.addWidget(self._update_toast_title)
        self._update_toast_notes = QTextEdit(self._update_toast)
        self._update_toast_notes.setProperty("cls", "toast-notes")
        self._update_toast_notes.setReadOnly(True)
        self._update_toast_notes.setFrameShape(QFrame.Shape.NoFrame)
        self._update_toast_notes.setFixedHeight(150)
        self._update_toast_notes.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        theme.polish(self._update_toast_notes)
        utl.addWidget(self._update_toast_notes)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._update_toast_later = button(self._update_toast, "Later", "btn-dark")
        self._update_toast_later.clicked.connect(self._update_toast.hide)
        btn_row.addWidget(self._update_toast_later)
        self._update_toast_btn = button(self._update_toast, "REVIEW & INSTALL", "btn-primary", "download", theme.BG)
        btn_row.addWidget(self._update_toast_btn)
        utl.addLayout(btn_row)
        self._update_toast.hide()
        self._resize_grip = QSizeGrip(self.centralWidget())
        self._resize_grip.setFixedSize(14, 14)
        self._resize_grip.setStyleSheet("background: transparent; border: none;")
        self._place_resize_grip()

    def toast(self, msg: str, ms: int = 5000) -> None:
        self._toast_serial += 1
        serial = self._toast_serial
        self._toast.setText(msg)
        self._toast.adjustSize()
        self._place_toast()
        self._toast.show()
        self._toast.raise_()

        def hide_current() -> None:
            if serial == self._toast_serial:
                self._toast.hide()

        QTimer.singleShot(ms, hide_current)

    def _place_toast(self) -> None:
        if not hasattr(self, "_toast"):
            return
        x = max(16, self.centralWidget().width() - self._toast.width() - 24)
        y = max(58, self.centralWidget().height() - self._toast.height() - 24)
        self._toast.move(x, y)

    def _place_update_toast(self) -> None:
        if not hasattr(self, "_update_toast"):
            return
        self._update_toast.adjustSize()
        x = max(16, self.centralWidget().width() - self._update_toast.width() - 24)
        y = max(58, self.centralWidget().height() - self._update_toast.height() - 24)
        self._update_toast.move(x, y)

    def toast_update(self, latest: str, notes: str, on_action=None) -> None:
        """Rich update toast: rendered release notes + a Review & install action.

        The action routes into Settings → Updates (which re-runs the check and
        shows the notes plus the install dialog) — so users always see the
        release notes before anything is applied.
        """
        self._update_toast_serial += 1
        self._update_toast_title.setText(f"Update v{latest} available")
        body = str(notes or "").strip()
        self._update_toast_notes.setMarkdown(body or "_The update feed did not include release notes._")
        try:
            self._update_toast_btn.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        if on_action is not None:
            def go():
                self._update_toast.hide()
                on_action()
            self._update_toast_btn.clicked.connect(go)
        self._update_toast_btn.setVisible(on_action is not None)
        self._place_update_toast()
        self._update_toast.show()
        self._update_toast.raise_()

    def _place_resize_grip(self) -> None:
        if not hasattr(self, "_resize_grip"):
            return
        self._resize_grip.move(
            self.centralWidget().width() - self._resize_grip.width(),
            self.centralWidget().height() - self._resize_grip.height(),
        )
        self._resize_grip.raise_()

    # ------------------------------------------------------------------
    def _build_sidebar(self) -> QFrame:
        from views.misc import _load_state
        sb = QFrame(self)
        sb.setProperty("cls", "sidebar")
        theme.polish(sb)
        self._sidebar_compact = bool(_load_state().get("sidebarCompact", False))
        sb.setFixedWidth(64 if self._sidebar_compact else 224)
        self._sb = sb
        self._sb_labels: list[QLabel] = []   # text labels to hide when compact
        self._sb_text_cols: list = []        # text columns (logo subtitle, account)
        self._sb_badges: list[QLabel] = []   # AI / download badges
        v = vbox(sb, 0)
        v.setContentsMargins(0, 0, 0, 0)

        # logo header from the supplied launcher design
        logo = QFrame(sb)
        logo.setObjectName("logoHeader")
        logo.setFixedHeight(58)
        theme.polish(logo)
        lr = hbox(logo, 10, margins=(20, 0, 16, 0))
        mark = QFrame(logo)
        mark.setProperty("cls", "logo-badge")
        mark.setFixedSize(32, 32)
        theme.polish(mark)
        mark_lay = hbox(mark, 0, margins=0)
        z = QLabel(mark)
        z.setPixmap(icon_pixmap("package", theme.GREEN, 17))
        z.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark_lay.addWidget(z)
        lr.addWidget(mark)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = label(logo, "AI MODPACK", "logo-title")
        col.addWidget(t)
        self._sb_labels.append(t)
        sub = label(logo, "BUILDER + LAUNCHER", "logo-sub")
        col.addWidget(sub)
        self._sb_labels.append(sub)
        lr.addLayout(col)
        self._sb_text_cols.append(col)
        lr.addStretch(1)
        v.addWidget(logo)

        # nav
        self.nav_btns: dict[str, tuple[QFrame, QLabel, QLabel, QLabel]] = {}
        navwrap = QWidget(sb)
        nv = vbox(navwrap, 4, margins=(12, 12, 12, 4))
        for nid, nlabel, nicon in NAV:
            b = QFrame(navwrap)
            b.setObjectName(f"nav_{nid}")
            b.setFixedHeight(44)
            bl = hbox(b, 12, margins=(14, 0, 14, 0))
            indicator = QLabel(b)
            indicator.setProperty("cls", "nav-indicator")
            indicator.setGeometry(0, 6, 3, 32)
            indicator.setVisible(False)
            theme.polish(indicator)
            ic = QLabel(b)
            ic.setPixmap(icon_pixmap(nicon, theme.MUTED, 16))
            ic.setFixedSize(16, 16)
            ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bl.addWidget(ic)
            nav_label = label(b, nlabel, "nav-label")
            bl.addWidget(nav_label)
            self._sb_labels.append(nav_label)
            bl.addStretch(1)
            if nid == "ai-builder":
                badge = label(b, "AI", "nav-badge-ai")
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                bl.addWidget(badge)
                self._sb_badges.append(badge)
            if nid == "downloads":
                self._dl_badge = label(b, "", "nav-badge")
                self._dl_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._dl_badge.setVisible(False)
                bl.addWidget(self._dl_badge)
                self._sb_badges.append(self._dl_badge)
            b.mousePressEvent = lambda e, n=nid: self._set_nav(n)
            # Keyboard accessibility: the nav items are QFrames, so make them
            # tab-reachable and activate on Enter/Space (not just clicks). The
            # tooltip doubles as the screen-reader name.
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)

            def _nav_key(e, n=nid):
                if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                    self._set_nav(n)
                    e.accept()
                    return
                QFrame.keyPressEvent(b, e)

            b.keyPressEvent = _nav_key
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(nlabel)
            nv.addWidget(b)
            self.nav_btns[nid] = (b, indicator, ic, nav_label)
        v.addWidget(navwrap)
        v.addStretch(1)

        # collapse toggle
        toggle_row = QFrame(sb)
        toggle_row.setProperty("cls", "sidebar-divider")
        theme.polish(toggle_row)
        tr = hbox(toggle_row, 0, margins=(12, 10, 12, 10))
        self._sb_toggle = button(toggle_row, "", "iconbtn",
                                "chevrons-left" if not self._sidebar_compact else "chevrons-right",
                                theme.TEXT2)
        self._sb_toggle.setToolTip("Collapse sidebar" if not self._sidebar_compact else "Expand sidebar")
        self._sb_toggle.clicked.connect(self._toggle_sidebar)
        tr.addWidget(self._sb_toggle)
        tr.addStretch(1)
        v.addWidget(toggle_row)

        # account block
        account_wrap = QFrame(sb)
        account_wrap.setProperty("cls", "sidebar-divider")
        theme.polish(account_wrap)
        aw = vbox(account_wrap, 0, margins=(10, 10, 10, 10))
        self._account_wrap = account_wrap
        acc = QFrame(account_wrap)
        acc.setProperty("cls", "account-card")
        theme.polish(acc)
        self._acc_card = acc
        ar = hbox(acc, 10, margins=(8, 8, 6, 6))
        self._acc_icon = QLabel(acc)
        self._acc_icon.setFixedSize(32, 32)
        ar.addWidget(self._acc_icon)
        col2 = QVBoxLayout()
        col2.setSpacing(0)
        self._acc_name = label(acc, "N/A", "h3")
        col2.addWidget(self._acc_name)
        self._sb_labels.append(self._acc_name)
        self._acc_status = label(acc, "Status: N/A", "muted")
        col2.addWidget(self._acc_status)
        self._sb_labels.append(self._acc_status)
        ar.addLayout(col2, 1)
        self._sb_text_cols.append(col2)
        ab = button(acc, "", "iconbtn", "usercheck", theme.GREEN)
        ab.clicked.connect(self.account_modal.show)
        # _refresh_account_block() sets the profile name as text + a tooltip,
        # which together form its accessible name — nothing more needed here.
        self._acc_btn = ab
        ar.addWidget(ab)
        aw.addWidget(acc)
        v.addWidget(account_wrap)
        self._refresh_account_block()
        self._apply_sidebar_compact(animate=False)
        return sb

    def _toggle_sidebar(self) -> None:
        from views.misc import _load_state, _save_state
        self._sidebar_compact = not self._sidebar_compact
        st = _load_state()
        st["sidebarCompact"] = self._sidebar_compact
        _save_state(st)
        self._apply_sidebar_compact(animate=True)

    def _apply_sidebar_compact(self, animate: bool = False) -> None:
        compact = self._sidebar_compact
        target = 64 if compact else 224
        self._sb.setFixedWidth(target)
        self._sb_toggle.setIcon(icon("chevrons-right" if compact else "chevrons-left",
                                     theme.TEXT2))
        self._sb_toggle.setToolTip("Expand sidebar" if compact else "Collapse sidebar")
        for label_w in self._sb_labels:
            label_w.setVisible(not compact)
        for col in self._sb_text_cols:
            col.setEnabled(not compact)
        for badge in self._sb_badges:
            badge.setVisible(not compact)
        # Account block: compact shows only the centered avatar (the card
        # chrome + usercheck button only fit at 224px).
        self._acc_card.setVisible(not compact)
        if hasattr(self, "_acc_btn"):
            self._acc_btn.setVisible(not compact)
        self._apply_sidebar_margins()

    def _apply_sidebar_margins(self) -> None:
        """Center nav icons when compact; keep left-aligned when expanded."""
        compact = self._sidebar_compact
        # Nav rows are built once; compact mode centers the icon in the rail.
        for nid, (b, indicator, ic, nav_label) in self.nav_btns.items():
            lay = b.layout()
            if lay is None:
                continue
            if compact:
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(0)
                for i in range(lay.count()):
                    item = lay.itemAt(i)
                    if item.widget() is ic:
                        lay.setAlignment(ic, Qt.AlignmentFlag.AlignHCenter)
            else:
                lay.setContentsMargins(14, 0, 14, 0)
                lay.setSpacing(12)

    def _refresh_account_block(self) -> None:
        from views.misc import _load_state
        st = _load_state()
        name = st.get("accountName") or "N/A"
        microsoft = st.get("accountMode") == "microsoft" and minecraft_auth.has_saved_credential()
        self._acc_name.setText(name)
        # Keep the status line short enough for the fixed 224px sidebar — the
        # long "Status: …" prefixes clipped the label (visual audit found
        # 'Status: Offline profile' needing 118px with only 94px available).
        if microsoft:
            self._acc_status.setText("Microsoft / Java")
        else:
            self._acc_status.setText("Offline profile" if name != "N/A" else "Setup needed")
        self._acc_status.setToolTip(
            "Microsoft / Java account connected" if microsoft else
            ("Offline Minecraft profile" if name != "N/A" else "Minecraft account not configured")
        )
        self._acc_icon.setPixmap(avatar(name, theme.GREEN, 32, 8))
        if hasattr(self, "_acc_btn"):
            self._acc_btn.setText(name)
            self._acc_btn.setToolTip("Minecraft profile used for launches")

    # ------------------------------------------------------------------
    def _build_topbar(self) -> QFrame:
        tb = AppTopBar(self)
        tb.setProperty("cls", "topbar")
        theme.polish(tb)
        tb.setFixedHeight(50)
        row = hbox(tb, 16, margins=(32, 0, 32, 0))
        self._title = label(tb, "Home", "top-title")
        row.addWidget(self._title)
        row.addStretch(1)

        self._dl_btn = button(tb, "Downloads", "top-compact", "download", theme.MUTED)
        self._dl_btn.setProperty("active", "false")
        self._dl_btn.setFixedHeight(26)
        self._dl_btn.setIconSize(QSize(14, 14))
        self._dl_btn.clicked.connect(lambda: self._set_nav("downloads"))
        row.addWidget(self._dl_btn)

        self._net_pill = QFrame(tb)
        self._net_pill.setProperty("cls", "top-compact-frame")
        self._net_pill.setFixedHeight(26)
        theme.polish(self._net_pill)
        self._net_pill.setToolTip("Live connection to the local launcher engine")
        nl = hbox(self._net_pill, 6, margins=(10, 4, 10, 4))
        self._net_icon = QLabel(self._net_pill)
        self._net_icon.setPixmap(icon_pixmap("wifioff", theme.WARNING, 14))
        self._net_text = label(self._net_pill, "Starting…", "top-mono-warn")
        nl.addWidget(self._net_icon)
        nl.addWidget(self._net_text)
        row.addWidget(self._net_pill)

        acc = button(tb, "N/A", "top-compact", "user", theme.MUTED)
        acc.setFixedHeight(26)
        acc.setIconSize(QSize(14, 14))
        acc.clicked.connect(self.account_modal.show)
        row.addWidget(acc)
        self._acc_btn = acc

        # The reference uses three restrained dots. Here they are real window
        # controls instead of decorative, non-functional placeholders.
        controls = QWidget(tb)
        control_row = hbox(controls, 8, margins=0)
        divider = QFrame(controls)
        divider.setFixedSize(1, 20)
        divider.setStyleSheet(f"background: {theme.BORDER}; border: none;")
        control_row.addWidget(divider)
        for tip, action in [
            ("Minimize", self.showMinimized),
            ("Maximize or restore", self._toggle_maximized),
            ("Close", self.close),
        ]:
            dot = QPushButton(tb)
            dot.setProperty("cls", "window-dot")
            dot.setToolTip(tip)
            dot.setCursor(Qt.CursorShape.PointingHandCursor)
            dot.clicked.connect(action)
            theme.polish(dot)
            control_row.addWidget(dot)
        row.addWidget(controls)
        return tb

    def _toggle_maximized(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    # ------------------------------------------------------------------
    def _wire(self) -> None:
        self.home.play_requested.connect(self.play)
        self.home.stop_requested.connect(self.stop)
        self.home.open_detail.connect(self.open_detail)
        self.home.delete_requested.connect(self.delete_pack)
        self.home.navigate.connect(self._set_nav)
        self.home.import_requested.connect(self.import_modal.show)
        self.home.select_build.connect(self._select_build)
        self.home.seed_requested.connect(self._seed_ai_builder)

        self.library.play_requested.connect(self.play)
        self.library.stop_requested.connect(self.stop)
        self.library.open_detail.connect(self.open_detail)
        self.library.delete_requested.connect(self.delete_pack)
        self.library.density_changed.connect(self.home.set_density)
        self.library.import_requested.connect(self.import_modal.show)
        self.library.new_pack_requested.connect(self.new_pack_dialog.show)
        self.library.navigate_ai.connect(lambda: self._set_nav("ai-builder"))
        self.library.navigate_discover.connect(lambda: self._set_nav("discover"))
        self.library.select_build.connect(self._select_build)

        self.packdetail.back_requested.connect(lambda: self._open_detail(None))
        self.packdetail.play_requested.connect(self.play)
        self.packdetail.stop_requested.connect(self.stop)
        self.packdetail.remove_mod.connect(self.remove_mod)
        self.packdetail.retest_requested.connect(self.retest)
        self.packdetail.repair_requested.connect(self.repair)
        # ADD CONTENT opens the pack-scoped browser instead of redirecting to
        # the global Discover page (which made multi-pack installs error-prone).
        self.packdetail.add_content_requested.connect(self._open_add_content)
        self.addcontent.back_requested.connect(lambda: self._open_detail(self.detail_pack_id))
        self.addcontent.add_mod.connect(self.add_mod)
        self.addcontent.open_settings.connect(self._open_provider_settings)
        self.packdetail.ask_ai.connect(self.ask_ai)
        self.packdetail.rename_requested.connect(self.rename_pack)
        self.packdetail.backup_requested.connect(self.backup_pack)
        self.packdetail.export_requested.connect(self.export_pack)
        self.packdetail.open_evidence.connect(self.open_evidence)
        self.packdetail.set_ram.connect(self.set_ram)
        self.packdetail.set_auto_relaunch.connect(self.set_auto_relaunch)
        self.packdetail.set_shader_preset.connect(self.set_shader_preset)
        self.packdetail.status_changed.connect(lambda bid: self._reload_detail(bid))

        self.discover.add_mod.connect(self.add_mod)
        self.discover.import_pack.connect(self.import_pack)
        self.discover.open_settings.connect(self._open_provider_settings)
        self.settings.settings_changed.connect(lambda _patch: self.discover.invalidate_cache())
        self.settings.settings_changed.connect(lambda _patch: self.addcontent.invalidate_cache())
        self.settings.settings_changed.connect(lambda _patch: self.aibuilder._load_hardware())
        self.settings.manage_account_requested.connect(self.account_modal.show)
        self.settings.theme_changed.connect(self._apply_theme)
        self.settings.sidebar_changed.connect(self._apply_sidebar_state)

        from PyQt6.QtGui import QKeySequence, QShortcut
        self._palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._palette_shortcut.activated.connect(self._open_palette)

        self.aibuilder.build_completed.connect(lambda _bid: self.refresh_builds())
        self.aibuilder.play_requested.connect(self.play)

        self.activity.open_evidence.connect(self.open_evidence)

        self.import_modal.import_pack.connect(self.import_pack)
        self.import_modal.import_file.connect(self.import_file)
        self.new_pack_dialog.create_requested.connect(self.create_pack)

        self.launch_overlay.stop_requested.connect(lambda: self.stop(self._launching or ""))
        self.launch_overlay.view_crash.connect(self._open_crash_drawer)
        self.import_overlay.cancel_requested.connect(self._cancel_import)
        self.import_overlay.play_requested.connect(self.play)
        self.crash_drawer.close_requested.connect(self.crash_drawer.hide)
        self.crash_drawer.fix_requested.connect(self.fix_missing)
        self.settings.close_requested.connect(self._close_settings)
        self.account_modal.finished.connect(lambda _r: self._refresh_account_block())
        self.account_modal.account_changed.connect(self._refresh_account_block)

    def _open_provider_settings(self) -> None:
        self._set_nav("settings")
        self.settings.open_section("providers")

    def _close_settings(self) -> None:
        """Close the settings overlay and return to the page it covered."""
        self.settings.hide()
        nav = getattr(self, "_settings_return_nav", None) or "home"
        if nav == "settings":
            nav = "home"
        self._set_nav(nav)

    def _timers(self) -> None:
        self._poll = QTimer(self)
        self._poll.setInterval(900)
        self._poll.timeout.connect(self._poll_launch)
        self._health = QTimer(self)
        self._health.setInterval(8000)
        self._health.timeout.connect(self._check_health)
        self._health.start()
        self._retry_timer = QTimer(self)
        self._retry_timer.setInterval(1000)
        self._retry_timer.timeout.connect(self._retry_tick)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(20000)
        self._refresh_timer.timeout.connect(self.refresh_builds)
        self._refresh_timer.start()
        self._import_timer = QTimer(self)
        self._import_timer.setInterval(120)
        self._import_timer.timeout.connect(self._import_tick)
        self._import_state = {"stage": "Preparing import…", "done": 0, "total": 0}
        self._import_cancel: threading.Event | None = None
        self._warm_done = threading.Event()
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(2 * 3600 * 1000)  # every 2 h while open
        self._update_timer.timeout.connect(self._periodic_update_check)
        if getattr(sys, "frozen", False):
            self._update_timer.start()

    def _teardown(self) -> None:
        """Orderly shutdown: stop every timer and drain the async worker pool.

        Without this, a run_async worker still executing at interpreter exit
        posts its result into the module-level _poster while Qt is tearing
        down, which fails fast natively (STATUS_STACK_BUFFER_OVERRUN) and
        masks a clean exit — previously every session ended with a hard
        crash after all work was done."""
        for t in (self._poll, self._health, self._retry_timer,
                  self._refresh_timer, self._import_timer, self._update_timer):
            try:
                t.stop()
            except Exception:  # noqa: BLE001 — teardown must never raise
                pass
        cancel = getattr(self, "_import_cancel", None)
        if cancel is not None:
            try:
                cancel.set()
            except Exception:  # noqa: BLE001
                pass
        try:
            from PyQt6.QtCore import QThreadPool
            QThreadPool.globalInstance().waitForDone(8000)
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, event) -> None:  # noqa: N802
        """Closing the window must also shut down cleanly (timers + async
        workers), so the process exits without a native teardown crash."""
        self._teardown()
        super().closeEvent(event)

    def _bootstrap(self) -> None:
        self._check_health()
        self.refresh_builds()
        self._load_hardware()
        if getattr(sys, "frozen", False):
            self._check_update_health()
        if ("--selftest" not in sys.argv and "--check-update" not in sys.argv
                and os.environ.get("AMB_DISABLE_CATALOG_WARMUP") != "1"):
            self._warm_catalogs()

    # ------------------------------------------------------------------
    def refresh_builds(self) -> None:
        # Only a result newer than the displayed result may update the library.
        gen = self._refresh_gen = self._refresh_gen + 1

        def fetch():
            lst = self.api.builds()
            recs = {}
            for b in lst[:25]:
                try:
                    recs[b["buildId"]] = self.api.build(b["buildId"])
                except Exception:  # noqa: BLE001
                    pass
            return lst, recs

        def ok(res):
            if gen <= self._refresh_applied:
                # A newer result is already displayed.
                return
            self._refresh_applied = gen
            lst, recs = res
            self.builds = lst
            self.records = recs
            # One corrupt/partial record must never blank the whole library:
            # enrich each pack independently and fall back to the raw summary.
            enriched = []
            for b in lst:
                try:
                    enriched.append(self._enrich(b))
                except Exception:  # noqa: BLE001
                    enriched.append(b)
            self.home.set_builds(enriched)
            self.library.set_builds(enriched)
            self.discover.set_builds(enriched)
            self._update_dl_badge()
            if self.detail_pack_id:
                self._reload_detail(self.detail_pack_id)

        def err(e):
            if gen == self._refresh_gen:
                self.toast(f"[engine] {e}")

        run_async(fetch, ok, err)

    def _enrich(self, b: dict) -> dict:
        rec = self.records.get(b.get("buildId")) or {}
        reqs = rec.get("requirements") or {}
        perf = rec.get("perfEstimate") or {}
        sel = rec.get("selections") or []
        nodes = ((rec.get("graph") or {}).get("nodes") or {})
        # Summary records now carry cover/icon for EVERY pack (Issue 24), so
        # the full-record fetch only adds gallery-grade detail — never blanks
        # the presentation of packs beyond the enrich window.
        icon_url = b.get("iconUrl") or None
        cover_url = rec.get("coverUrl") or b.get("coverUrl") or None
        for s in sel[:6]:
            key = s.get("key") or f"{s.get('provider')}:{s.get('projectId')}"
            project = (nodes.get(key) or {}).get("project") or {}
            # Cover: prefer a real gallery screenshot (CurseForge-style banner),
            # falling back to the project icon so every pack with any image
            # gets a picture instead of a letter tile.
            if not cover_url:
                gallery = project.get("gallery") or []
                if gallery and (gallery[0].get("url") or gallery[0].get("thumbnailUrl")):
                    cover_url = gallery[0].get("url") or gallery[0].get("thumbnailUrl")
            if not icon_url:
                if project.get("iconUrl"):
                    icon_url = project.get("iconUrl")
                elif s.get("provider") == "modrinth" and s.get("projectId"):
                    icon_url = f"https://cdn.modrinth.com/data/{s['projectId']}/icon.png"
            if icon_url and cover_url:
                break
        cover_url = cover_url or icon_url
        mc_version = reqs.get("minecraftVersion") or b.get("minecraftVersion") or ""
        loader_name = reqs.get("loader") or b.get("loader") or ""
        raw_description = rec.get("request") or rec.get("finalReport") or ""
        if str(raw_description).lower().startswith("import:"):
            count = b.get("modCount") or len(sel)
            display_description = (
                f"Imported modpack with {count} mods for Minecraft {mc_version} "
                f"using {str(loader_name).capitalize()}."
            )
        else:
            display_description = raw_description
        perf_load = perf.get("load") or ""
        hardware_fit = f"{str(perf_load).title()} load" if perf_load else (b.get("hardwareFit") or "")
        ram_target = (f"{reqs.get('ramGB')} GB RAM target" if reqs.get("ramGB")
                      else b.get("ramTarget") or ("Hardware detected" if not reqs else ""))
        return {
            **b,
            "name": b.get("name") or rec.get("name"),
            "mcVersion": mc_version,
            "loader": loader_name,
            "loaderVersion": reqs.get("loaderVersion") or "",
            "description": display_description,
            "hardwareFit": hardware_fit,
            "ramTarget": ram_target,
            "iconUrl": icon_url,
            "coverUrl": cover_url,
        }

    def _update_dl_badge(self) -> None:
        active = 0
        for rec in self.records.values():
            for download in rec.get("downloads") or []:
                status = str(download.get("status") or "").lower()
                if status in {"queued", "pending", "downloading", "verifying"}:
                    active += 1
        self._dl_badge.setText(str(active))
        self._dl_badge.setVisible(active > 0)
        self._dl_btn.setText(f"{active} Downloading" if active else "Downloads")
        self._dl_btn.setProperty("active", "true" if active else "false")
        self._dl_btn.setIcon(icon("download", theme.GREEN if active else theme.MUTED, 14))
        theme.polish(self._dl_btn)

    def _select_build(self, build_id: str) -> None:
        self._selected_id = build_id
        self.home.selected_id = build_id
        self.library.selected_id = build_id

    def _seed_ai_builder(self, prompt: str) -> None:
        """A starter concept / Surprise Me brief seeds the AI Builder prompt."""
        self.aibuilder.seed_prompt(prompt)
        self._set_nav("ai-builder")

    # ------------------------------------------------------------------
    def _open_palette(self) -> None:
        """Ctrl+K command palette: navigate anywhere, run quick actions."""
        from PyQt6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout
        if self._palette is not None and self._palette.isVisible():
            self._palette.raise_()
            return
        d = QDialog(self)
        d.setWindowTitle("Command palette")
        d.setModal(False)
        d.resize(560, 420)
        d.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        lay = QVBoxLayout(d)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        search = QLineEdit(d)
        search.setPlaceholderText("Jump to a page or run an action…  (↑↓ to move, Enter to run, Esc to close)")
        search.setMinimumHeight(38)
        search.addAction(icon("search", theme.MUTED, 16), QLineEdit.ActionPosition.LeadingPosition)
        lay.addWidget(search)
        lst = QListWidget(d)
        lst.setFrameShape(QFrame.Shape.NoFrame)
        lst.setStyleSheet("QListWidget { background: transparent; font-size: 13px; }"
                          "QListWidget::item { padding: 8px 10px; border-radius: 6px; }"
                          "QListWidget::item:selected { background: rgba(57,184,106,0.18); color: #FFFFFF; }")
        lay.addWidget(lst, 1)

        # Actions: navigation + a few real quick actions.
        actions = [("navigation", nlabel, lambda n=nid: (d.accept(), self._set_nav(n)))
                   for nid, nlabel, _icon in NAV]
        actions.append(("action", "Check for updates now", lambda: (d.accept(), self._manual_update_check())))
        actions.append(("action", "Re-detect hardware", lambda: (d.accept(), self._redetect_hardware())))
        actions.append(("action", "Import a modpack…", lambda: (d.accept(), self.import_modal.show())))
        actions.append(("action", "New pack…", lambda: (d.accept(), self.new_pack_dialog.show())))
        sel = self.home.selected()
        if sel:
            bid = sel.get("buildId")
            actions.append(("action", f"Play {sel.get('name') or 'selected pack'}",
                            lambda b=bid: (d.accept(), self.play(b))))

        def populate(filter_text: str = "") -> None:
            lst.clear()
            q = filter_text.strip().lower()
            for kind, text, fn in actions:
                if q and q not in text.lower():
                    continue
                item = QListWidgetItem(f"  {text}")
                item.setData(256, fn)
                if kind == "navigation":
                    item.setIcon(icon("arrowright", theme.TEXT2, 14))
                lst.addItem(item)
            if lst.count():
                lst.setCurrentRow(0)

        populate()
        search.textChanged.connect(populate)
        lst.itemActivated.connect(lambda item: (d.accept(), item.data(256)()))
        lst.itemClicked.connect(lambda item: (d.accept(), item.data(256)()))
        lst.keyPressEvent = lambda e: None  # arrows handled by the list natively

        def on_enter() -> None:
            item = lst.currentItem()
            if item is not None:
                fn = item.data(256)
                d.accept()
                fn()
        search.returnPressed.connect(on_enter)
        self._palette = d
        d.finished.connect(lambda _code: setattr(self, "_palette", None))
        d.show()
        search.setFocus()

    # ------------------------------------------------------------------
    def _apply_theme(self, pref: str) -> None:
        """Re-theme the whole window after an Appearance change."""
        theme.set_mode(pref)
        self.setStyleSheet(theme.QSS)
        # Re-polish every widget so dynamic-property styles update in place.
        for w in self.findChildren(QWidget):
            theme.polish(w)
        theme.polish(self)
        self._set_nav(self.active_nav)   # re-color the nav rail
        self._refresh_account_block()
        self._apply_sidebar_margins()

    def _apply_sidebar_state(self, compact: bool) -> None:
        """Apply the sidebar preference from Settings (keep the toggle in sync)."""
        self._sidebar_compact = bool(compact)
        self._apply_sidebar_compact(animate=True)

    # ------------------------------------------------------------------
    def _set_nav(self, nav: str) -> None:
        if nav == "settings":
            # Settings is a floating overlay, never a QStackedWidget page:
            # remember the route it covers, keep the stack untouched, and do
            # not route it through _open_detail(). Closing restores the
            # underlying page via _close_settings().
            if self.active_nav != "settings":
                self._settings_return_nav = self.active_nav
            self.active_nav = nav
            self._paint_nav(nav)
            self.settings.show_overlay()
            return
        self.active_nav = nav
        self._open_detail(None)
        self._paint_nav(nav)
        self.stack.setCurrentWidget(getattr(self, ATTR_BY_NAV[nav]))
        # Downloads/Activity refresh from their real showEvent when the stack
        # shows them — never invoke the lifecycle event manually.
        # Packs must be current the moment the user looks: Home and Library
        # re-read the engine's on-disk index on arrival (async, non-blocking)
        # instead of waiting up to 20 s for the background refresh timer.
        if nav in ("home", "library"):
            self.refresh_builds()

    def _paint_nav(self, nav: str) -> None:
        icon_by_id = {nid: nicon for nid, _nlabel, nicon in NAV}
        for nid, (frame, indicator, ic, nav_label) in self.nav_btns.items():
            active = nid == nav
            selector = f"QFrame#{frame.objectName()}"
            frame.setStyleSheet(
                f"{selector} {{ background: {theme.CARD if active else 'transparent'}; border-radius: 8px; }}"
                f"{selector}:hover {{ background: {theme.HOVER if not active else theme.CARD}; }}")
            indicator.setVisible(active)
            indicator.raise_()
            ic.setPixmap(icon_pixmap(icon_by_id[nid], theme.GREEN if active else theme.MUTED, 16))
            nav_label.setProperty("cls", "nav-label-active" if active else "nav-label")
            theme.polish(nav_label)
        if nav != "settings":
            self._title.setText(TITLES.get(nav, nav.title()))

    def open_detail(self, build_id: str) -> None:
        self._open_detail(build_id)

    def _open_detail(self, build_id: str | None) -> None:
        self.detail_pack_id = build_id
        if self.settings.isVisible():
            self.settings.hide()
        if build_id:
            self._title.setText("Pack Management")
            self.stack.setCurrentWidget(self.packdetail)
            self._reload_detail(build_id)
        else:
            self._title.setText(TITLES.get(self.active_nav, self.active_nav.title()))
            self.stack.setCurrentWidget(getattr(self, ATTR_BY_NAV[self.active_nav]))

    def _reload_detail(self, build_id: str) -> None:
        rec = self.records.get(build_id)
        self.packdetail.load(build_id, rec)

    def _open_add_content(self) -> None:
        """Show the pack-scoped Add Content browser for the pack on screen."""
        bid = self.detail_pack_id
        build = next((b for b in self.builds if b.get("buildId") == bid), None)
        if not build:
            self.toast("Open a pack first.")
            return
        self._title.setText(f"Add Content — {build.get('name') or 'Pack'}")
        self.addcontent.set_pack(build)
        self.stack.setCurrentWidget(self.addcontent)

    def import_pack(self, provider: str, project_id: str) -> None:
        self._run_import(f"Importing {project_id}…",
                         lambda p, c: self.api.import_pack(provider, project_id, None, p, c))

    def import_file(self, path: str) -> None:
        import os
        self._run_import(f"Importing local pack {os.path.basename(path)}…",
                         lambda p, c: self.api.import_file(path, os.path.basename(path), p, c))

    def _run_import(self, label_text: str, worker) -> None:
        """Run an import with the CurseForge-style overlay: live stage/progress,
        a CANCEL button, and a PLAY button that replaces it on success."""
        import threading
        self._import_cancel = threading.Event()
        self._import_state = {"stage": "Preparing import…", "done": 0, "total": 0}
        self.import_overlay.show_import(label_text)
        self._import_timer.start()
        self.toast(label_text)

        def on_progress(stage: str, done: int, total: int) -> None:
            # Worker thread → GUI: only touch the plain dict here; the timer
            # marshals it onto the GUI thread.
            self._import_state["stage"] = stage
            self._import_state["done"] = done
            self._import_state["total"] = total

        def fetch():
            return worker(on_progress, self._import_cancel)

        def ok(res):
            self._import_timer.stop()
            if res.get("cancelled"):
                self.import_overlay.hide()
                self.toast("Import cancelled.")
                self.refresh_builds()
                return
            bid = res.get("buildId")
            n = res.get("modCount", 0)
            extra = []
            if res.get("downloaded"):
                extra.append(f"{res['downloaded']} downloaded")
            if res.get("references"):
                extra.append(f"{res['references']} reference-only")
            if res.get("failed"):
                extra.append(f"{res['failed']} failed")
            summary = f"{n} mods installed" + (f" ({', '.join(extra)})" if extra else "")
            self.import_overlay.set_done(bid, res.get("name") or "pack", summary)
            self.toast(f"Imported {n} mods — pack ready.")
            self.refresh_builds()

        def err(e):
            self._import_timer.stop()
            self.import_overlay.set_error(str(e))
            self.toast(f"[import] {e}")

        run_async(fetch, ok, err)

    def _import_tick(self) -> None:
        if not self.import_overlay.is_importing():
            self._import_timer.stop()
            return
        st = self._import_state
        self.import_overlay.set_progress(st["stage"], st["done"], st["total"])

    def _cancel_import(self) -> None:
        self.import_overlay.set_cancelling()
        if self._import_cancel is not None:
            self._import_cancel.set()

    def delete_pack(self, build_id: str) -> None:
        """Delete a pack from the Library (real delete — instance, downloads,
        exports, worlds). Confirms first; the engine refuses while it runs."""
        rec = self.records.get(build_id) or {}
        name = rec.get("name") or build_id
        confirm = QMessageBox.question(
            self, "Delete pack",
            f"Delete \"{name}\" permanently?\n\nThis removes the instance, all mod jars, "
            f"exports, and any worlds in it. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.toast(f"Deleting {name}…")

        def fetch():
            return self.api.delete_pack(build_id)

        def ok(res):
            self.toast(f"Deleted {name}.")
            if self._selected_id == build_id:
                self._selected_id = None
            if self.detail_pack_id == build_id:
                self._open_detail(None)
            self.refresh_builds()

        def err(e):
            self.toast(f"[delete] {e}")

        run_async(fetch, ok, err)

    def create_pack(self, name: str, mc: str, loader: str, ram_gb: int) -> None:
        """Blank-pack creation from the Library: engine makes the record + instance,
        then the user fills it via the Mod Browser (Discover)."""
        self.toast(f"Creating pack {name or 'Untitled'} — MC {mc}, {loader or 'auto'}, {ram_gb} GB…")

        def fetch():
            return self.api.create_pack(name, mc, loader, ram_gb)

        def ok(res):
            bid = res.get("buildId")
            self.toast(f"Pack \"{res.get('name')}\" created ({res.get('mcVersion')} / {res.get('loader')}, {res.get('ramGB')} GB) — use ADD CONTENT on the pack to add mods.")
            self.refresh_builds()
            if bid:
                self._select_build(bid)
                QTimer.singleShot(400, lambda: self._open_detail(bid))

        def err(e):
            self.toast(f"[new pack] {e}")

        run_async(fetch, ok, err)

    def backup_pack(self, build_id: str) -> None:
        if not build_id:
            return
        self.toast("Saving pack — zipping worlds, configs & visuals…")
        pd = self.packdetail

        def fetch():
            return self.api.backup(build_id)

        def ok(res):
            self.toast(f"Backup saved: {res.get('file')} ({res.get('files')} files, {res.get('bytes', 0) // 1024} KB).")
            if pd._backup_status:
                note = res.get("note") or ""
                pd._backup_status.setText(f"Saved {res.get('file')} — {res.get('files')} files, {res.get('bytes', 0) // 1024} KB." + (f" ({note})" if note else ""))
            if self.detail_pack_id == build_id:
                self._reload_detail(build_id)

        def err(e):
            self.toast(f"[backup] {e}")
            if pd._backup_status:
                pd._backup_status.setText(f"Backup failed: {e}")

        run_async(fetch, ok, err)

    def set_ram(self, build_id: str, ram_gb: int) -> None:
        self.toast(f"Setting RAM to {ram_gb} GB…")

        def fetch():
            return self.api.set_ram(build_id, ram_gb)

        def ok(res):
            self.toast(f"RAM updated to {res.get('ramGB')} GB (applies on next launch).")
            self.refresh_builds()
            if self.detail_pack_id == build_id:
                self._reload_detail(build_id)

        def err(e):
            self.toast(f"[ram] {e}")

        run_async(fetch, ok, err)

    def set_shader_preset(self, build_id: str, preset: str) -> None:
        self.toast(f"Swapping shader to {preset} preset — downloading + re-testing…")

        def fetch():
            return self.api.set_shader_preset(build_id, preset)

        def ok(res):
            self.toast(f"Shader swapped: {res.get('title')} ({res.get('preset')} preset, {res.get('provider')}) — re-test running.")
            self.refresh_builds()
            if self.detail_pack_id == build_id:
                self._reload_detail(build_id)

        def err(e):
            self.toast(f"[shader preset] {e}")

        run_async(fetch, ok, err)

    def set_auto_relaunch(self, build_id: str, enabled: bool) -> None:
        def fetch():
            return self.api.set_auto_relaunch(build_id, enabled)

        def ok(res):
            state = bool(res.get("autoRelaunch"))
            self.toast("Auto-relaunch ON — silently-dying games relaunch once at lower RAM."
                       if state else "Auto-relaunch OFF — games close as before.")
            if self.detail_pack_id == build_id:
                self._reload_detail(build_id)

        def err(e):
            self.toast(f"[auto-relaunch] {e}")

        run_async(fetch, ok, err)

    def ask_ai(self, build_id: str, prompt: str) -> None:
        """Ask-AI: show the non-mutating change plan first; only build on approval.

        The plan tells the user what will change (mods added/removed, RAM,
        risk, what is preserved) before anything is built. Approval runs the
        transactional candidate — the working pack stays untouched until the
        candidate validates and is promoted.
        """
        self.toast("Planning AI change…")

        def fetch():
            return self.api.plan_ai_change(build_id, prompt)

        def ok(plan):
            if not plan.get("changes") and not plan.get("interpretation", {}).get("addFeatures"):
                self.toast("I couldn't map that request to pack changes — try rephrasing.", 7000)
                return
            self._confirm_ai_plan(build_id, prompt, plan)

        def err(e):
            self.toast(f"[plan] {e}")

        run_async(fetch, ok, err)

    def _confirm_ai_plan(self, build_id: str, prompt: str, plan: dict) -> None:
        """Plan preview dialog with APPLY & TEST / MODIFY PLAN / CANCEL."""
        d = QDialog(self)
        d.setWindowTitle("Suggested AI changes")
        d.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        d.resize(600, 480)
        lay = vbox(d, 12, margins=(22, 18, 22, 18))
        lay.addWidget(label(d, "Suggested changes", "h3"))
        interp = plan.get("interpretation") or {}
        ch = plan.get("changes") or {}
        imp = plan.get("impact") or {}
        pres = plan.get("preserved") or {}
        lines = []
        if interp.get("addLabels"):
            lines.append("Add: " + ", ".join(interp["addLabels"]))
        if interp.get("removeLabels"):
            lines.append("Remove: " + ", ".join(interp["removeLabels"]))
        if interp.get("shaderChange"):
            lines.append("Change shader preset")
        if interp.get("ramGB"):
            lines.append(f"Target RAM: {interp['ramGB']} GB")
        body = "\n".join(lines) if lines else "(no feature-level changes recognized)"
        lay.addWidget(label(d, f"You said: “{prompt}”", "sub"))
        bx = QPlainTextEdit(d)
        bx.setReadOnly(True)
        bx.setPlainText(body)
        bx.setMinimumHeight(110)
        lay.addWidget(bx, 1)
        meta = (f"Mods added: {ch.get('modsAdded', 0)}  ·  removed: {ch.get('modsRemoved', 0)}  ·  "
                f"deps est.: {ch.get('dependenciesEstimated', 0)}  ·  RAM → {imp.get('ramTo')} GB  ·  "
                f"confidence {imp.get('confidence')}%  ·  risk {imp.get('risk')}")
        lay.addWidget(label(d, meta, "mono"))
        if pres.get("coreTheme"):
            lay.addWidget(label(d, f"Preserves: {pres.get('coreTheme')} — locked mods stay.", "muted"))
        lay.addWidget(label(d, "The pack is snapshotted first; the current state stays intact until the change validates.", "muted"))
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button(d, "Cancel", "btn-dark")
        cancel.clicked.connect(d.reject)
        modify = button(d, "MODIFY PLAN", "btn-dark", "settings")
        modify.clicked.connect(lambda: (d.accept(), self._open_ai_editor(build_id, prompt)))
        go = button(d, "APPLY & TEST", "btn-primary", "sparkles", theme.BG)
        go.clicked.connect(lambda: (d.accept(), self._apply_ai_change(build_id, prompt)))
        row.addWidget(cancel)
        row.addWidget(modify)
        row.addWidget(go)
        lay.addLayout(row)
        d.exec()

    def _open_ai_editor(self, build_id: str, prompt: str) -> None:
        """MODIFY PLAN: open the plain edit dialog for the same pack."""
        d = QDialog(self)
        d.setWindowTitle("Refine the AI request")
        d.setStyleSheet(f"QDialog {{ background: {theme.CARD}; }}")
        d.resize(520, 240)
        lay = vbox(d, 12, margins=(20, 18, 20, 18))
        lay.addWidget(label(d, "Refine the AI request", "h3"))
        box = QPlainTextEdit(d)
        box.setPlainText(prompt)
        box.setMinimumHeight(90)
        lay.addWidget(box)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button(d, "Cancel", "btn-dark")
        cancel.clicked.connect(d.reject)
        go = button(d, "RE-PLAN", "btn-primary", "sparkles", theme.BG)
        def apply():
            p2 = box.toPlainText().strip()
            if p2:
                self.ask_ai(build_id, p2)
            d.accept()
        go.clicked.connect(apply)
        row.addWidget(cancel)
        row.addWidget(go)
        lay.addLayout(row)
        d.exec()

    def _apply_ai_change(self, build_id: str, prompt: str) -> None:
        """Transactional apply: snapshot → candidate build → promote on PASS."""
        self.toast("Applying AI change (candidate)…")

        def fetch():
            return self.api.apply_ai_change(build_id, prompt)

        def ok(res):
            bid = res.get("candidateBuildId") or ""
            self.toast(f"Candidate build started: {bid} — the pack is snapshotted.")
            self.refresh_builds()
            if bid:
                QTimer.singleShot(800, lambda: self._open_detail(bid))

        def err(e):
            self.toast(f"[apply] {e}")

        run_async(fetch, ok, err)

    def rename_pack(self, build_id: str, name: str) -> None:
        def fetch():
            return self.api.rename(build_id, name)

        def ok(res):
            self.toast(f"Renamed to {res.get('name')}.")
            self.refresh_builds()

        def err(e):
            self.toast(f"[rename] {e}")

        run_async(fetch, ok, err)

    def export_pack(self, build_id: str, filename: str) -> None:
        dest, _ = QFileDialog.getSaveFileName(self, "Save export", filename, "ZIP archive (*.zip);;All files (*)")
        if not dest:
            return
        self.toast("Downloading export artifact…")

        def fetch():
            return self.api.export_file(build_id, filename, dest)

        def ok(n):
            self.toast(f"Saved {filename} ({n // 1024 // 1024} MB).")

        def err(e):
            self.toast(f"[export] {e}")

        run_async(fetch, ok, err)

    def open_evidence(self, build_id: str, filename: str) -> None:
        def fetch():
            return self.api.status(build_id), self.api.evidence(build_id, filename)

        def ok(res):
            st, _text = res
            name = next((b.get("name") for b in self.builds if b.get("buildId") == build_id), "pack")
            self.crash_drawer.show_report(build_id, st, name)

        run_async(fetch, ok, None)

    # ------------------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.launch_overlay._reposition(self.width(), self.height())
        self.import_overlay._reposition(self.width(), self.height())
        self.crash_drawer._reposition(self.width(), self.height())
        self.settings._reposition(self.width(), self.height())
        self._place_toast()
        self._place_update_toast()
        self._place_resize_grip()


def main() -> int:
    # --check-update [url] [--apply-update]: headless self-update flow used
    # by the installer pipeline and power users. Fetches the feed, downloads
    # the installer (size-capped, SHA-256 verified), optionally launches it,
    # and writes update-check.json into the workspace. Exits 0 on success.
    if "--check-update" in sys.argv:
        from engine.core import workspace_dir
        import updater
        import json as _json
        idx = sys.argv.index("--check-update")
        url = (sys.argv[idx + 1] if len(sys.argv) > idx + 1
               and not sys.argv[idx + 1].startswith("-") else updater.update_url())
        res = updater.run_update(url, apply="--apply-update" in sys.argv)
        try:
            out = workspace_dir()
            out.mkdir(parents=True, exist_ok=True)
            (out / "update-check.json").write_text(_json.dumps(res, indent=2), "utf-8")
        except Exception:  # noqa: BLE001
            pass
        os._exit(0 if res.get("ok") else 1)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AI.Modpack.Builder")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("AI Modpack Builder")
    from engine.core import resource_path
    app.setWindowIcon(QIcon(str(resource_path("app.ico"))))
    theme.setup_fonts(app)
    # Apply the saved Appearance preference (dark / light / system) before any
    # widget is built so the whole window renders in the right palette from
    # the first frame.
    try:
        from views.misc import _load_state
        theme.set_mode(str(_load_state().get("theme", "dark")))
    except Exception:  # noqa: BLE001 — never block startup on a theme read
        theme.set_mode("dark")
    app.aboutToQuit.connect(icon_cache.shutdown)
    # One system: the Python engine runs in-process. No Node server, no
    # localhost — the desktop app IS the engine.
    api = PyEngine()
    win = MainWindow(api)
    # Drain async workers before Qt tears down, so a busy engine thread can
    # never post into a half-destroyed poster at exit (native fail-fast).
    app.aboutToQuit.connect(win._teardown)
    win.show()
    # --selftest: boot the whole app offscreen, verify the in-process engine
    # and real builds load, write a JSON verdict to the workspace, then exit.
    # Used by the installer pipeline to smoke-test the installed bundle.
    if "--selftest" in sys.argv:
        from engine.core import workspace_dir
        import json as _json
        res = {"ok": False, "checks": []}
        try:
            health = api.health()
            res["checks"].append({"name": "engine health", "ok": bool(health)})
            bids = [b.get("buildId") for b in (api.builds() or [])]
            # A fresh install starts with an empty library — 0 builds is
            # legitimate. The load itself must not raise.
            res["checks"].append({"name": "builds load", "ok": True, "count": len(bids)})
            res["checks"].append({"name": "window constructed", "ok": win.isVisible()})
            # The settings surface must lay on top of the page and close like
            # a modal sheet (Escape) — the interaction the overlay release
            # shipped. Visibility is set synchronously, so this needs no
            # event-loop waiting.
            try:
                win._set_nav("settings")
                app.processEvents()
                shown = win.settings.isVisible() and bool(win.settings._overlay)
                esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(win, esc)
                app.processEvents()
                closed = not win.settings.isVisible()
                res["checks"].append({
                    "name": "settings overlay + Escape close",
                    "ok": shown and closed, "shown": shown, "closed": closed})
            except Exception as _e:  # noqa: BLE001
                res["checks"].append({"name": "settings overlay + Escape close",
                                      "ok": False, "error": str(_e)})
            # The single most important property of an installed app: its
            # per-user workspace must be creatable and writable.
            ws = workspace_dir()
            ws.mkdir(parents=True, exist_ok=True)
            probe = ws / "selftest-probe.tmp"
            probe.write_text("ok", "utf-8")
            probe.unlink()
            res["checks"].append({"name": "workspace writable", "ok": True, "path": str(ws)})
            # Installed-bundle guarantee: the shipped app must be the Python
            # engine alone — zero legacy Node-era files, and the newest engine
            # modules (shader + resource-pack selection, shared errors) present.
            if getattr(sys, "frozen", False):
                bundle = Path(sys.executable).resolve().parent
                legacy = [n for n in ("src", "web", "node_modules", "package.json",
                                      "tsconfig.json", "api.py") if (bundle / n).exists()]
                res["checks"].append({"name": "no legacy Node files in bundle",
                                      "ok": not legacy, "found": legacy})
                # PyInstaller compiles modules into the PYZ archive (no loose
                # .py files), so "bundled" is proven by importability inside
                # the frozen app — the real guarantee that the newest engine
                # modules shipped.
                missing_mods = []
                for _mod in ("engine.shaders", "engine.resource_packs", "engine.errors"):
                    try:
                        __import__(_mod)
                    except Exception:
                        missing_mods.append(_mod)
                res["checks"].append({"name": "shader/resource-pack engine importable",
                                      "ok": not missing_mods, "missing": missing_mods})
                # Modrinth is the zero-configuration provider. CurseForge is an
                # optional second provider for unsigned/dev builds, while the
                # signed release pipeline separately requires the publisher key.
                try:
                    from engine.providers.settings import SettingsStore
                    src = SettingsStore().curseforge_key_source()
                    res["checks"].append({
                        "name": "provider configuration readable",
                        "ok": True,
                        "curseforgeAvailable": bool(src) and src != "none",
                        "source": src,
                    })
                except Exception as _ke:  # noqa: BLE001
                    res["checks"].append({"name": "provider configuration readable",
                                          "ok": False, "error": str(_ke)})
            res["ok"] = all(c["ok"] for c in res["checks"])
        except Exception as e:  # noqa: BLE001
            res["error"] = str(e)
        try:
            out = workspace_dir()
            out.mkdir(parents=True, exist_ok=True)
            (out / "selftest.json").write_text(_json.dumps(res, indent=2), "utf-8")
        except Exception as e:  # noqa: BLE001
            res["error"] = (res.get("error") or "") + f" write-failed: {e}"
        # Exit without Qt/Python teardown: the result is already flushed to
        # disk, and tearing down a live QApplication (window + timers) after a
        # headless selftest can hit Qt fail-fast paths on Windows.
        os._exit(0 if res["ok"] else 1)
    # Installed builds check the update feed once per day in the background.
    if getattr(sys, "frozen", False):
        QTimer.singleShot(5000, win._auto_check_update)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
