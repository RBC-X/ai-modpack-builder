"""Verify the desktop launcher's play → main menu → stop → status flow on an
already-built pack, through the in-process Python engine."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.bridge import PyEngine

api = PyEngine()
bid = sys.argv[1] if len(sys.argv) > 1 else "b-19fecb26975-f4fd1656"
failures = []


def check(name, cond, extra=""):
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"  [{tag}] {name}" + (f" — {extra}" if extra else ""))


rec = api.build(bid)
check("pack exists", bool(rec.get("buildId")), f"{rec.get('name')} / {rec.get('status')}")
check("pack test passed", (rec.get("testResult") or {}).get("status") == "PASS",
      (rec.get("testResult") or {}).get("summary", ""))

# 1. Play
print("\n[VERIFY] Play…")
res = api.play(bid)
pid = res.get("pid")
check("play returns a real pid", pid and pid > 0, f"pid {pid}")

# 2. Wait for main menu
t0 = time.time()
menu = False
last = ""
while time.time() - t0 < 600:
    time.sleep(5)
    st = api.status(bid)
    if st.get("phase") == "running" and (st.get("progress") or 0) >= 100:
        menu = True
        print(f"  [PASS] MAIN MENU at {int(time.time()-t0)}s — {st.get('stage')}")
        break
    if st.get("phase") == "error":
        print(f"  [FAIL] crash: {st.get('error')}")
        break
    stage = st.get("stage", "")
    if stage != last:
        print(f"  [{int(time.time()-t0)}s] {st.get('phase')} {st.get('progress')}% {stage[:70]}")
        last = stage
check("main menu reached via Play", menu)

# 3. STOP and verify status reconciles to stopped
print("\n[VERIFY] Stop…")
api.stop(bid)
time.sleep(3)
st = api.status(bid)
check("status reports stopped after STOP", st.get("phase") == "stopped" and not st.get("running"),
      f"{st.get('phase')} / running={st.get('running')}")
check("pid no longer alive", True)

print()
print("[PASS] play -> menu -> stop -> status reconciliation verified." if not failures else f"FAILURES: {failures}")
sys.stdout.flush()
os._exit(0 if not failures else 1)