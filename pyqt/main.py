"""AI Minecraft Launcher — PyQt6 desktop client for the AI Modpack Builder engine.

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

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel,
                             QMainWindow, QMessageBox, QPushButton, QStackedWidget,
                             QSizeGrip, QVBoxLayout, QWidget)

import theme
import minecraft_auth
from engine.bridge import PyEngine
from common import (avatar, button, hbox, icon_cache, icon_pixmap, label, pill,
                    run_async, vbox)
from icons import icon
from views.aibuilder import AIBuilderView
from views.discover import DiscoverView
from views.home import HomeView
from views.library import LibraryView
from views.misc import ActivityView, DownloadsView, SettingsView
from views.overlays import (AccountModal, CrashDrawer, ImportModal, ImportOverlay,
                            LaunchOverlay, NewPackDialog)
from views.packdetail import PackDetailView

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


class AppTopBar(QFrame):
    """Frameless-window drag surface backed by the native system move loop."""

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            window.showNormal() if window.isMaximized() else window.showMaximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, api: PyEngine):
        super().__init__()
        self.api = api
        self.builds: list[dict] = []
        self.records: dict[str, dict] = {}
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

        self.setWindowTitle("AI Minecraft Launcher")
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "app.ico")))
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.resize(1365, 840)
        self.setMinimumSize(1080, 700)
        self.setStyleSheet(theme.QSS)

        # overlays (created before the sidebar wires its account button)
        self.account_modal = AccountModal(self)
        self.import_modal = ImportModal(self)
        self.new_pack_dialog = NewPackDialog(self)
        self.launch_overlay = LaunchOverlay(self)
        self.import_overlay = ImportOverlay(self)
        self.crash_drawer = CrashDrawer(self, api)

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
        self.aibuilder = AIBuilderView(api)
        self.downloads = DownloadsView(api)
        self.activity = ActivityView(api)
        self.settings = SettingsView(api)
        self.packdetail = PackDetailView(api)
        for w in (self.home, self.library, self.discover, self.aibuilder,
                  self.downloads, self.activity, self.settings, self.packdetail):
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

    def _place_resize_grip(self) -> None:
        if not hasattr(self, "_resize_grip"):
            return
        self._resize_grip.move(
            self.centralWidget().width() - self._resize_grip.width(),
            self.centralWidget().height() - self._resize_grip.height(),
        )
        self._resize_grip.raise_()

    def _auto_check_update(self, stamp: str | None = None, hours: int = 24) -> None:
        """Throttled background update check for installed builds.

        Runs at startup (once per 24 h) and periodically (every 2 h while the
        app is open) when a feed is configured (AMB_UPDATE_URL, the updateUrl
        setting, or the embedded default); announces only if a newer version
        is available. Silent in dev mode.
        """
        from engine.core import data_dir
        import updater
        from views.misc import _load_state
        st = _load_state() or {}
        if not st.get("autoCheckUpdates", True):
            return  # "Check for updates on startup" toggle is off
        dd = data_dir()
        if not updater.should_auto_check(dd, hours=hours, stamp=stamp or updater.CHECK_STAMP):
            return
        updater.stamp_check(dd, stamp or updater.CHECK_STAMP)
        # Priority: env override → the user's Settings URL → the embedded
        # default feed. The default must never shadow a custom feed.
        url = os.environ.get("AMB_UPDATE_URL", "").strip()
        if not url:
            url = st.get("updateUrl") or ""
        if not url:
            url = updater.update_url()
        if not url:
            return

        def work():
            return updater.check(url)

        def ok(res):
            if res.get("available"):
                notes = (res.get("notes") or "").strip()
                first = notes.splitlines()[0][:140] if notes else ""
                msg = f"Update {res.get('latest')} available — install it in Settings → Updates."
                if first:
                    msg = f"Update {res.get('latest')} available: {first}… Install in Settings → Updates."
                self.toast(msg, 9000)

        run_async(work, ok, lambda e: None)

    def _periodic_update_check(self) -> None:
        """Every 2 h while the launcher is open, reuse the throttled check with
        its own stamp so it does not collide with the once-per-24 h startup
        check (and never fires if the user disabled auto-checks)."""
        import updater
        self._auto_check_update(stamp=updater.PERIODIC_STAMP, hours=2)

    def _check_update_health(self) -> None:
        """After an update applies, the next boot health-checks the engine and
        clears the marker; a failed health probe tells the user where to roll
        back instead of leaving them with a broken install silently."""
        from engine.core import data_dir
        import updater
        from product_config import APP_VERSION as CUR_VERSION
        from views.misc import _load_state, _save_state
        dd = data_dir()
        applied = updater.applied_marker(dd)
        if not applied:
            return

        def work():
            try:
                return bool(self.api.health())
            except Exception:  # noqa: BLE001
                return False

        def ok(healthy: bool) -> None:
            if healthy:
                if applied != CUR_VERSION:
                    self.toast(
                        f"Update v{applied} did not take effect — still on v{CUR_VERSION}. "
                        "Open Settings → Updates to retry or restore the previous version.", 10000)
                updater.clear_applied_marker(dd)
                return
            self.toast(
                "The last update did not pass its health check — open Settings → Updates "
                "and use Restore previous version.", 12000)

        run_async(work, ok, lambda e: None)

    # ------------------------------------------------------------------
    def _build_sidebar(self) -> QFrame:
        sb = QFrame(self)
        sb.setProperty("cls", "sidebar")
        theme.polish(sb)
        sb.setFixedWidth(224)
        v = vbox(sb, 0)
        v.setContentsMargins(0, 0, 0, 0)

        # logo header from the supplied launcher design
        logo = QFrame(sb)
        logo.setObjectName("logoHeader")
        logo.setFixedHeight(58)
        logo.setStyleSheet(f"QFrame#logoHeader {{ background: {theme.PANEL}; border: none; border-bottom: 1px solid {theme.BORDER}; }}")
        lr = hbox(logo, 10, margins=(20, 0, 16, 0))
        mark = QFrame(logo)
        mark.setProperty("cls", "logo-badge")
        mark.setFixedSize(32, 32)
        theme.polish(mark)
        mark_lay = hbox(mark, 0, margins=0)
        z = QLabel(mark)
        z.setPixmap(icon_pixmap("zap", theme.GREEN, 17))
        z.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark_lay.addWidget(z)
        lr.addWidget(mark)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = label(logo, "AI MINECRAFT", "logo-title")
        col.addWidget(t)
        sub = label(logo, "Launcher Engine", "logo-sub")
        col.addWidget(sub)
        lr.addLayout(col)
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
            bl.addStretch(1)
            if nid == "ai-builder":
                badge = label(b, "AI", "nav-badge-ai")
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                bl.addWidget(badge)
            if nid == "downloads":
                self._dl_badge = label(b, "", "nav-badge")
                self._dl_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._dl_badge.setVisible(False)
                bl.addWidget(self._dl_badge)
            b.mousePressEvent = lambda e, n=nid: self._set_nav(n)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            nv.addWidget(b)
            self.nav_btns[nid] = (b, indicator, ic, nav_label)
        v.addWidget(navwrap)
        v.addStretch(1)

        # account block
        account_wrap = QFrame(sb)
        account_wrap.setProperty("cls", "sidebar-divider")
        theme.polish(account_wrap)
        aw = vbox(account_wrap, 0, margins=(10, 10, 10, 10))
        acc = QFrame(account_wrap)
        acc.setProperty("cls", "account-card")
        theme.polish(acc)
        ar = hbox(acc, 10, margins=(8, 8, 6, 6))
        self._acc_icon = QLabel(acc)
        self._acc_icon.setFixedSize(32, 32)
        ar.addWidget(self._acc_icon)
        col2 = QVBoxLayout()
        col2.setSpacing(0)
        self._acc_name = label(acc, "N/A", "h3")
        col2.addWidget(self._acc_name)
        self._acc_status = label(acc, "Status: N/A", "muted")
        col2.addWidget(self._acc_status)
        ar.addLayout(col2, 1)
        ab = button(acc, "", "iconbtn", "usercheck", theme.GREEN)
        ab.clicked.connect(self.account_modal.show)
        ar.addWidget(ab)
        aw.addWidget(acc)
        v.addWidget(account_wrap)
        self._refresh_account_block()
        return sb

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
            self._acc_status.setText("Offline profile" if name != "N/A" else "Not configured")
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
        self.home.navigate.connect(self._set_nav)
        self.home.import_requested.connect(self.import_modal.show)
        self.home.select_build.connect(self._select_build)
        self.home.seed_requested.connect(self._seed_ai_builder)

        self.library.play_requested.connect(self.play)
        self.library.stop_requested.connect(self.stop)
        self.library.open_detail.connect(self.open_detail)
        self.library.delete_requested.connect(self.delete_pack)
        self.library.import_requested.connect(self.import_modal.show)
        self.library.new_pack_requested.connect(self.new_pack_dialog.show)
        self.library.navigate_ai.connect(lambda: self._set_nav("ai-builder"))
        self.library.select_build.connect(self._select_build)

        self.packdetail.back_requested.connect(lambda: self._open_detail(None))
        self.packdetail.play_requested.connect(self.play)
        self.packdetail.stop_requested.connect(self.stop)
        self.packdetail.remove_mod.connect(self.remove_mod)
        self.packdetail.retest_requested.connect(self.retest)
        self.packdetail.repair_requested.connect(self.repair)
        self.packdetail.navigate_discover.connect(lambda: self._set_nav("discover"))
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
        self.settings.settings_changed.connect(lambda _patch: self.aibuilder._load_hardware())
        self.settings.manage_account_requested.connect(self.account_modal.show)

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
        self.account_modal.finished.connect(lambda _r: self._refresh_account_block())
        self.account_modal.account_changed.connect(self._refresh_account_block)

    def _open_provider_settings(self) -> None:
        self._set_nav("settings")
        self.settings.open_section("providers")

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

    def _bootstrap(self) -> None:
        self._check_health()
        self.refresh_builds()
        self._load_hardware()
        if getattr(sys, "frozen", False):
            self._check_update_health()
        if ("--selftest" not in sys.argv and "--check-update" not in sys.argv
                and os.environ.get("AMB_DISABLE_CATALOG_WARMUP") != "1"):
            self._warm_catalogs()

    def _warm_catalogs(self) -> None:
        """Prefetch the default Discover catalogs in the background so the
        first browse of mods / modpacks / shaders / resource packs / worlds
        renders instantly: the API responses land in the provider disk cache
        and the top icons in the icon cache while the user does anything else."""
        def work() -> None:
            combos = [
                ("mod", "1.20.1"), ("mod", "1.21.1"), ("modpack", "1.20.1"),
                ("shader", "1.20.1"), ("resourcepack", "1.20.1"), ("world", "1.20.1"),
            ]
            try:
                for ctype, mc in combos:
                    try:
                        r = self.api.search(q="", provider="all", mc=mc, loader="all", type=ctype)
                    except Exception:  # noqa: BLE001
                        continue
                    if r.get("error") and not r.get("hits"):
                        continue
                    for h in (r.get("hits") or [])[:24]:
                        u = h.get("iconUrl")
                        if u:
                            icon_cache.request(u, None, 48)
            finally:
                self._warm_done.set()

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------
    def _check_health(self) -> None:
        was_online = self._online

        def fetch():
            return self.api.health()

        def ok(ok_: bool):
            if ok_:
                if not was_online:
                    # Back online (the in-process engine is always with us) —
                    # repopulate the views.
                    self._retry_timer.stop()
                    self._restart_pending = False
                    self._restart_attempts = 0
                    self._set_net(True, "In-process")
                    self._net_pill.setToolTip("The Python engine runs inside this app — no separate server")
                    self.refresh_builds()
                    self._load_hardware()
                else:
                    self._set_net(True, "In-process")
            else:
                self._set_net(False)
                if was_online:
                    self.toast("Engine health check failed — retrying…")
                self._schedule_engine_restart()

        def err(_e):
            ok(False)

        run_async(fetch, ok, err)

    def _set_net(self, online: bool, text: str | None = None) -> None:
        self._online = online
        self._net_text.setText(text if text is not None else ("Online" if online else "Offline"))
        self._net_text.setProperty("cls", "top-mono-green" if online else "top-mono-warn")
        theme.polish(self._net_text)
        self._net_icon.setPixmap(icon_pixmap("wifi" if online else "wifioff",
                                             theme.GREEN if online else theme.WARNING, 14))

    # ------------------------------------------------------------------
    # Engine auto-restart: when the health check fails, count down, start
    # the engine, and keep retrying until the pill flips back to Online.
    # ------------------------------------------------------------------
    def _schedule_engine_restart(self) -> None:
        if self._restart_pending:
            return
        self._restart_pending = True
        self._retry_in = 15 if self._restart_attempts >= 3 else 5
        self._net_pill.setToolTip("The launcher engine is down — the launcher restarts it automatically.")
        self._retry_timer.start()
        self._set_net(False, f"Offline · retry {self._retry_in}s")

    def _retry_tick(self) -> None:
        if not self._restart_pending:
            self._retry_timer.stop()
            return
        self._retry_in -= 1
        if self._retry_in <= 0:
            self._restart_pending = False
            self._retry_timer.stop()
            self._try_start_engine()
        else:
            self._set_net(False, f"Offline · retry {self._retry_in}s")

    def _try_start_engine(self) -> None:
        self._set_net(False, "Offline · starting…")
        self._net_pill.setToolTip("Waiting for the launcher engine to come up…")

        def work():
            # The Python engine runs inside this process, so there is no
            # separate engine to respawn — health is authoritative.
            return ("online", "") if self.api.health() else ("error", "in-process engine unhealthy")

        def ok(res):
            status, note = res
            self._restart_attempts += 1
            if status == "online":
                self._restart_attempts = 0
                self._set_net(True)
                self.refresh_builds()
            else:
                self._set_net(False, "Offline · engine failed")
                self._net_pill.setToolTip(f"Engine check failed: {note}")
                self._restart_pending = False  # next health tick retries

        run_async(work, ok, lambda e: self._set_net(False, "Offline · retry failed"))

    def _load_hardware(self) -> None:
        def fetch():
            return self.api.hardware()

        def ok(hw):
            self._hardware = hw.get("effective") or {}
            self.home.set_hardware(self._hardware)

        run_async(fetch, ok, None)

    # ------------------------------------------------------------------
    def refresh_builds(self) -> None:
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
            lst, recs = res
            self.builds = lst
            self.records = recs
            enriched = [self._enrich(b) for b in lst]
            self.home.set_builds(enriched)
            self.library.set_builds(enriched)
            self.discover.set_builds(enriched)
            self._update_dl_badge()
            if self.detail_pack_id:
                self._reload_detail(self.detail_pack_id)

        def err(e):
            self.toast(f"[engine] {e}")

        run_async(fetch, ok, err)

    def _enrich(self, b: dict) -> dict:
        rec = self.records.get(b.get("buildId")) or {}
        reqs = rec.get("requirements") or {}
        perf = rec.get("perfEstimate") or {}
        sel = rec.get("selections") or []
        nodes = ((rec.get("graph") or {}).get("nodes") or {})
        icon_url = None
        for s in sel[:6]:
            key = s.get("key") or f"{s.get('provider')}:{s.get('projectId')}"
            project = (nodes.get(key) or {}).get("project") or {}
            if project.get("iconUrl"):
                icon_url = project.get("iconUrl")
                break
            if s.get("provider") == "modrinth" and s.get("projectId"):
                icon_url = f"https://cdn.modrinth.com/data/{s['projectId']}/icon.png"
                break
        mc_version = reqs.get("minecraftVersion") or ""
        loader_name = reqs.get("loader") or ""
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
        hardware_fit = f"{str(perf_load).title()} load" if perf_load else ""
        ram_target = f"{reqs.get('ramGB')} GB RAM target" if reqs.get("ramGB") else "Hardware detected"
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
    def _set_nav(self, nav: str) -> None:
        self.active_nav = nav
        self._open_detail(None)
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
        self._title.setText(TITLES.get(nav, nav.title()))
        self.stack.setCurrentWidget(getattr(self, ATTR_BY_NAV[nav]))
        if nav in ("downloads", "activity", "settings"):
            getattr(self, ATTR_BY_NAV[nav]).showEvent(None)

    def open_detail(self, build_id: str) -> None:
        self._open_detail(build_id)

    def _open_detail(self, build_id: str | None) -> None:
        self.detail_pack_id = build_id
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

    # ------------------------------------------------------------------
    # Launcher
    # ------------------------------------------------------------------
    def _launch_identity(self) -> tuple[str | None, dict | None]:
        """Resolve the selected account inside a worker thread before launch."""
        from views.misc import _load_state
        st = _load_state()
        if st.get("accountMode") == "microsoft":
            client_id = minecraft_auth.configured_client_id()
            return None, minecraft_auth.get_minecraft_session(client_id)
        username = str(st.get("accountName") or "").strip()
        return username or None, None

    def play(self, build_id: str) -> None:
        if not build_id:
            return
        # Concurrent packs are allowed: each launch has its own isolated
        # instance, pid, launch state and logs. The overlay tracks the most
        # recently launched pack; per-pack status is on Pack Detail.
        self._launching = build_id
        self._launch_ui_applied = False
        name = next((b.get("name") for b in self.builds if b.get("buildId") == build_id), "pack")
        self.launch_overlay.show_launch(name)
        self.toast(f"Launching {name}…")

        def fetch():
            username, auth = self._launch_identity()
            return self.api.play(build_id, username, auth)

        def ok(res):
            self.toast(f"Launched (pid {res.get('pid')})")
            self._poll.start()

        def err(e):
            self.launch_overlay.apply_status({"error": str(e), "phase": "error"})
            self.toast(f"[launch] {e}")

        run_async(fetch, ok, err)

    def stop(self, build_id: str) -> None:
        def fetch():
            return self.api.stop(build_id)

        def ok(res):
            self.toast("Stopped instance.")
            self._poll.stop()
            self.launch_overlay.hide()
            self.crash_drawer.hide()
            self._launching = None
            self.refresh_builds()

        def err(e):
            self.toast(f"[stop] {e}")

        run_async(fetch, ok, err)

    def _poll_launch(self) -> None:
        if not self._launching:
            self._poll.stop()
            return
        bid = self._launching

        def fetch():
            return self.api.status(bid)

        def ok(st):
            self.launch_overlay.apply_status(st)
            if self.detail_pack_id == bid:
                self.packdetail.set_status(st)
            err = st.get("error")
            if not st.get("running") and not st.get("starting") and (st.get("phase") in (None, "stopped", "idle") or err):
                self._poll.stop()
                self.refresh_builds()
                # On a crash keep _launching set so the crash drawer (VIEW
                # CRASH REPORT / ADD MISSING MODS) still works; only a stop()
                # or a new play() clears it.
                if not err:
                    QTimer.singleShot(1200, self.launch_overlay.hide)
            if st.get("running"):
                if not self._launch_ui_applied:
                    from views.misc import _load_state
                    launcher_state = _load_state()
                    self._launch_ui_applied = True
                    if launcher_state.get("closeOnLaunch"):
                        self.close()
                    elif launcher_state.get("minimizeOnLaunch"):
                        self.showMinimized()
                self.refresh_builds()

        def err(e):
            self._poll.stop()
            self.launch_overlay.hide()
            self.toast(f"[status] {e}")

        run_async(fetch, ok, err)

    def _open_crash_drawer(self) -> None:
        if not self._launching:
            return

        def fetch():
            return self.api.status(self._launching)

        def ok(st):
            name = next((b.get("name") for b in self.builds if b.get("buildId") == self._launching), "pack")
            self.crash_drawer.show_report(self._launching, st, name)

        run_async(fetch, ok, None)

    def fix_missing(self) -> None:
        bid = self._launching or self.crash_drawer._build_id
        if not bid:
            return
        self.crash_drawer.hide()
        self.toast("Adding missing mods & relaunching…")
        self.launch_overlay.show_launch("repair")

        def fetch():
            username, auth = self._launch_identity()
            return self.api.add_missing(bid, username=username, auth=auth)

        def ok(res):
            self.toast(res.get("summary") or "Dependencies added — relaunching.")
            self._launching = bid
            self._poll.start()
            self.refresh_builds()

        def err(e):
            self.toast(f"[repair] {e}")
            self.launch_overlay.hide()

        run_async(fetch, ok, err)

    def repair(self, build_id: str) -> None:
        self.toast("Running full repair & relaunch (crash logs → root cause → fix → retest)…")
        self.launch_overlay.show_launch("repair scan")
        self._launching = build_id

        def fetch():
            username, auth = self._launch_identity()
            return self.api.fix(build_id, username=username, auth=auth)

        def ok(res):
            self.toast(res.get("summary") or "Repair finished.")
            self._poll.start()
            self.refresh_builds()

        def err(e):
            self.toast(f"[repair] {e}")
            self.launch_overlay.hide()
            self._poll.start()

        run_async(fetch, ok, err)

    # ------------------------------------------------------------------
    # Mod management
    # ------------------------------------------------------------------
    def add_mod(self, build_id: str, provider: str, project_id: str, _version_id, mtype) -> None:
        if not build_id:
            self.toast("Pick a target pack first (see Discover drawer).")
            return
        self.toast(f"Adding {project_id} to pack — resolving dependencies…")

        def fetch():
            return self.api.add_mod(build_id, provider, project_id, type=mtype)

        def ok(res):
            added = [a.get("title") for a in (res.get("added") or [])]
            deps = [a.get("title") for a in (res.get("dependencies") or [])]
            msg = f"Added {', '.join(added)}" + (f" + deps {', '.join(deps)}" if deps else "")
            self.toast(msg or "Mod added.")
            self.refresh_builds()
            if self.detail_pack_id == build_id:
                self._reload_detail(build_id)

        def err(e):
            self.toast(f"[add] {e}")

        run_async(fetch, ok, err)

    def remove_mod(self, build_id: str, slug: str, mtype) -> None:
        def fetch():
            return self.api.remove_mod(build_id, slug, type=mtype)

        def ok(res):
            self.toast(f"Removed {slug}.")
            self.refresh_builds()
            if self.detail_pack_id == build_id:
                self._reload_detail(build_id)

        def err(e):
            self.toast(f"[remove] {e}")

        run_async(fetch, ok, err)

    def retest(self, build_id: str) -> None:
        self.toast("Re-testing pack (real launch)…")

        def fetch():
            return self.api.retest(build_id)

        def ok(res):
            self.toast(res.get("summary") or f"Re-test: {res.get('status')}")
            self.refresh_builds()

        def err(e):
            self.toast(f"[retest] {e}")

        run_async(fetch, ok, err)

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
            self.toast(f"Pack \"{res.get('name')}\" created ({res.get('mcVersion')} / {res.get('loader')}, {res.get('ramGB')} GB) — add mods from Discover.")
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
        self._place_toast()
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
    app.setApplicationName("AI Minecraft Launcher")
    from engine.core import resource_path
    app.setWindowIcon(QIcon(str(resource_path("app.ico"))))
    theme.setup_fonts(app)
    app.aboutToQuit.connect(icon_cache.shutdown)
    # One system: the Python engine runs in-process. No Node server, no
    # localhost — the desktop app IS the engine.
    api = PyEngine()
    win = MainWindow(api)
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
