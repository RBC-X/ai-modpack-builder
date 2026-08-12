"""Download manager — Python port of src/downloads/manager.ts.

Downloads every selected file with per-file + total size budgets, SHA1
verification, sanitized filenames, and clear skip records when a provider
forbids bundling (CurseForge).
"""
from __future__ import annotations

from pathlib import Path

from .core import (download_to_file, sanitize_filename, sha1_hex, format_bytes,
                   mkdirp)
from .providers.curseforge import cf_download_headers


def download_pack_files(nodes: list, downloads_root, opts: dict) -> dict:
    logger = opts["logger"]
    max_total_mb = opts.get("maxTotalDownloadMB", opts.get("maxTotalMB", 600))
    mods_dir = Path(downloads_root) / "mods"
    mkdirp(mods_dir)
    records = []
    failed = []
    file_by_key = {}
    total_bytes = 0
    max_total = max_total_mb * 1024 ** 2

    selected = [n for n in nodes if n.get("selected")]
    logger.stage("download", f"Downloading {len(selected)} files (budget {max_total_mb} MB)…")
    idx = 0
    for node in selected:
        idx += 1
        version = node.get("version")
        files = (version or {}).get("files") or []
        f = next((x for x in files if x.get("primary")), files[0] if files else None)
        if not version or not f:
            records.append({"key": node["key"], "versionId": (version or {}).get("versionId", "?"),
                            "filename": "?", "url": "", "sizeBytes": 0, "status": "skipped", "error": "no file"})
            continue
        if not f.get("url"):
            records.append({"key": node["key"], "versionId": version["versionId"], "filename": f.get("filename", ""),
                            "url": "", "sizeBytes": f.get("size") or 0, "status": "skipped",
                            "error": "provider forbids direct bundling; exported via manifest reference"})
            logger.info("download", f"SKIP {node['project']['title']}: {records[-1]['error']}")
            continue
        if total_bytes + (f.get("size") or 0) > max_total:
            records.append({"key": node["key"], "versionId": version["versionId"], "filename": f.get("filename", ""),
                            "url": f.get("url", ""), "sizeBytes": f.get("size") or 0, "status": "skipped",
                            "error": f"total budget {format_bytes(max_total)} exceeded"})
            logger.warn("download", f"SKIP {node['project']['title']}: download budget exceeded")
            continue
        # Mods are named {slug}-{version}.jar; NON-mod files (shader packs,
        # resource packs, datapacks) keep the provider's real filename and
        # extension — a shader zip named "*.jar" would be invisible to
        # Iris/Oculus scanning shaderpacks/ for *.zip.
        if node["project"].get("projectType", "mod") == "mod":
            name = sanitize_filename(f"{node['project']['slug']}-{version['versionNumber']}.jar", "mod.jar")
        else:
            real = f.get("filename") or f"{node['project']['slug']}-{version['versionNumber']}.zip"
            name = sanitize_filename(real, f"{node['project']['slug']}.zip")
        dest = mods_dir / name
        import time as _t
        started = _t.time() * 1000
        try:
            expected_sha1 = str((f.get("hashes") or {}).get("sha1") or "").lower()
            if dest.exists() and expected_sha1 and sha1_hex(dest.read_bytes()).lower() != expected_sha1:
                logger.warn("download", f"Cached file failed provider hash verification; downloading {name} again")
                dest.unlink()
            if not dest.exists():
                download_to_file(f["url"], dest,
                                 max_bytes=max((f.get("size") or 0) * 2 + 1024 * 1024, 5 * 1024 ** 2),
                                 expected_sha1=expected_sha1 or None,
                                 timeout_ms=300000,
                                 headers=cf_download_headers(f["url"]))
            buf = dest.read_bytes()
            sha1 = sha1_hex(buf)
            if expected_sha1 and sha1.lower() != expected_sha1:
                dest.unlink(missing_ok=True)
                raise ValueError(f"SHA-1 mismatch: expected {expected_sha1}, got {sha1}")
            total_bytes += len(buf)
            file_by_key[node["key"]] = str(dest)
            records.append({"key": node["key"], "versionId": version["versionId"], "filename": name,
                            "url": f.get("url", ""), "sizeBytes": len(buf), "sha1": sha1,
                            "status": "ok", "tookMs": int(_t.time() * 1000 - started)})
            logger.info("download", f"[{idx}/{len(selected)}] {node['project']['title']} {version['versionNumber']} ({format_bytes(len(buf))})")
        except Exception as e:
            msg = str(e)
            failed.append(node["project"]["title"])
            records.append({"key": node["key"], "versionId": version["versionId"], "filename": name,
                            "url": f.get("url", ""), "sizeBytes": f.get("size") or 0, "status": "failed",
                            "error": msg, "tookMs": int(_t.time() * 1000 - started)})
            logger.warn("download", f"FAIL {node['project']['title']}: {msg}")
    ok_count = len([r for r in records if r["status"] == "ok"])
    skip_count = len([r for r in records if r["status"] == "skipped"])
    logger.ok("download", f"{ok_count} downloaded, {skip_count} skipped, {len(failed)} failed")
    return {"records": records, "modsDir": str(mods_dir), "totalBytes": total_bytes,
            "failed": failed, "fileByKey": file_by_key}
