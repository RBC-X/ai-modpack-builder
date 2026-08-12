"""Crash parser + attribution — Python port of src/repair/parse.ts + attribution.ts.

Reads real crash reports / latest.log, extracts root cause, matches known
signatures, and names likely culprit mods from the stack trace.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from .conflict import match_crash_signature
from .jarmeta import read_jar_metadata, norm_id as _norm

IGNORE_PREFIXES = [
    "java.", "javax.", "jdk.", "sun.", "com.sun.",
    "org.apache.", "org.objectweb.asm.", "org.spongepowered.asm.",
    "org.spongepowered.launch.", "org.slf4j.", "org.lwjgl.", "org.jetbrains.",
    "org.yaml.snakeyaml.", "org.xerial.", "org.intellij.", "org.fusesource.",
    "net.minecraft", "net.fabricmc", "net.neoforged", "cpw.mods",
    "com.google.", "com.mojang.", "com.ibm.", "com.ctc.wstx.",
    "io.netty.", "it.unimi.", "kotlin.", "scala.",
]

THROWABLE_RE = re.compile(r"^(?:(?:Caused by: |Exception in thread \"[^\"]*\" |java\.lang\.)?)([A-Za-z_$][\w.$]*(?:Error|Exception|RuntimeException))(?::|\s|$)", re.M)


def extract_stack_frames(text: str) -> list:
    out = []
    re_ = re.compile(r"^\s*at\s+([A-Za-z_$][\w.$]*?)\.(?:[a-zA-Z_$][\w$]*|<\w+>|lambda\$[\w.$]*|class_\w+)\(", re.M)
    for m in re_.finditer(text):
        cls = m.group(1)
        if cls not in out:
            out.append(cls)
        if len(out) >= 60:
            break
    return out


def is_ignored_frame(cls: str) -> bool:
    return any(cls.startswith(p) for p in IGNORE_PREFIXES)


def mod_frames(frames: list) -> list:
    return [f for f in frames if not is_ignored_frame(f)]


def parse_crash_report(text: str) -> dict:
    description = ""
    m = re.search(r"Description:\s*(.*)", text)
    if m:
        description = m.group(1).strip()
    cause = ""
    m = re.search(r"Caused by:\s*(.*)", text)
    if m:
        cause = m.group(1).strip()
    causes = list(re.finditer(r"Caused by:\s*([A-Za-z_$][\w.$]*(?:Error|Exception))(?::|\s|$)", text))
    innermost = causes[-1].group(1) if causes else None
    if innermost:
        throwable = innermost
    else:
        m2 = re.search(r"([A-Za-z_$][\w.$]*Error|[A-Za-z_$][\w.$]*Exception)", cause)
        throwable = m2.group(1) if m2 else (THROWABLE_RE.search(text).group(1) if THROWABLE_RE.search(text) else "UnknownException")
    matched = match_crash_signature(text)
    culprit_hints = []

    def unshift(x):
        if x not in culprit_hints:
            culprit_hints.insert(0, x)

    def push(x):
        if x not in culprit_hints:
            culprit_hints.append(x)

    for m in re.finditer(r"mixin apply failed[^\n]*?(?:from modid|modid)\s+([a-zA-Z0-9_\-]+)", text, re.I):
        unshift(m.group(1))
    for m in re.finditer(r"(?:mod|modid)\s+([a-zA-Z0-9_\-]+)\s+is not compatible|unsupported minecraft version[^\n]*?(?:mod|modid)\s+([a-zA-Z0-9_\-]+)", text, re.I):
        g = m.group(1) or m.group(2)
        if g:
            push(g)
    for m in re.finditer(r"^(?:Mod|mod)\s+([a-zA-Z0-9_\-]+)\s+(?:has|is)\s+(?:a problem|missing|unsupported|failed|incompatible)[^\n]*$", text, re.I | re.M):
        push(m.group(1))
    for m in re.finditer(r"requires (?:any )?version(?: [^\n]*? or later)? of ([a-zA-Z0-9_\-]+), which is missing!", text, re.I):
        unshift(m.group(1))
    for m in re.finditer(r"Failure message: Mod [^\n]*? requires ([a-zA-Z0-9_\-]+)(?:\s+\d|\s+or\s|\s*$)", text, re.I):
        unshift(m.group(1))
    for m in re.finditer(r"Currently,\s*([a-zA-Z0-9_\-]+)\s+is not installed", text, re.I):
        unshift(m.group(1))
    for m in re.finditer(r"Mod '[^']+' \(([a-zA-Z0-9_\-]+)\)[^\n]*requires", text, re.I):
        push(m.group(1))
    for m in re.finditer(r"([a-zA-Z0-9_$.]+): Invalid module name: '[^']+' is not a Java identifier", text, re.I):
        unshift(m.group(1))
    for m in re.finditer(r"InvalidInjectionException[^\n]*", text):
        line = m.group(0)
        fm = re.search(r"from mod ([a-zA-Z0-9_-]+)", line, re.I)
        if fm:
            unshift(fm.group(1))
        mb = re.search(r"merged by ([a-zA-Z0-9_.]+)", line, re.I)
        if mb:
            push(mb.group(1))
    culprit_jars = []
    for m in re.finditer(r"\b([a-zA-Z0-9_.\-]+\.jar)\b", text):
        j = m.group(1)
        if j not in culprit_jars:
            culprit_jars.append(j)
    for m in re.finditer(r"^\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|", text, re.M):
        mid = m.group(1).strip()
        file = m.group(4).strip()
        if re.match(r"^[a-zA-Z][a-zA-Z0-9_\-]*$", mid) and mid.lower() not in ("id", "name"):
            push(mid)
        if re.search(r"\.jar$", file, re.I) and file not in culprit_jars:
            culprit_jars.append(file)
    for jar in list(culprit_jars):
        slug = slug_from_jar(jar)
        if slug and slug not in culprit_hints:
            push(slug)
    return {
        "signature": matched["label"] if matched else None,
        "label": matched["label"] if matched else "unknown",
        "exception": throwable,
        "description": description or cause or text[:200],
        "culpritHints": list(dict.fromkeys(culprit_hints))[:10],
        "culpritJars": list(dict.fromkeys(culprit_jars))[:20],
        "stackFrames": extract_stack_frames(text),
        "raw": text[:30000],
    }


def slug_from_jar(file: str):
    base = re.sub(r"\.jar$", "", file, flags=re.I)
    m = re.match(r"^(.*?)-(\d+(?:\.\d+)*[a-z]?)(?:-[a-zA-Z0-9.]+)*$", base)
    return m.group(1) if m and m.group(1) else None


LOADER_PROVIDED = {"minecraft", "fabricloader", "fabric", "fmlloader", "modlauncher",
                   "forge", "neoforge", "quilt_loader", "quilt", "java", "javafml",
                   "mcp", "minecraftforge"}


def missing_dep_ids(text: str) -> list:
    if not re.search(r"missing dependency|which is missing!|which is not installed|currently,[^\n]*is not installed|failure message: mod [^\n]* requires|\binstall [a-z0-9][a-z0-9 _-]+(?: or | to |\(|$)|missing or unsupported mandatory dependenc|mod id: '[^']+', requested by:", text, re.I):
        return []
    out = []

    def push(x):
        clean = str(x).strip()
        if clean and clean not in out and clean not in LOADER_PROVIDED:
            out.append(clean)

    # Forge error screen: "Mod ID: 'irons_lib', Requested by: 'irons_spellbooks', Actual version: '[MISSING]'"
    for m in re.finditer(r"Mod ID: '([a-zA-Z0-9_\-]+)', Requested by: '[^']+', (?:Expected range: '[^']*', )?Actual version: '\[MISSING\]'", text):
        push(m.group(1))
    for m in re.finditer(r"Mod ID: '([a-zA-Z0-9_\-]+)', Requested by:", text):
        push(m.group(1))
    for m in re.finditer(r"requires (?:any )?version(?: [^\n]*? or later)? of ([a-zA-Z0-9_\-]+), which is missing!", text, re.I):
        push(m.group(1))
    for m in re.finditer(r"Currently,\s*([a-zA-Z0-9_\-]+)\s+is not installed", text, re.I):
        push(m.group(1))
    # NOTE: we deliberately do NOT extract from Forge's normal
    # "Error loading class: X (java.lang.ClassNotFoundException: Y)" warnings —
    # those fire on optional/disabled feature classes in every healthy pack and
    # their package segments (client, util, gui…) are not mod ids.
    for m in re.finditer(r"Failure message: Mod [^\n]*? requires ([a-zA-Z0-9_\-]+)(?:\s+\d|\s+or\s|\s*$)", text, re.I):
        push(m.group(1))
    m = re.search(r"\bInstall ([A-Za-z0-9][A-Za-z0-9 _\-]{1,40}?)(?: or | to |\(|$)", text, re.I)
    if m:
        push(m.group(1))
    return out[:20]


def version_conflicts(text: str) -> list:
    """Forge error-screen entries where a mod IS present but its version falls
    outside the requested range, e.g.
        Mod ID: 'curios', Requested by: 'irons_spellbooks',
        Expected range: '[5.14.1+1.20.1,)', Actual version: '5.6.1+1.20.1'
    Returns [{id, expected, actual}]. Entries with Actual '[MISSING]' are
    missing deps (handled by missing_dep_ids), not conflicts."""
    out = []
    pat = re.compile(
        r"Mod ID: '([a-zA-Z0-9_\-]+)', Requested by: '[^']+', "
        r"Expected range: '([^']*)', Actual version: '([^']+)'")
    for m in pat.finditer(text):
        mid, expected, actual = m.groups()
        if actual.strip().upper() == "[MISSING]":
            continue
        if mid not in LOADER_PROVIDED:
            out.append({"id": mid.strip(), "expected": expected.strip(), "actual": actual.strip()})
    return out


def expected_ranges(text: str) -> dict:
    """Map mod id -> required version range from the Forge error screen, for
    both missing deps and version conflicts:
        Mod ID: 'irons_lib', Requested by: 'irons_spellbooks',
        Expected range: '[1.20.1-2,1.20.1-3)', Actual version: '[MISSING]'"""
    out = {}
    pat = re.compile(
        r"Mod ID: '([a-zA-Z0-9_\-]+)', Requested by: '[^']+', "
        r"Expected range: '([^']*)', Actual version: '[^']+'")
    for m in pat.finditer(text):
        out.setdefault(m.group(1).strip(), m.group(2).strip())
    return out


def missing_requesters(text: str) -> dict:
    """Map missing/conflicting mod id -> the mod ids that require it, from the
    Forge error screen. Used to decide what to remove when a dependency cannot
    be resolved on any available provider."""
    out = {}
    for m in re.finditer(r"Mod ID: '([a-zA-Z0-9_\-]+)', Requested by: '([a-zA-Z0-9_\-]+)'", text):
        mid = m.group(1).strip()
        req = m.group(2).strip()
        if mid in LOADER_PROVIDED or req in LOADER_PROVIDED:
            continue
        out.setdefault(mid, [])
        if req not in out[mid]:
            out[mid].append(req)
    return out


def parse_latest_log(lines: list) -> dict:
    text = "\n".join(lines)
    fatal = next((l for l in lines if re.search(
        r"The game crashed whilst|Failed to start the minecraft server|Exception in thread \"(Render thread|main)\"|"
        r"FATAL ERROR in native method|Incompatible mods found!|Some of your mods are incompatible|"
        r"mods are incompatible with the game|Invalid module name: '[^']+' is not a Java identifier|"
        r"Missing or unsupported mandatory dependenc|Mod ID: '[^']+', Requested by:", l)), None)
    if not fatal:
        return {"signature": None, "label": "no-crash", "exception": "", "description": "",
                "culpritHints": [], "culpritJars": [], "stackFrames": [], "raw": text[-2000:]}
    return parse_crash_report(text)


def fatal_startup_detected(lines: list) -> bool:
    text = "\n".join(lines)
    return bool(re.search(
        r"The game crashed whilst|Exception in thread \"(Render thread|main)\"|Failed to start the minecraft server|"
        r"FATAL ERROR in native method|Incompatible mods found!|Some of your mods are incompatible with the game or each other!|"
        r"Invalid module name: '[^']+' is not a Java identifier|which is missing!|which is not installed|"
        r"MISSING EXCEPTION MESSAGE|Failure message: Mod .* requires|There was a severe problem during mod loading|"
        r"Missing or unsupported mandatory dependenc|Mod ID: '[^']+', Requested by:|A potential solution has been determined|"
        r"---- Minecraft Crash Report ----|Mod loading error has occurred|Mod Loading has failed", text))


def main_menu_reached(lines: list) -> bool:
    text = "\n".join(lines)
    if re.search(r"The game crashed whilst|Exception in thread \"Render thread\"|Failed to start the minecraft server|FATAL ERROR in native method|"
                 r"Missing or unsupported mandatory dependenc|Mod ID: '[^']+', Requested by:|A potential solution has been determined", text):
        return False
    # Real menu evidence only: audio init + atlas creation + login happen in
    # the final seconds before the main menu on EVERY modded client. A bare
    # "[Render thread/INFO]:" line is NOT enough — heavy mods log Render-thread
    # work long before the menu (e.g. Project Atmosphere's client setup), and
    # matching on it produced false "menu reached" verdicts.
    audio = bool(re.search(r"Sound engine started|OpenAL initialized", text))
    atlas = bool(re.search(r"Created: \d+x\d+x\d+ minecraft:textures/atlas/", text))
    login = bool(re.search(r"Backend library: LWJGL version", text))
    return audio or (atlas and login)


def world_load_detected(lines: list) -> bool:
    text = "\n".join(lines)
    return bool(re.search(r"Preparing spawn area|Time elapsed: \d+ ms|Done \(\d+\.\d+s\)!|Saving and pausing game", text))


def server_start_detected(lines: list) -> bool:
    text = "\n".join(lines)
    return bool(re.search(r"Done \(\d+\.\d+s\)!", text)) and 'For help, type "help"' in text


# ---------------------------------------------------------------------------
# Attribution — stack-trace → offending mod (no guessing)
# ---------------------------------------------------------------------------

_class_index_cache = {}


def _index_jar(path, slug: str):
    st = Path(path).stat() if Path(path).exists() else None
    if not st:
        return None
    hit = _class_index_cache.get(path)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    index = None
    try:
        classes = set()
        prefixes = set()
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                name = info.filename
                if not name.endswith(".class") or "$" in name or name.startswith("META-INF/") or name == "module-info.class":
                    continue
                fqn = name[:-6].replace("/", ".")
                if "." not in fqn:
                    continue
                classes.add(fqn)
                segs = fqn.split(".")
                if len(segs) >= 2:
                    prefixes.add(".".join(segs[:2]))
                if len(segs) >= 3:
                    prefixes.add(".".join(segs[:3]))
        meta = read_jar_metadata(path)
        index = {"slug": slug, "modId": _norm(meta["id"]) if meta else "",
                 "classes": classes, "prefixes": prefixes, "totalClasses": len(classes)}
    except Exception:
        index = None
    _class_index_cache[path] = (st.st_mtime_ns, st.st_size, index)
    return index


def invalidate_jar_index(path) -> None:
    _class_index_cache.pop(path, None)


def attribute_crash(crash_text: str, jars: list) -> list:
    out = []
    seen = set()

    def push(a):
        if a["slug"] not in seen:
            seen.add(a["slug"])
            out.append(a)

    for m in re.finditer(r"mixin config:?\s*([a-zA-Z0-9_-]+?)(?:\.mixins\.json)?[),;:\s]", crash_text):
        nid = _norm(m.group(1).strip())
        if not nid:
            continue
        for jar in jars:
            ix = _index_jar(jar["path"], jar["slug"])
            if ix and (ix["modId"] == nid or _norm(jar["slug"]) == nid):
                push({"slug": jar["slug"], "confidence": "mixin-config",
                      "reason": f'Crash is inside mixin config "{m.group(1)}" — {jar["slug"]}\'s mixins failed to apply'})
                break

    frames = mod_frames(extract_stack_frames(crash_text))
    if frames and jars:
        indexes = [_index_jar(j["path"], j["slug"]) for j in jars]
        indexes = [x for x in indexes if x]
        for frame in frames:
            for ix in indexes:
                if frame in ix["classes"]:
                    push({"slug": ix["slug"], "confidence": "exact-class",
                          "reason": f"Stack trace calls {frame} — a class shipped inside {ix['slug']}"})
            if any(a["confidence"] == "exact-class" for a in out):
                break
            segs = frame.split(".")
            for depth in (3, 2):
                if len(segs) < depth:
                    continue
                pkg = ".".join(segs[:depth])
                for ix in indexes:
                    if pkg in ix["prefixes"]:
                        push({"slug": ix["slug"], "confidence": "package",
                              "reason": f"Stack trace references {pkg}.* — a package shipped inside {ix['slug']}"})
                if any(a["confidence"] == "package" for a in out):
                    break
            if out:
                break
    return out[:5]
