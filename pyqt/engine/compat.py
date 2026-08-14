"""Compatibility memory — Python port of src/memory/compatDb.ts.

Persistent local database of every real test outcome, backed by stdlib
sqlite3. Designed so a remote/shared compatibility service can be added later
behind the same interface.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .core import workspace_dir, uid


class CompatibilityDatabase:
    """Thread-safe SQLite store. Builds run on worker threads while the
    connection is created on the main thread, so the connection is opened
    with check_same_thread=False and every operation is serialized by a lock."""

    def __init__(self, db_path=None):
        self.path = db_path or str(workspace_dir() / "compat" / "compat.db")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the schema on every open (idempotent). This must live in
        __init__: a stale copy of it sat inside a shadowed close() method, so
        fresh databases (new installs, CI workspaces) were never created and
        the first query failed with 'no such table: entries'."""
        with self._lock:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS entries (
                    id TEXT PRIMARY KEY,
                    minecraft_version TEXT NOT NULL,
                    loader TEXT NOT NULL,
                    loader_version TEXT,
                    java_version TEXT,
                    mods TEXT NOT NULL,
                    result TEXT NOT NULL,
                    crash_signature TEXT,
                    exception TEXT,
                    world_ok INTEGER,
                    server_ok INTEGER,
                    memory_mb INTEGER,
                    repair TEXT,
                    resolution TEXT,
                    build_id TEXT,
                    ts TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_entries_mc_loader ON entries(minecraft_version, loader);
                CREATE INDEX IF NOT EXISTS idx_entries_result ON entries(result);
            """)

    def record(self, entry: dict) -> None:
        eid = entry.get("id") or uid("mem-")
        ts = entry.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO entries (id, minecraft_version, loader, loader_version, java_version,"
                " mods, result, crash_signature, exception, world_ok, server_ok, memory_mb, repair, resolution, build_id, ts)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, entry.get("minecraftVersion", ""), entry.get("loader", ""),
                 entry.get("loaderVersion"), entry.get("javaVersion"),
                 json.dumps(entry.get("mods") or {}), entry.get("result", ""),
                 entry.get("crashSignature"), entry.get("exception"),
                 1 if entry.get("worldLoadOk") is True else (0 if entry.get("worldLoadOk") is False else None),
                 1 if entry.get("serverStartOk") is True else (0 if entry.get("serverStartOk") is False else None),
                 entry.get("memoryMB"), entry.get("repair"), entry.get("resolution"),
                 entry.get("buildId"), ts),
            )
            self.db.commit()

    def best_result_for_mod(self, mc: str, loader: str, mod_slug: str = "", mod_id: str = ""):
        if not mod_slug or mod_slug == "auto":
            return None
        with self._lock:
            rows = self.db.execute(
                "SELECT mods, result, crash_signature, repair FROM entries"
                " WHERE minecraft_version = ? AND loader = ? ORDER BY ts DESC LIMIT 40",
                (mc, loader)).fetchall()
        for mods_raw, result, sig, repair in rows:
            try:
                mods = json.loads(mods_raw)
            except Exception:
                continue
            for k in (mod_slug, mod_id, mod_slug.lower()):
                if k in mods:
                    return {"result": result, "crashSignature": sig,
                            "repair": repair, "mods": list(mods.keys())}
        return None

    def history_for(self, mc: str, loader: str, limit: int = 20) -> list:
        with self._lock:
            rows = self.db.execute(
                "SELECT * FROM entries WHERE minecraft_version = ? AND loader = ?"
                " ORDER BY ts DESC LIMIT ?", (mc, loader, limit)).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def resolution_for_signature(self, signature: str, limit: int = 10) -> list:
        with self._lock:
            rows = self.db.execute(
                "SELECT * FROM entries WHERE crash_signature = ? AND resolution IS NOT NULL"
                " ORDER BY ts DESC LIMIT ?", (signature, limit)).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return int(self.db.execute("SELECT COUNT(*) AS c FROM entries").fetchone()[0])

    def close(self) -> None:
        try:
            with self._lock:
                self.db.close()
        except Exception:
            pass

    def _row_to_entry(self, r) -> dict:
        with self._lock:
            cols = [d[0] for d in self.db.execute("SELECT * FROM entries LIMIT 0").description]
        row = dict(zip(cols, r))
        try:
            mods = json.loads(row.get("mods") or "{}")
        except Exception:
            mods = {}
        return {
            "id": row["id"], "minecraftVersion": row["minecraft_version"],
            "loader": row["loader"], "loaderVersion": row.get("loader_version"),
            "javaVersion": row.get("java_version"), "mods": mods,
            "result": row["result"], "crashSignature": row.get("crash_signature"),
            "exception": row.get("exception"),
            "worldLoadOk": None if row.get("world_ok") is None else bool(row.get("world_ok")),
            "serverStartOk": None if row.get("server_ok") is None else bool(row.get("server_ok")),
            "memoryMB": row.get("memory_mb"), "repair": row.get("repair"),
            "resolution": row.get("resolution"), "buildId": row.get("build_id"),
            "timestamp": row["ts"],
        }
