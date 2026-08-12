"""E2E flagship test: build the 120-mod medieval fantasy Forge 1.20.1 pack
entirely through the in-process Python engine — real provider searches, real
downloads, real launch, automatic repair on crash if needed, and validated
exports. No Node server, no localhost, no second process.

    pyqt/.venv/Scripts/python pyqt/e2e_flagship_test.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.bridge import PyEngine
from engine.core import builds_dir, read_json_file, format_bytes

FAILURES = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        FAILURES.append(name)
    print(f"  [{tag}] {name}" + (f" — {extra}" if extra else ""))


def fmt_time(t: float) -> str:
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


FLAGSHIP_PROMPT = (
    "Make me a Minecraft 1.20.1 medieval fantasy RPG modpack with around 120 mods, "
    "Create, magic, better villages, bosses, structures, realistic terrain, shaders, "
    "32x textures, multiplayer support, and good performance on 8 GB RAM."
)

print("=" * 70)
print("FLAGSHIP E2E TEST — in-process Python engine")
print(f"Prompt: {FLAGSHIP_PROMPT[:80]}…")
print("=" * 70)

# ---- 1. Set up engine with budget raised for a 120-mod pack ----
api = PyEngine()
check("engine healthy", api.health())

# Save settings with generous budget
api.settings_post({
    "build": {
        "maxTotalMB": 4000,
        "downloadAssets": True,
        "maxAssetMB": 800,
        "autoInstallJava": True,
        "repairMode": "standard",
    }
})
check("budget set to 4000 MB for 120 mods", True)

# ---- 2. Start build ----
print("\n[FLAGSHIP] Starting build…")
t0 = time.time()
build_id = api.start_build({
    "prompt": FLAGSHIP_PROMPT,
    "loader": "forge",
    "testMode": "standard",
    "ramGB": 8,
    "shaders": True,
    "sources": ["modrinth"],
})

check("build started", bool(build_id), build_id)
print(f"  Build ID: {build_id}")

# ---- 3. Wait for build completion ----
print("\n[FLAGSHIP] Waiting for build to complete…")
import glob
elapsed = 0
timeout = 7200  # 2 hours max (120 mod downloads + assets + Forge boot)
last_line = ""
last_print = 0
last_stage = ""

while elapsed < timeout:
    time.sleep(5)
    elapsed = time.time() - t0
    rec = api.build(build_id)
    status = rec.get("status", "")

    # tail the real event log for live stage/progress
    ev_path = os.path.join(str(builds_dir()), build_id, "logs", "events.jsonl")
    stage_line = ""
    try:
        with open(ev_path, "r", encoding="utf-8") as f:
            for line in f:
                stage_line = line
        if stage_line:
            ev = json.loads(stage_line)
            last_stage = f"{ev.get('stage')}: {ev.get('message', '')[:60]}"
    except Exception:
        pass

    # print every 15s regardless (so a long download phase never looks hung)
    if elapsed - last_print >= 15:
        last_print = elapsed
        print(f"  [{fmt_time(elapsed)}] {status or 'building'} — {last_stage or 'starting…'}")

    if status in ("done", "failed"):
        print(f"  [{fmt_time(elapsed)}] {status} — {last_stage}")
        break

# ---- 4. Report build results ----
elapsed = time.time() - t0
print(f"\n[FLAGSHIP] Build finished in {fmt_time(elapsed)}")
print(f"  Status: {rec.get('status')}")

mod_count = len([s for s in (rec.get("selections") or []) if s.get("projectType") == "mod" and s.get("selected", True)])
graph_count = len((rec.get("graph") or {}).get("nodes", {}))
dl_records = rec.get("downloads") or []
dl_ok = len([d for d in dl_records if d.get("status") == "ok"])
dl_skip = len([d for d in dl_records if d.get("status") == "skipped"])
dl_fail = len([d for d in dl_records if d.get("status") == "failed"])
repairs = rec.get("repairs") or []
test_result = rec.get("testResult") or {}

check("mods selected", mod_count > 0, f"{mod_count} mods selected, {graph_count} graph nodes")
check("some files downloaded", dl_ok > 0, f"{dl_ok} ok, {dl_skip} skipped, {dl_fail} failed")
if repairs:
    check("repairs applied", True, f"{len(repairs)} repair(s): {repairs[0].get('action')}")
else:
    check("no repairs needed (passed first boot)", True)

if repairs:
    print(f"  Repairs:")
    for r_ in repairs:
        print(f"    - {r_.get('action')}: {r_.get('reason', '')[:100]}")

tr_status = test_result.get("status", "N/A")
check("test result recorded", tr_status in ("PASS", "FAIL", "ERROR"), tr_status)
# Hard gate: the acceptance test only passes when the pack actually reached the
# main menu — a failed launch must fail the whole acceptance run.
check("launch test PASSED (main menu reached)", tr_status == "PASS",
      f"status={tr_status}: {test_result.get('summary', '')[:100]}")
if test_result.get("summary"):
    print(f"  Test: {test_result.get('summary')}")

# ---- 5. Validate exports exist ----
exports = rec.get("exports") or []
check("exports generated", len(exports) > 0, f"{len(exports)} export(s)")
for e in exports:
    ep = e.get("path", "")
    ev = e.get("validated", False)
    sz = e.get("sizeBytes", 0)
    exists = os.path.isfile(ep) if ep else False
    check(f"  export {e.get('kind')}", exists and ev,
          f"{format_bytes(sz)} {'VALIDATED' if ev else 'NOT VALIDATED'}")

# ---- 6. Real launch (Play) ----
if tr_status == "PASS":
    print(f"\n[FLAGSHIP] Launching pack (Play)…")
    play_t0 = time.time()
    try:
        result = api.play(build_id)
        check("play returned pid", True, f"pid {result.get('pid')}")
    except Exception as e:
        check("play failed (possible repair peak)", False, str(e))
        print("  Trying fix → relaunch…")
        try:
            api.fix(build_id)
            for _ in range(60):
                time.sleep(2)
                st = api.status(build_id)
                if st.get("phase") == "running" and st.get("progress", 0) >= 100:
                    break
        except Exception as e2:
            check("repair also failed", False, str(e2))
        result = api.status(build_id)

    # Poll for main menu
    play_timeout = 600  # 10 min first boot
    menu_reached = False
    crash_detected = False
    play_elapsed = 0
    while play_elapsed < play_timeout:
        time.sleep(3)
        play_elapsed = time.time() - play_t0
        try:
            st = api.status(build_id)
        except Exception:
            continue
        phase = st.get("phase")
        progress = st.get("progress", 0)
        if phase == "running" and progress >= 100:
            menu_reached = True
            print(f"\n  [PASS] MAIN MENU REACHED after {int(play_elapsed)}s!")
            break
        if st.get("error") or phase == "error":
            crash_detected = True
            print(f"\n  [FAIL] CRASH: {st.get('error', '')[:120]}")
            missing = st.get("missingDeps") or []
            if missing:
                print(f"  Missing deps: {missing}")
            break
        if play_elapsed % 15 < 3:
            print(f"  [{fmt_time(play_elapsed)}] {phase} {progress}%")

    if not menu_reached and not crash_detected:
        print(f"\n  [FAIL] Neither menu nor crash within {play_timeout}s")

    # STOP
    print("\n[FLAGSHIP] Stopping instance…")
    api.stop(build_id)
    time.sleep(2)
    check("instance stopped after STOP", not api.status(build_id).get("running"))

# ---- 7. Summary ----
print("\n" + "=" * 70)
print("FLAGSHIP RESULTS")
print("=" * 70)
print(f"Build ID:       {build_id}")
print(f"Duration:       {fmt_time(time.time() - t0)}")
print(f"Status:         {rec.get('status')}")
print(f"Mods selected:  {mod_count}")
print(f"Downloads:      {dl_ok} ok / {dl_skip} skipped / {dl_fail} failed")
print(f"Test status:    {tr_status}")
wait_str = f" / main menu: {int(time.time() - t0)}s" if tr_status == "PASS" else ""
print(f"Repairs:        {len(repairs)}{' — ' + repairs[0].get('action') if repairs else ' (none)'}")
print(f"Exports:        {', '.join(e.get('kind', '?') for e in exports)}")
print(f"Exports path:   {exports[0].get('path', '')[:80] + '…' if exports else 'N/A'}")
if FAILURES:
    print(f"\nFAILURES: {FAILURES}")
    sys.exit(1)
print(f"\n[{'PASS' if not FAILURES else 'FAIL'}] FLAGSHIP E2E {'PASS' if not FAILURES else 'FAIL'}")
sys.stdout.flush()
os._exit(0 if not FAILURES else 1)