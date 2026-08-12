"""Build the AI Modpack Builder Windows installer, end to end.

Pipeline (all real, no fakes):
  1. PyInstaller one-folder bundle  -> dist/AI Modpack Builder/
  2. Frozen selftest (offscreen)    -> writes selftest.json into the frozen
                                       workspace (LOCALAPPDATA, or AMB_WORKSPACE)
  3. Inno Setup compile             -> installers/AI-Modpack-Builder-Setup-<ver>.exe
  4. (verify) silent-install to a scratch dir, run the INSTALLED app's
     --selftest, then uninstall.

Requires: pyqt/.venv with pyinstaller, Inno Setup 6 (ISCC.exe) installed.
Usage:    pyqt/.venv/Scripts/python pyqt/build_installer.py [--verify] [--trust]
          --trust also installs the signing cert into this machine's Trusted
          Root/Publisher stores (UAC prompt) so the signed build verifies.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # pyqt/
ROOT = HERE.parent                              # project root
sys.path.insert(0, str(HERE))
from product_config import APP_VERSION  # noqa: E402

VENV_PY = HERE / ".venv" / "Scripts" / "python.exe"
SPEC = HERE / "installer" / "amb.spec"
ISS = HERE / "installer" / "installer.iss"
APP_DIR = ROOT / "dist" / "AI Modpack Builder"
EXE = APP_DIR / "AI Modpack Builder.exe"
INSTALLER_DIR = ROOT / "installers"
VERSION = APP_VERSION
report: dict = {"phases": []}


def phase(name: str, ok: bool, detail: str = "") -> None:
    report["phases"].append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def run(cmd: list, timeout: int = 600, env: dict | None = None) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run([str(c) for c in cmd], capture_output=True, timeout=timeout, env=env)


def find_iscc() -> Path | None:
    for cand in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
                 Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")):
        if cand.exists():
            return cand
    return None


def main() -> int:
    global VERSION
    if "--version" in sys.argv:
        VERSION = sys.argv[sys.argv.index("--version") + 1].strip()
    sign = "--no-sign" not in sys.argv
    t0 = time.time()
    # ---- 1. PyInstaller bundle
    r = run([VENV_PY, "-m", "PyInstaller", str(SPEC),
             "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "pyi"),
             "--noconfirm", "--clean"], timeout=900)
    bundle_ok = r.returncode == 0 and EXE.exists() and (APP_DIR / "_internal" / "assets" / "fonts").is_dir()
    phase("PyInstaller bundle", bundle_ok,
          f"{(EXE if EXE.exists() else APP_DIR)} ({_mb(APP_DIR)} MB)")
    if not bundle_ok:
        report["overall"] = "FAIL"
        return 1

    # ---- sign the bundled app exe before it is wrapped by the installer
    if sign:
        import sign as signer
        try:
            tp = signer.ensure_cert()
            ok_s, msg_s = signer.sign_file(EXE, tp)
            phase("sign app exe", ok_s, f"{msg_s} (thumbprint {tp[:12]}…)")
            if not ok_s:
                report["overall"] = "FAIL"
                return 1
        except Exception as e:  # noqa: BLE001
            phase("sign app exe", False, str(e))
            report["overall"] = "FAIL"
            return 1
    else:
        phase("sign app exe", True, "skipped (--no-sign)")

    # ---- 2. Frozen selftest (fresh workspace = LOCALAPPDATA when not overridden)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    r = run([EXE, "--selftest"], timeout=300, env=env)
    st_path = Path(os.environ.get("AMB_WORKSPACE") or
                   (Path(os.environ.get("LOCALAPPDATA", "")) / "AI Modpack Builder" / "workspace")) / "selftest.json"
    st = {}
    if st_path.exists():
        try:
            st = json.loads(st_path.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            st = {}
    frozen_ok = r.returncode == 0 and bool(st.get("ok"))
    phase("frozen app selftest", frozen_ok,
          f"rc={r.returncode} checks={[c['name'] for c in st.get('checks', [])]}")
    if not frozen_ok:
        report["overall"] = "FAIL"
        return 1

    # ---- 3. Inno Setup installer
    iscc = find_iscc()
    if not iscc:
        phase("Inno Setup compile", False, "ISCC.exe not found (install Inno Setup 6)")
        report["overall"] = "FAIL"
        return 1
    r = run([iscc, f"/DMyAppVersion={VERSION}", str(ISS)], timeout=600)
    setup = INSTALLER_DIR / f"AI-Modpack-Builder-Setup-{VERSION}.exe"
    setup_ok = r.returncode == 0 and setup.exists()
    phase("Inno Setup installer", setup_ok,
          f"{setup.name} ({setup.stat().st_size // (1024*1024)} MB)" if setup_ok else "")
    if not setup_ok:
        report["overall"] = "FAIL"
        return 1

    # ---- sign the installer itself and report the final signature status
    if sign:
        import sign as signer
        try:
            tp = signer.ensure_cert()
            ok_s, msg_s = signer.sign_file(setup, tp)
            phase("sign installer", ok_s, f"{msg_s} — status: {signer.verify(setup)}")
            if not ok_s:
                report["overall"] = "FAIL"
                return 1
        except Exception as e:  # noqa: BLE001
            phase("sign installer", False, str(e))
            report["overall"] = "FAIL"
            return 1
    else:
        phase("sign installer", True, "skipped (--no-sign)")

    # ---- 4. Optional: trust the signing cert locally (Trusted Root/Publisher)
    if "--trust" in sys.argv and sign:
        import sign as signer
        try:
            tp = signer.ensure_cert()
            if signer.is_trusted(tp):
                phase("trust cert locally", True, "already trusted (LocalMachine Root)")
            else:
                res = signer.trust(tp)
                phase("trust cert locally", res["ok"],
                      res["message"] + (f" — verify: {signer.verify(setup)}" if res["ok"] else ""))
        except Exception as e:  # noqa: BLE001
            phase("trust cert locally", False, str(e))
    elif "--trust" in sys.argv:
        phase("trust cert locally", False, "requires --no-sign to be absent (sign first)")

    # ---- 5. Optional: install -> run -> uninstall verification
    if "--verify" in sys.argv:
        scratch = Path(os.environ.get("LOCALAPPDATA", "")) / "AI Modpack Builder Test Install"
        r = run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                 "/DIR=" + str(scratch)], timeout=600)
        installed_exe = scratch / "AI Modpack Builder.exe"
        inst_ok = r.returncode == 0 and installed_exe.exists()
        phase("silent install to scratch dir", inst_ok)
        if inst_ok:
            r = run([installed_exe, "--selftest"], timeout=300)
            installed_ok = r.returncode == 0
            phase("installed app selftest", installed_ok, f"rc={r.returncode}")
            un = scratch / "unins000.exe"
            if un.exists():
                run([un, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=120)
            shutil.rmtree(scratch, ignore_errors=True)
        else:
            phase("installed app selftest", False, "install failed — skipped")

    report["overall"] = "PASS" if all(p["status"] == "PASS" for p in report["phases"]) else "FAIL"
    report["installer"] = str(setup)
    report["version"] = VERSION
    report["signed"] = sign
    report["elapsedSec"] = round(time.time() - t0)
    out = ROOT / "workspace" / "installer-build-result.json"
    out.write_text(json.dumps(report, indent=2), "utf-8")
    print(f"\n[build] OVERALL: {report['overall']} — installer: {setup}", flush=True)
    print(f"[build] report: {out}", flush=True)
    return 0 if report["overall"] == "PASS" else 1


def _mb(p: Path) -> int:
    try:
        return round(sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / (1024 * 1024))
    except Exception:  # noqa: BLE001
        return 0


if __name__ == "__main__":
    sys.exit(main())
