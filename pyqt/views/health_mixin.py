"""Engine health / auto-restart / catalog-warmup mixin for MainWindow.
"""
from __future__ import annotations

import os
import threading

import theme
from common import icon_cache, icon_pixmap, run_async


class HealthMixin:
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
                    # Rich release-notes toast: title + rendered notes + a Review
                    # action that lands in Settings → Updates (notes shown, install
                    # confirmed from there). The plain-text one-liner toast is gone.
                    self.toast_update(res.get("latest") or "?",
                                      res.get("notes") or "", self._manual_update_check)

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

    def _manual_update_check(self) -> None:
            self._set_nav("settings")
            self.settings._set_sub("updates")
            QTimer.singleShot(200, self.settings._do_update_check)

    def _redetect_hardware(self) -> None:
            self._set_nav("settings")
            self.settings._set_sub("minecraft")
            QTimer.singleShot(200, self.settings._redetect)


