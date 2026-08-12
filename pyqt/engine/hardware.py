"""Hardware detection + performance estimation — Python port of
src/hardware/* and src/perf/*. Detects the real machine (CPU/GPU/RAM/OS) and
sizes the pack's RAM/load expectations from it.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import time

# Hardware is queried via PowerShell subprocesses (2–3 spawns, each with a
# 20 s timeout). fit_xmx_mb() calls detect_hardware() on EVERY launch, build
# test and retest — without a cache that is seconds of PowerShell startup per
# call, and up to 60 s of worst-case stall if PowerShell hangs. Cache with a
# short TTL; hardware_refresh() forces a re-detect.
_detect_cache = {"at": 0.0, "data": None}
_DETECT_TTL_S = 300


def detect_hardware(force: bool = False) -> dict:
    now = time.monotonic()
    if not force and _detect_cache["data"] is not None and now - _detect_cache["at"] < _DETECT_TTL_S:
        return _detect_cache["data"]
    out = _detect_hardware_now()
    _detect_cache["at"] = now
    _detect_cache["data"] = out
    return out


def _detect_hardware_now() -> dict:
    out = {"cpu": "Unknown CPU", "gpu": "Unknown GPU", "ramGB": 0, "os": f"{platform.system()} {platform.release()}", "cores": 0}
    try:
        out["cores"] = os.cpu_count() or 0
    except Exception:
        pass
    # CPU + RAM via PowerShell (Windows)
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name; "
                 "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1)"],
                capture_output=True, text=True, timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW)
            lines = [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
            if lines:
                out["cpu"] = lines[0]
            if len(lines) > 1:
                try:
                    out["ramGB"] = round(float(lines[1]))
                except ValueError:
                    pass
        except Exception:
            pass
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW)
            gpus = [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
            if gpus:
                out["gpu"] = gpus[0]
        except Exception:
            pass
    else:
        try:
            out["cpu"] = platform.processor() or out["cpu"]
        except Exception:
            pass
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        out["ramGB"] = round(int(line.split()[1]) / 1024 / 1024)
                        break
        except OSError:
            pass
        try:
            r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10)
            for line in (r.stdout or "").splitlines():
                if "VGA" in line or "3D" in line:
                    parts = line.split(":", 1)
                    if len(parts) > 1:
                        out["gpu"] = parts[1].strip()
                        break
        except Exception:
            pass
    if not out["ramGB"]:
        out["ramGB"] = round((os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")) / 1024 ** 3) if hasattr(os, "sysconf") else 8
    return out


def fit_xmx_mb(requested_gb: int = 8) -> int:
    """Cap the JVM heap against detected physical RAM.

    An 8 GB request on a 7 GB laptop used to launch with -Xmx8192m, which
    overcommits the machine (swap thrash, random game-window closes, JVM
    deaths when a second pack runs). The heap is capped at ~72% of physical
    RAM (floored at 2 GB, rounded to 256 MB) so a single pack stays bootable
    and two packs can coexist.
    """
    requested = max(2048, int(requested_gb or 8) * 1024)
    phys = detect_hardware().get("ramGB") or 8
    cap = max(2048, int(phys * 1024 * 0.72))
    fitted = min(requested, cap)
    return max(2048, int(fitted // 256 * 256))


def performance_estimate(hardware: dict, ram_gb: int = 0, target_fps: int = 60,
                         mod_count: int = 80, shaders: bool = False,
                         res: str = "1920x1080") -> dict:
    """Estimate whether the requested pack is realistic for the machine."""
    hw = hardware.get("effective") or hardware.get("detected") or {}
    ram = ram_gb or hw.get("ramGB") or 8
    gpu = str(hw.get("gpu") or "").lower()
    cpu = str(hw.get("cpu") or "").lower()
    integrated = any(g in gpu for g in ("intel", "radeon", "amd radeon", "uhd", "iris", "vega"))
    weak_gpu = integrated or "gt 710" in gpu or "940" in gpu
    weak_cpu = any(c in cpu for c in ("celeron", "pentium", "athlon", "a4", "a6"))
    base = 6.0 + min(8.0, mod_count / 40.0)
    if shaders:
        base += 2.0
    recommended = min(ram, max(4, round(base)))
    load = "Light" if mod_count <= 40 else "Medium" if mod_count <= 100 else "Heavy"
    confidence = 90
    if weak_gpu and shaders:
        confidence -= 25
    if weak_cpu:
        confidence -= 15
    if mod_count > 160 and not weak_gpu:
        confidence -= 10
    if ram < 8:
        confidence -= 10
    realistic = confidence >= 50
    return {
        "estimatedRamGB": round(base, 1),
        "recommendedAllocationMB": recommended * 1024,
        "recommendedAllocation": f"{recommended} GB",
        "expectedLoad": load,
        "confidence": max(5, min(99, confidence)),
        "realistic": realistic,
        "note": "" if realistic else "Requested pack may exceed this machine; a lighter build is recommended.",
        "optimizedProposal": not realistic,
    }
