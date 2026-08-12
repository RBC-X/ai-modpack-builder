"""UI-level proof: a pack made in the launcher stays listed in the Library
across tab switches and full app restarts (fresh engine + fresh window on the
same workspace). Run with pyqt/.venv/Scripts/python.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AMB_DISABLE_CATALOG_WARMUP"] = "1"

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

WORK = HERE.parent / ".freebuff" / "libpersist-test"
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True, exist_ok=True)
os.environ["AMB_WORKSPACE"] = str(WORK)

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    if not cond:
        failures.append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))


def make_completed_pack(api, name: str, bid: str) -> str:
    """Create a build record directly (a finished pack) without a real build."""
    from engine.service import PyEngine  # noqa: F401 (keeps imports local)
    rec = {
        "buildId": bid, "name": name, "request": "UI persistence test pack",
        "status": "done", "phase": "done", "requirements": {
            "minecraftVersion": "1.20.1", "loader": "forge", "ramGB": 4},
        "selections": [], "downloads": [], "graph": {"nodes": {}, "edges": []},
        "tests": [], "testResult": {"status": "PASS", "level": "standard"},
        "conflicts": [], "repairs": [], "exports": [], "packStats": {"modCount": 12},
        "settings": {}, "perfEstimate": None, "finalReport": "ok", "error": None,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    api._s._write_record(rec)
    return bid


from PyQt6.QtWidgets import QApplication  # noqa: E402

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402

app = QApplication(sys.argv)
theme.setup_fonts(app)

# ---- first app session: create the pack, verify it is listed
api1 = PyEngine()
bid = make_completed_pack(api1, "My Persisted Pack", "b-persist-test-1")
win1 = MainWindow(api1)
win1.resize(1320, 840)
win1.show()

for _ in range(80):
    app.processEvents()
    if any(b.get("buildId") == bid for b in win1.library.builds):
        break
    time.sleep(0.1)
check("pack listed right after being made", any(
    b.get("buildId") == bid for b in win1.library.builds))

# ---- tab away and come back: still listed (in-memory keeps the list)
win1._set_nav("discover")
app.processEvents()
win1._set_nav("library")
app.processEvents()
check("pack still listed after switching tabs", any(
    b.get("buildId") == bid for b in win1.library.builds))

# ---- full restart: brand-new engine + window on the SAME workspace
win1.close()
app.processEvents()
api2 = PyEngine()
win2 = MainWindow(api2)
win2.show()
for _ in range(80):
    app.processEvents()
    if any(b.get("buildId") == bid for b in win2.library.builds):
        break
    time.sleep(0.1)
check("pack still listed after full app restart", any(
    b.get("buildId") == bid for b in win2.library.builds))

# ---- the on-disk index itself carries it
idx = json.loads((WORK / "builds" / "index.json").read_text("utf-8"))
check("pack persisted in index.json on disk", any(
    s.get("buildId") == bid for s in idx), f"{len(idx)} entries")

# ---- a corrupt record must not blank the whole library
bad = dict(idx[0])
bad["buildId"] = "b-corrupt-record"
bad["name"] = None  # _enrich chokes on None name in some paths
idx.insert(0, bad)
(WORK / "builds" / "index.json").write_text(json.dumps(idx), "utf-8")
(WORK / "builds" / "b-corrupt-record").mkdir(exist_ok=True)
(WORK / "builds" / "b-corrupt-record" / "build.json").write_text("{not json", "utf-8")
api3 = PyEngine()
win3 = MainWindow(api3)
win3.show()
for _ in range(80):
    app.processEvents()
    if any(b.get("buildId") == bid for b in win3.library.builds):
        break
    time.sleep(0.1)
check("library still lists good packs despite a corrupt record", any(
    b.get("buildId") == bid for b in win3.library.builds),
    f"{len(win3.library.builds)} listed")
win3.close()

win2.close()
app.processEvents()
from common import icon_cache  # noqa: E402
icon_cache.shutdown()
time.sleep(0.5)

shutil.rmtree(WORK, ignore_errors=True)
ok = not failures
print("LIBRARY PERSIST PASS" if ok else "LIBRARY PERSIST FAIL")
sys.exit(0 if ok else 1)
