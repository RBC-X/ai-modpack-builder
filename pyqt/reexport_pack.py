"""Re-export the repaired flagship pack (b-19fed8cb2cc) so the archives include
Serene Seasons + GlitchCore, then validate every archive."""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path

from engine.bridge import PyEngine
from engine.core import BuildLogger, sanitize_filename, format_bytes
from engine.exports import (export_mrpack, export_curseforge, export_server_pack,
                            validate_mrpack, validate_curseforge_zip)

BUILD_ID = "b-19fed8cb2cc-1b65ae48"
api = PyEngine()
rec = api.build(BUILD_ID)
build_dir = (Path("workspace/builds") / BUILD_ID).resolve()
logger = BuildLogger(BUILD_ID, build_dir)

selections = rec.get("selections") or []
graph = rec.get("graph") or {"nodes": {}}
mc = rec["requirements"]["minecraftVersion"]
loader = rec["requirements"]["loader"]
prompt = rec.get("request") or ""
perf = rec.get("perfEstimate") or {}
name_slug = sanitize_filename(rec["name"], "pack")
out_dir = build_dir / "exports"

cf_refs = [{"slug": s["slug"], "projectID": int(s["projectId"]), "fileID": int(s["versionId"])}
           for s in selections if s["provider"] == "curseforge" and s.get("versionId")]

print(f"re-exporting {len([s for s in selections if s.get('selected', True) and s.get('projectType')=='mod'])} selected mods…")
mods_dir = build_dir / "downloads" / "mods"
game_dir = build_dir / "instance" / "minecraft"

mr = export_mrpack({
    "name": rec["name"], "summary": prompt[:200], "mcVersion": mc,
    "loader": loader, "loaderVersion": None,
    "selections": selections, "graph": graph,
    "modsDir": str(mods_dir), "overridesDir": str(game_dir),
    "outPath": str(out_dir / f"{name_slug}.mrpack"), "logger": logger,
})
cf = export_curseforge({
    "name": rec["name"], "version": "1.0.0", "mcVersion": mc,
    "loader": loader, "loaderVersion": None,
    "selections": selections, "cfReferences": cf_refs,
    "modsDir": str(mods_dir), "overridesDir": str(game_dir),
    "outPath": str(out_dir / f"{name_slug}-CurseForge.zip"), "logger": logger,
})
sp = export_server_pack({
    "name": rec["name"], "mcVersion": mc, "loader": loader,
    "selections": selections,
    "modsDir": str(mods_dir), "overridesDir": str(game_dir),
    "outPath": str(out_dir / f"{name_slug}-Server.zip"), "perf": perf, "logger": logger,
})

for e in (mr, cf, sp):
    p = Path(e["path"])
    ok = p.exists() and e.get("validated")
    print(f"  [{('PASS' if ok else 'FAIL')}] {e['kind']}: {format_bytes(e.get('sizeBytes') or 0)} validated={e.get('validated')}")
    for d in (e.get("validationDetails") or [])[-3:]:
        print(f"       {d}")

all_ok = all(Path(e["path"]).exists() and e.get("validated") for e in (mr, cf, sp))
# also confirm the mrpack contains Serene Seasons
import zipfile
with zipfile.ZipFile(mr["path"]) as zf:
    idx = json.loads(zf.read("modrinth.index.json"))
    files = [f["path"] for f in idx.get("files") or []]
    has_serene = any("serene" in f.lower() for f in files)
    print("  mrpack contains Serene Seasons:", has_serene)
print(f"\n[{'PASS' if all_ok and has_serene else 'FAIL'}] REEXPORT {'PASS' if all_ok and has_serene else 'FAIL'}")
sys.exit(0 if (all_ok and has_serene) else 1)
