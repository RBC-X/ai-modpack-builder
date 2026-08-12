"""Description-based dependency research — Python port of src/solver/descresearch.ts.

Scans real project descriptions (Modrinth body) for known requirement phrases
and returns candidate ids for the reconcile pass to verify against the real
provider. Conservative by design.
"""
from __future__ import annotations

import re

REQUIREMENT_RULES = [
    {"re": re.compile(r"requires\s+fabric\s+api", re.I), "candidates": lambda m: ["fabric-api"]},
    {"re": re.compile(r"requires\s+fabric\s+loader", re.I), "candidates": lambda m: ["fabricloader"]},
    {"re": re.compile(r"requires\s+cloth\s+config", re.I), "candidates": lambda m: ["cloth-config"]},
    {"re": re.compile(r"requires\s+gecko\s*lib", re.I), "candidates": lambda m: ["geckolib"]},
    {"re": re.compile(r"requires\s+architectury\s+api", re.I), "candidates": lambda m: ["architectury-api"]},
    {"re": re.compile(r"requires\s+cardinal\s+components", re.I), "candidates": lambda m: ["cardinal-components-api"]},
    {"re": re.compile(r"requires\s+player\s+animator", re.I), "candidates": lambda m: ["playeranimator"]},
    {"re": re.compile(r"(?:requires|needs|depends on)\s+(?:the\s+)?(?:mod\s+)?['\"`]?([A-Za-z][A-Za-z0-9_\-]{2,30})['\"`]?(?=\s*(?:mod|api|library|lib|,|\.|\n|$))", re.I),
     "candidates": lambda m: [slugify(m[1])] if len(m) > 1 else []},
    {"re": re.compile(r"(?:requires|needs)\s+(?:the\s+)?(['\"`]?[A-Z][a-zA-Z0-9_\-]{2,30}['\"`]?)\s+to\s+work", re.I),
     "candidates": lambda m: [slugify(m[1])] if len(m) > 1 else []},
    {"re": re.compile(r"(?:requires|needed|dependencies?):?\s+([A-Za-z][A-Za-z0-9_\-]{2,30}(?:\s*,\s*[A-Za-z][A-Za-z0-9_\-]{2,30}){0,4})", re.I),
     "candidates": lambda m: [slugify(s) for s in re.split(r"\s*,\s*", m[1])] if len(m) > 1 else []},
]

STOP = {
    "the", "a", "an", "this", "that", "you", "your", "and", "or", "but", "for",
    "with", "from", "into", "onto", "minecraft", "minecrafts", "vanilla", "fabric",
    "forge", "neoforge", "quilt", "loader", "mod", "mods", "java", "version",
    "latest", "newest", "game", "client", "server", "world", "jar", "file", "files",
    "any", "all", "more", "some", "will", "should", "must", "can", "work", "works",
    "working", "compatible", "compatibility", "require", "requires", "needs", "need",
    "install", "installed", "installation", "dependencies", "dependency", "support",
    "supports", "use", "uses", "using", "recommend", "recommended", "please", "see",
    "check", "read", "download", "downloads", "version", "versions", "minecraft",
    "mc", "api", "apis", "library", "libraries", "essential", "required", "optional",
}


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9_-]+", "-", s.strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def research_description(body: str) -> list:
    if not body:
        return []
    hints = []
    for rule in REQUIREMENT_RULES:
        for m in rule["re"].finditer(body):
            groups = list(m.groups())
            candidates = [c for c in rule["candidates"]([m.group(0)] + groups)
                          if c and len(c) >= 3 and c not in STOP]
            if not candidates:
                continue
            phrase = m.group(0).strip()[:80]
            if not any(h["phrase"] == phrase for h in hints):
                hints.append({"phrase": phrase, "candidates": candidates})
    return hints
