"""Jar filename → Java module name — Python port of src/repair/jarname.ts.

Forge/NeoForge derive an automatic module name from EVERY jar's filename at
bootstrap; an invalid derived name (Java keyword or digit start, e.g.
`true-power-optimization.jar` → `true`) kills the game before any log file is
written. This module deterministically explains WHY a slug can't load.
"""
from __future__ import annotations

import re
from typing import Optional

JAVA_KEYWORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
    "class", "const", "continue", "default", "do", "double", "else", "enum",
    "extends", "final", "finally", "float", "for", "goto", "if", "implements",
    "import", "instanceof", "int", "interface", "long", "native", "new",
    "package", "private", "protected", "public", "return", "short", "static",
    "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
    "transient", "try", "void", "volatile", "while", "true", "false", "null",
    "var", "record", "sealed", "permits", "yield", "when", "_",
}


def _strip_version(base: str) -> str:
    out = base
    while True:
        m = re.match(r"^(.+)-(\d[\w.+-]*)$", out)
        if not m:
            break
        out = m.group(1)
    return out


def jar_module_name(filename: str) -> Optional[str]:
    base = _strip_version(re.sub(r"\.jar$", "", filename, flags=re.I))
    name = re.sub(r"[^\w.]+", ".", base).lower().strip(".")
    return name or None


def invalid_module_reason(slug: str) -> Optional[str]:
    name = jar_module_name(slug + ".jar")
    if not name:
        return f"jar filename has no usable identifier ({slug})"
    for part in name.split("."):
        if not re.match(r"^[a-z_$][a-z0-9_$]*$", part):
            return f'filename-derived module name "{name}" contains "{part}" — not a valid Java identifier'
        if part in JAVA_KEYWORDS:
            return f'filename-derived module name "{name}" starts with Java keyword "{part}" — Forge cannot load it (invalid module name)'
    return None


def normalize_module_part(s: str) -> str:
    return re.sub(r"[^a-z0-9$_.]+", ".", s.lower())


def find_invalid_module_jar(invalid_name: str, slugs: list) -> Optional[str]:
    target = normalize_module_part(invalid_name)
    for slug in slugs:
        if normalize_module_part(slug) == target:
            return slug
    for slug in slugs:
        norm = normalize_module_part(slug)
        if norm.startswith(target) or target.startswith(norm):
            return slug
    return None
