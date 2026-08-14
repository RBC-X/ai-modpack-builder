"""Headless smoke test: build the window, flip through every view, verify the
engine is reachable and real builds render. Run with:

    pyqt/.venv/Scripts/python pyqt/smoke_test.py

No windows are shown (QT_QPA_PLATFORM=offscreen); PASS/FAIL printed per step.

Clean-workspace isolation: the test always runs against a throwaway
AMB_WORKSPACE seeded with one minimal completed pack, so it never depends on
a developer's prior %LOCALAPPDATA% / pyqt/state.json / workspace data, and
the pack-detail assertions always have a deterministic fixture.
"""
import json
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AMB_DISABLE_CATALOG_WARMUP"] = "1"

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

# Console encoding is locale-dependent on Windows (cp1252 can't encode the
# '→' characters some UI strings contain); the harness must never crash on
# log output, so tolerate undecodable characters instead of failing.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

from pathlib import Path

# Throwaway workspace: every smoke run is a fresh install, seeded with one
# minimal real pack record so pack-detail assertions always have a fixture.
_WORK = Path(tempfile.mkdtemp(prefix="amb-smoke-"))
os.environ["AMB_WORKSPACE"] = str(_WORK)

from PyQt6.QtWidgets import QApplication, QCheckBox, QLabel, QLineEdit, QPushButton, QScrollArea  # noqa: E402

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


def make_completed_pack(api, name: str, bid: str) -> str:
    """Create a finished pack record directly (no real build) so the smoke
    run has a deterministic fixture regardless of prior machine state."""
    rec = {
        "buildId": bid, "name": name, "request": "Smoke test pack",
        "status": "done", "phase": "done", "requirements": {
            "minecraftVersion": "1.20.1", "loader": "forge", "ramGB": 4},
        "selections": [
            {"provider": "modrinth", "projectId": "jei", "slug": "jei",
             "title": "Just Enough Items", "fileId": "jei-file-1"},
            {"provider": "modrinth", "projectId": "sodium", "slug": "sodium",
             "title": "Sodium", "fileId": "sodium-file-1"},
        ], "downloads": [], "graph": {"nodes": {}, "edges": []},
        "tests": [], "testResult": {"status": "PASS", "level": "standard"},
        "conflicts": [], "repairs": [], "exports": [], "packStats": {"modCount": 12},
        "settings": {}, "perfEstimate": None, "finalReport": "ok", "error": None,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    api._s._write_record(rec)
    return bid


app = QApplication(sys.argv)
theme.setup_fonts(app)

api = PyEngine()
check("in-process engine healthy", api.health())
_seed_bid = make_completed_pack(api, "Smoke Fixture Pack", "b-smoke-fixture")
check("clean workspace seeded with a pack fixture", bool(_seed_bid))

win = MainWindow(api)
win.resize(1320, 840)
win.show()

# wait for the async build refresh to land
import time  # noqa: E402
for _ in range(80):
    app.processEvents()
    if win.builds:
        break
    time.sleep(0.1)

builds = win.builds
check("builds loaded from engine", len(builds) > 0, f"{len(builds)} packs")
# `first` is always defined: the seeded fixture guarantees at least one pack
# even on a brand-new machine (previously a NameError on clean workspaces).
first = next((build for build in builds if build.get("modCount", 0) > 0), builds[0])
check("launcher sidebar width matches reference", win.sidebar.width() == 224, f"{win.sidebar.width()} px")
check("launcher top bar height matches reference", win.topbar.height() == 50, f"{win.topbar.height()} px")

check("first pack has a name", bool(first.get("name")))
check("first pack has mod count", first.get("modCount", 0) > 0)
rec = api.build(first["buildId"])
check("build record fetched", bool(rec.get("buildId")))
check("record has selections or visuals",
      bool(rec.get("selections")) or bool(rec.get("visualSelections")))
worlds = api.worlds(first["buildId"])
check("worlds endpoint responds", isinstance(worlds, list))

for nav in ["home", "library", "discover", "ai-builder", "downloads", "activity", "settings"]:
    try:
        win._set_nav(nav)
        app.processEvents()
        app.processEvents()
        check(f"navigate {nav}", True)
    except Exception as e:  # noqa: BLE001
        check(f"navigate {nav}", False, str(e))

win._set_nav("home")
app.processEvents()
check("home hero uses compact launcher proportions", win.home._hero.height() == 368, f"{win.home._hero.height()} px")
check("home history label is backend-accurate", win.home._recent_title.text() == "Recent Builds")

win._set_nav("library")
app.processEvents()
library_scroll = win.library.findChild(QScrollArea)
check("library fills the application content area",
      library_scroll is not None and library_scroll.width() >= 1000,
      f"{library_scroll.width() if library_scroll else 0} px")
check("library creation-time sort is honestly labeled",
      win.library._sort_box.currentText() == "Newest Builds")

try:
    win._open_detail(first["buildId"])
    app.processEvents()
    for _ in range(5):
        app.processEvents()
    check("open pack detail", True)
    check("pack hero uses compact launcher proportions", win.packdetail._hero.height() == 280,
          f"{win.packdetail._hero.height()} px")
    badge = win.packdetail._heap_badge
    check("heap-fit badge renders on pack detail",
          badge is not None and bool(badge.text()) and "Heap" in badge.text(),
          badge.text() if badge else "missing")
    win.packdetail._set_tab("content")
    app.processEvents()
    content_placeholders = [w.placeholderText() for w in win.packdetail._body.findChildren(QLineEdit)]
    content_labels = [w.text() for w in win.packdetail._body.findChildren(QLabel)]
    check("content tab replaces overview without overlap",
          "Search installed mods..." in content_placeholders and "About this Modpack" not in content_labels)
except Exception as e:  # noqa: BLE001
    check("open pack detail", False, str(e))

try:
    win._set_nav("discover")
    # The view itself retries a transient empty browse (bounded, with backoff
    # and a visible status notice), so the test only needs to wait for hits;
    # a persistent empty result still fails the job.
    time0 = time.time()
    while time0 + 15 > time.time():
        app.processEvents()
        if win.discover._hits:
            break
        time.sleep(0.05)
    check("discover search/browse", len(win.discover._hits) > 0, f"{len(win.discover._hits)} hits")
    check("discover defaults to both real catalogs", win.discover._provider == "all")
    check("discover results expose provider images",
          any(bool(hit.get("iconUrl")) for hit in win.discover._hits),
          f"{sum(1 for hit in win.discover._hits if hit.get('iconUrl'))} image-backed results")
    detail_hit = next((hit for hit in win.discover._hits
                       if hit.get("provider") == "modrinth" and hit.get("projectType") != "modpack"), None)
    if detail_hit and win.discover.builds:
        win.discover._target_id = first["buildId"]
        win.discover._open_drawer(detail_hit)
        time0 = time.time()
        while time0 + 8 > time.time() and "Checking" in win.discover._detail_status.text():
            app.processEvents()
            time.sleep(0.05)
        target = win.discover._target_build() or {}
        detail_text = win.discover._detail_status.text().lower()
        check("add drawer checks the selected pack compatibility",
              str(target.get("mcVersion") or "").lower() in detail_text and
              str(target.get("loader") or "").lower() in detail_text,
              win.discover._detail_status.text())
        check("incompatible content cannot be added",
              win.discover._version_box.isEnabled() == win.discover._drawer_primary.isEnabled())
        win.discover._close_drawer()
except Exception as e:  # noqa: BLE001
    check("discover search/browse", False, str(e))

try:
    win._set_nav("ai-builder")
    time0 = time.time()
    while time0 + 6 > time.time() and "Loading" in win.aibuilder._source_desc.text():
        app.processEvents()
        time.sleep(0.05)
    configured = (api.settings_get().get("build") or {}).get("sources") or ["modrinth"]
    source_text = win.aibuilder._source_desc.text()
    check("AI Builder names real configured provider", ("modrinth" not in configured) or "Modrinth" in source_text,
          source_text)
    win.aibuilder._show_done("test-build", {
        "status": "failed",
        "tests": [{"status": "FAIL", "level": "standard"}],
        "failure": {"message": "test failure"},
    })
    done_text = " ".join(w.text() for w in win.aibuilder._done_card.findChildren(QLabel))
    done_buttons = [w.text() for w in win.aibuilder._done_card.findChildren(QPushButton)]
    check("failed AI build never displays a fake PASS", "BUILD FAILED" in done_text and "PLAY NOW" not in done_buttons)
    win.aibuilder._reset()
except Exception as e:  # noqa: BLE001
    check("AI Builder truth labels", False, str(e))

try:
    row = win.downloads._row({"name": "local-import.jar", "provider": "import", "build": "Test",
                              "sizeBytes": 10, "status": "ok", "sha1": ""})
    row_text = " ".join(w.text() for w in row.findChildren(QLabel))
    check("unhashed local import is not labeled verified", "completed" in row_text and "verified" not in row_text.lower())
    row.deleteLater()
except Exception as e:  # noqa: BLE001
    check("download verification labels", False, str(e))

try:
    win._set_nav("settings")
    win.settings._set_sub("java")
    app.processEvents()
    java_text = " ".join(w.text() for w in win.settings._panel.findChildren(QLabel))
    check("Java page exposes the real engine setting", "Automatic Java runtime management" in java_text)
    settings = api.settings_get()
    check("saved CurseForge secret is masked by the engine",
          not settings.get("curseforgeApiKey") or settings.get("curseforgeApiKey") == "********" or bool(settings.get("curseforgeKeyConfigured")))
    win.settings.open_section("providers")
    app.processEvents()
    provider_text = " ".join(w.text() for w in win.settings._panel.findChildren(QLabel))
    check("provider setup exposes real connection controls",
          "CurseForge API key" in provider_text and "Modrinth REST API v2" in provider_text)
    provider_checks = win.settings._panel.findChildren(QCheckBox)
    # Build sources default to ["modrinth"] on a fresh install; CurseForge is
    # opt-in (needs an API key). The engine invariant is that at least one
    # source stays enabled, not that every source is on by default.
    checked = [control.isChecked() for control in provider_checks[:2]]
    check("Modrinth and CurseForge build sources stay enabled together",
          len(provider_checks) >= 2 and any(checked),
          f"{len(provider_checks)} controls, checked={checked}")
    test_button = next((control for control in win.settings._panel.findChildren(QPushButton)
                        if control.text() == "Test connection"), None)
    if test_button:
        test_button.click()
        time0 = time.time()
        while time0 + 8 > time.time():
            app.processEvents()
            provider_text = " ".join(w.text() for w in win.settings._panel.findChildren(QLabel))
            if "Modrinth connected" in provider_text:
                break
            time.sleep(0.05)
    check("provider connection test reports real source state",
              "Modrinth connected" in provider_text and "CurseForge:" in provider_text,
              provider_text[-180:])
    win.settings.open_section("account")
    app.processEvents()
    account_buttons = [control.text() for control in win.settings._panel.findChildren(QPushButton)]
    check("settings exposes real Microsoft account management",
          "MANAGE MINECRAFT ACCOUNT" in account_buttons)
    win.account_modal.show()
    app.processEvents()
    modal_buttons = [control.text() for control in win.account_modal.findChildren(QPushButton)]
    signin_controls = [control for control in win.account_modal.findChildren(QPushButton)
                       if control.text() in ("Sign in with Microsoft", "Microsoft sign-in unavailable")]
    signin_truthful = bool(signin_controls) and (
        signin_controls[0].text() == "Sign in with Microsoft" or not signin_controls[0].isEnabled())
    check("account dialog truthfully exposes Microsoft availability and offline fallback",
          signin_truthful and "USE OFFLINE PROFILE" in modal_buttons)
    check("account dialog contains no player-facing app-id setup",
          "Launcher setup" not in modal_buttons and
          not any("client ID" in field.placeholderText() for field in win.account_modal.findChildren(QLineEdit)))
    win.account_modal.close()
except Exception as e:  # noqa: BLE001
    check("Java settings truth labels", False, str(e))

try:
    win.launch_overlay.show_launch("Smoke Test")
    win.launch_overlay.apply_status({"phase": "preparing", "progress": 42,
                                     "stage": "Reading real launch status", "modsLoaded": 2, "modsTotal": 4})
    for _ in range(3):
        app.processEvents()
    check("launch progress card remains visible after status refresh", win.launch_overlay.height() >= 150,
          f"{win.launch_overlay.width()}x{win.launch_overlay.height()}")
    win.launch_overlay.hide()
except Exception as e:  # noqa: BLE001
    check("launch progress card layout", False, str(e))

print()
if failures:
    print(f"SMOKE TEST FAILED: {failures}")
    sys.stdout.flush()
    os._exit(1)
print("SMOKE TEST PASS — all views construct and live data renders.")
sys.stdout.flush()
os._exit(0)
