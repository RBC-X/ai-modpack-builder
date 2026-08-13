"""Real interactive-session verification against the INSTALLED workspace.

Boots the actual MainWindow (offscreen launcher UI, real in-process engine)
with AMB_WORKSPACE pointed at the installed app's workspace, opens Library,
asserts the two randoo packs render as full cards (artwork + PLAY button),
screenshots them, then drives PLAY through the real UI signal path and polls
the engine to the main menu while streaming instance/minecraft/logs/latest.log
live. Stops the pack and writes workspace/verify-installed-library-result.json.

Usage: pyqt/.venv/Scripts/python pyqt/verify_installed_library.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))

INSTALLED = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AI Modpack Builder" / "workspace"
os.environ["AMB_WORKSPACE"] = str(INSTALLED)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, HERE)

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402

TARGET = os.environ.get("TARGET_PACK", "b-19ff8400e14-cec93aca")  # pack with proven menu launch
VERIFY_ONLY = os.environ.get("VERIFY_ONLY", "") == "1"
report: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    report.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def pump(app, n: int = 10, dt: float = 0.03) -> None:
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


app = QApplication(sys.argv)
theme.setup_fonts(app)
api = PyEngine()

# ---- boot the real launcher window --------------------------------------
win = MainWindow(api)
win.resize(1320, 840)
win.show()
t0 = time.time()
while time.time() - t0 < 20:
    pump(app, 8)
    if getattr(win, "builds", None):
        break
names = sorted(b.get("name") for b in win.builds)
check("launcher boots against installed workspace",
      len(win.builds) == 2 and names == ["randoo", "randoo"],
      f"builds={len(win.builds)} names={names}")

# ---- open Library --------------------------------------------------------
win._set_nav("library")
pump(app, 12)
t0 = time.time()
while time.time() - t0 < 10:
    pump(app, 8)
    grid = win.library._grid
    if grid.count() >= 2:
        break
grid = win.library._grid
check("library grid renders 2 cards", grid.count() >= 2, f"cards={grid.count()}")

card_widgets = []
for i in range(grid.count()):
    w = grid.itemAt(i).widget()
    if w is not None:
        card_widgets.append(w)
card_widgets = card_widgets[:2]

card_ok = True
details = []
for c in card_widgets:
    texts = [l.text() for l in c.findChildren(QLabel) if l.text().strip()]
    has_name = any("randoo" in t.lower() for t in texts)
    avatars = [l for l in c.findChildren(QLabel)
               if l.pixmap() is not None and not l.pixmap().isNull()
               and l.pixmap().width() >= 40]
    has_art = len(avatars) >= 1
    plays = [b for b in c.findChildren(QPushButton) if b.text().strip().upper() == "PLAY"]
    has_play = len(plays) >= 1
    ok = has_name and has_art and has_play
    card_ok = card_ok and ok
    details.append(f"name={has_name} art={has_art} play={has_play}")
check("both randoo cards render full (artwork + play button)",
      card_ok, "; ".join(details))

shot_lib = INSTALLED / "verify-library-installed.png"
win.grab().save(str(shot_lib))
print(f"  saved {shot_lib}", flush=True)

# ---- press PLAY through the real UI path --------------------------------
btn = None
for c in card_widgets:
    for b in c.findChildren(QPushButton):
        if b.text().strip().upper() == "PLAY":
            btn = b
            break
    if btn:
        break
check("PLAY button found for a randoo card", btn is not None)
if VERIFY_ONLY:
    print("  VERIFY_ONLY — skipping live launch (Library render verified).", flush=True)
    overall = all(r["status"] == "PASS" for r in report)
    out = INSTALLED / "verify-installed-library-result.json"
    out.write_text(json.dumps({"phases": report, "overall": "PASS" if overall else "FAIL"}, indent=2), "utf-8")
    print(f"\n[verify] OVERALL: {report}")
    sys.stdout.flush()
    os._exit(0 if overall else 1)
if not btn:
    # still record the result and exit cleanly
    overall = all(r["status"] == "PASS" for r in report)
    out = INSTALLED / "verify-installed-library-result.json"
    out.write_text(json.dumps({"phases": report, "overall": "PASS" if overall else "FAIL"}, indent=2), "utf-8")
    print(f"\n[verify] OVERALL: {report}")
    os._exit(0 if overall else 1)

btn.click()  # real signal path: play_requested -> MainWindow.play -> api.play
pump(app, 15)
launched = getattr(win, "_launching", None) == TARGET
check("PLAY wired through UI -> engine launch", launched, f"_launching={getattr(win, '_launching', None)}")

# ---- poll to main menu while streaming latest.log ----------------------
log_path = INSTALLED / "builds" / TARGET / "instance" / "minecraft" / "logs" / "latest.log"
seen = 0  # byte offset (the game rotates/truncates the log; line counts lie)
menu = False
err = None
t0 = time.time()
deadline = t0 + 540
while time.time() < deadline:
    pump(app, 6, 0.05)
    if log_path.exists():
        try:
            data = log_path.read_text("utf-8", errors="replace")
            size = len(data)
            if size < seen:
                seen = 0  # game rotated/truncated the log
            if size > seen:
                for ln in data[seen:].splitlines():
                    print(f"  [log] {ln[:160]}", flush=True)
                seen = size
        except OSError:
            pass
    st = api.status(TARGET)
    if st.get("phase") == "running" and (st.get("progress") or 0) >= 100:
        # Fresh-evidence gate: the status may only be believed if the game
        # process is alive and the game log was actually written during THIS
        # launch (a persisted stale record must never pass as a menu).
        pid = st.get("pid") or 0
        fresh = False
        try:
            fresh = log_path.exists() and log_path.stat().st_mtime >= t0 - 5
        except OSError:
            pass
        if pid and fresh:
            menu = True
            print(f"  MAIN MENU after {int(time.time() - t0)}s (pid {pid}, log fresh)", flush=True)
            break
        print(f"  [warn] running/100 without fresh evidence (pid={pid} fresh={fresh}) — ignoring", flush=True)
    if st.get("phase") == "error":
        err = st.get("error") or st.get("stage")
        break
    if int(time.time() - t0) % 30 == 0 and (int(time.time() - t0) > 0):
        print(f"  [poll] t={int(time.time() - t0)}s phase={st.get('phase')} progress={st.get('progress')}", flush=True)
    time.sleep(2)

check("pack reaches the main menu", menu, f"phase={st.get('phase')} progress={st.get('progress')} err={err}")
if menu:
    shot_menu = INSTALLED / "verify-launch-menu.png"
    win.grab().save(str(shot_menu))
    print(f"  saved {shot_menu}", flush=True)

# ---- stop through the UI path -------------------------------------------
win.stop(TARGET)
pump(app, 15)
time.sleep(2)
st = api.status(TARGET)
check("STOP closes the instance", st.get("phase") == "stopped" and not st.get("running"),
      f"phase={st.get('phase')} running={st.get('running')}")

overall = all(r["status"] == "PASS" for r in report)
out = INSTALLED / "verify-installed-library-result.json"
out.write_text(json.dumps({"phases": report, "overall": "PASS" if overall else "FAIL"}, indent=2), "utf-8")
print(f"\n[verify] OVERALL: {report}")
sys.stdout.flush()
os._exit(0 if overall else 1)
