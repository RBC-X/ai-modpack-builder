"""Verify the RAM-fitted lite pack end-to-end on this machine.

Because the lite pack dropped heavy BASE mods (mna, goety, aether...), addon
mods that hard-require them (dmnr, goety_mastery_of_magic, aeroblender) must
be cascade-removed the same way the repair engine does: parse the REAL
missing-deps screen ("Mod ID: 'x', Requested by: 'y'"), deselect the
requesters, relaunch — until the menu is reached. Then hold at the menu for
HOLD_MINUTES and report survival + free RAM.

Usage: python pyqt/lite_verify.py [build_id]
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.bridge import PyEngine  # noqa: E402
from engine.core import builds_dir  # noqa: E402
from engine.jarmeta import provided_mod_ids, read_jar_metadata  # noqa: E402
from engine.launcher import pid_alive  # noqa: E402

PACK = sys.argv[1] if len(sys.argv) > 1 else "b-lite-ef38acfd"
HOLD_MIN = float(os.environ.get("HOLD_MINUTES", "5"))
report: dict = {"phases": [], "cascade": []}


def _ascii(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def phase(name: str, ok: bool, detail: str) -> None:
    report["phases"].append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {_ascii(name)}: {_ascii(detail)}", flush=True)


def free_ram_gb() -> float:
    try:
        import ctypes
        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS(); m.dwLength = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return round(m.ullAvailPhys / 1024 ** 3, 2)
    except Exception:
        pass
    return 0.0


def read_record():
    return json.loads((builds_dir() / PACK / "build.json").read_text("utf-8"))


def write_record(rec):
    (builds_dir() / PACK / "build.json").write_text(json.dumps(rec, indent=2), "utf-8")


def requester_pairs(text: str) -> list:
    """Parse the real Forge missing-deps screen: 'Mod ID: 'x', Requested by: 'y''."""
    pairs = []
    for m in re.finditer(r"Mod ID: '([^']+)', Requested by: '([^']+)'", text):
        pairs.append((m.group(1), m.group(2)))
    return pairs


def build_modid_map(rec: dict) -> dict:
    """modId -> slug for every selected jar (the missing-deps screen reports
    MOD IDs like 'dmnr', while selections are keyed by project slug). Uses the
    one-time cache built by pyqt/build_modid_cache.py when it is fresh."""
    try:
        cache = json.loads(Path("workspace/lite-modid-map.json").read_text("utf-8"))
        cur_slugs = {s["slug"] for s in rec["selections"]
                     if s.get("selected", True) and s.get("projectType") == "mod"}
        if set(cache.get("slugs") or []) == cur_slugs:
            return cache["map"]
    except Exception:
        pass
    out = {}
    for s in rec.get("selections") or []:
        if not s.get("selected", True) or s.get("projectType") != "mod":
            continue
        p = s.get("downloadPath")
        if not p or not os.path.exists(p):
            continue
        meta = read_jar_metadata(p)
        if meta and meta.get("id"):
            out.setdefault(meta["id"], s["slug"])
        for pid in provided_mod_ids(p):
            out.setdefault(pid, s["slug"])
    return out


eng = PyEngine()
try:
    # ---- cascade loop: drop addons whose base mods are gone (real screen data)
    menu_pid = None
    for round_no in range(1, 9):
        eng.play(PACK, "PlayerLite")
        t0 = time.time()
        st = eng.status(PACK)
        while time.time() - t0 < 900 and st.get("phase") not in ("running", "error", "stopped"):
            time.sleep(3)
            st = eng.status(PACK)
        if st.get("phase") == "running" and st.get("pid"):
            menu_pid = st.get("pid")
            print(f"[lite] round {round_no}: menu reached (pid {menu_pid})", flush=True)
            break
        # The error screen is written asynchronously — give it a beat, then
        # merge pairs from the play log AND the game's latest.log.
        time.sleep(3)
        texts = []
        for rel in ("logs/launch-play.log", "instance/minecraft/logs/latest.log"):
            p = builds_dir() / PACK / rel
            if p.exists():
                texts.append(p.read_text("utf-8", errors="replace"))
        pairs = []
        seen = set()
        for text in texts:
            for a, b in requester_pairs(text):
                if (a, b) not in seen:
                    seen.add((a, b))
                    pairs.append((a, b))
        if not pairs:
            phase(f"cascade round {round_no}: cannot resolve", False,
                  f"phase={st.get('phase')} {st.get('stage')}")
            raise SystemExit(1)
        rec = read_record()
        by_slug = {s["slug"]: s for s in rec["selections"]}
        modid_map = build_modid_map(rec)
        removed = []
        for missing, requester in pairs:
            slug = modid_map.get(requester) or (requester if requester in by_slug else None)
            if slug and by_slug[slug].get("selected", True):
                by_slug[slug]["selected"] = False
                removed.append(f"{slug}(modid {requester}, needs {missing})")
        write_record(rec)
        report["cascade"].append({"round": round_no, "removed": removed, "seen": pairs})
        print(f"[lite] round {round_no}: missing-deps screen -> cascade-removed {removed}", flush=True)
        # The game may still be sitting at the error screen — stop it before
        # the next round or the next play() will refuse ("already running").
        try:
            eng.stop(PACK)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(4)
    else:
        phase("lite pack reaches menu", False, "menu not reached after cascade rounds")
        raise SystemExit(1)

    phase("lite pack reaches menu", True, f"pid {menu_pid}")

    # ---- hold at the menu
    deadline = time.time() + HOLD_MIN * 60
    held = 0.0
    up = True
    while time.time() < deadline:
        time.sleep(5)
        held = time.time() - t0
        st = eng.status(PACK)
        up = st.get("phase") == "running" and pid_alive(st.get("pid") or 0)
        report.setdefault("timeline", []).append({"t": round(held), "up": up, "freeRamGB": free_ram_gb()})
        if not up:
            break
    phase(f"lite pack at menu for {int(held)}s (target {int(HOLD_MIN*60)}s)",
          up and held >= HOLD_MIN * 60 - 10, f"up={up} freeRAM={free_ram_gb()}GB")
finally:
    try:
        eng.stop(PACK)
    except Exception:  # noqa: BLE001
        pass

overall = all(p["status"] == "PASS" for p in report["phases"])
report["overall"] = "PASS" if overall else "FAIL"
Path("workspace/lite-verify-result.json").write_text(json.dumps(report, indent=2), "utf-8")
print(f"\n[lite] OVERALL: {report['overall']} — saved workspace/lite-verify-result.json", flush=True)
sys.exit(0 if overall else 1)
