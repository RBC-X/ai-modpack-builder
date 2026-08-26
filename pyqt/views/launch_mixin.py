"""Launch / stop / repair / mod-management actions mixin for MainWindow.
"""
from __future__ import annotations

import minecraft_auth
from PyQt6.QtCore import QTimer

from common import run_async


class LaunchMixin:
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
            self.launch_overlay.show_launch(name, build_id)
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
                # Only the active launch may update the overlay or poll lifecycle.
                if bid != self._launching:
                    return
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
                if bid != self._launching:
                    return
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
            self.launch_overlay.show_launch("repair", bid)

            def fetch():
                username, auth = self._launch_identity()
                return self.api.add_missing(bid, username=username, auth=auth)

            def ok(res):
                self.toast(res.get("summary") or "Dependencies added — relaunching.")
                if res.get("relaunch"):
                    # add_missing terminated the stale crashed JVM; honour the
                    # button label and actually start the game again.
                    self.play(bid)
                    return
                self._launching = bid
                self._poll.start()
                self.refresh_builds()

            def err(e):
                self.toast(f"[repair] {e}")
                self.launch_overlay.hide()

            run_async(fetch, ok, err)

    def repair(self, build_id: str) -> None:
            self.toast("Running full repair & relaunch (crash logs → root cause → fix → retest)…")
            self.launch_overlay.show_launch("repair scan", build_id)
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


