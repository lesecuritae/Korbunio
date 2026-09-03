from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
import zlib
from pathlib import Path
from typing import Any, Optional

from .models import ToolError


class PersistentSnapshotStore:
    """SQLite store with separate freshness and result-retention windows."""

    TABLE = "supermarket_snapshots"

    def __init__(self, path: Path, freshness_minutes: int, retention_hours: int, max_snapshots: int) -> None:
        self.path = path
        self.freshness_seconds = max(60, int(freshness_minutes) * 60)
        self.retention_seconds = max(self.freshness_seconds, int(retention_hours) * 3600)
        self.max_snapshots = max(4, int(max_snapshots))
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE} (
                    search_id TEXT PRIMARY KEY,
                    cache_key TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    fresh_until REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    payload BLOB NOT NULL
                )
                """
            )
            old_tables = [
                row["name"]
                for row in db.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name GLOB 'supermarket_snapshots_*'"
                ).fetchall()
                if row["name"] != self.TABLE
            ]
            for old_table in old_tables:
                if not old_table.replace("_", "").isalnum():
                    continue
                db.execute(f"DROP TABLE IF EXISTS {old_table}")

            db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_supermarket_cache "
                f"ON {self.TABLE}(cache_key, created_at DESC)"
            )
            db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_supermarket_expires "
                f"ON {self.TABLE}(expires_at)"
            )

    @staticmethod
    def _encode(payload: dict[str, Any]) -> bytes:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return zlib.compress(raw, level=6)

    @staticmethod
    def _decode(payload: bytes) -> dict[str, Any]:
        value = json.loads(zlib.decompress(payload).decode("utf-8"))
        if not isinstance(value, dict):
            raise ToolError("Ungültiger Supermarkt-Cache")
        return value

    def _cleanup(self, db: sqlite3.Connection, now: float) -> None:
        db.execute("DELETE FROM supermarket_snapshots WHERE expires_at <= ?", (now,))
        rows = db.execute(
            "SELECT search_id FROM supermarket_snapshots ORDER BY created_at DESC LIMIT -1 OFFSET ?",
            (self.max_snapshots,),
        ).fetchall()
        if rows:
            db.executemany(
                "DELETE FROM supermarket_snapshots WHERE search_id = ?",
                [(row["search_id"],) for row in rows],
            )

    def _decoded_row(self, db: sqlite3.Connection, row: sqlite3.Row) -> Optional[dict[str, Any]]:
        try:
            return self._decode(row["payload"])
        except (OSError, UnicodeDecodeError, ValueError, zlib.error, ToolError):
            db.execute("DELETE FROM supermarket_snapshots WHERE search_id = ?", (row["search_id"],))
            return None

    def get_by_key(self, cache_key: str) -> Optional[dict[str, Any]]:
        now = time.time()
        with self._lock, self._connect() as db:
            self._cleanup(db, now)
            row = db.execute(
                """
                SELECT search_id, created_at, payload
                FROM supermarket_snapshots
                WHERE cache_key = ? AND fresh_until > ? AND expires_at > ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (cache_key, now, now),
            ).fetchone()
            if row is None:
                return None
            payload = self._decoded_row(db, row)
            if payload is None:
                return None
            payload["search_id"] = row["search_id"]
            payload["created_at"] = float(row["created_at"])
            return payload

    def get_by_id(self, search_id: str) -> Optional[dict[str, Any]]:
        now = time.time()
        with self._lock, self._connect() as db:
            self._cleanup(db, now)
            row = db.execute(
                "SELECT search_id, created_at, payload FROM supermarket_snapshots WHERE search_id = ? AND expires_at > ?",
                (search_id, now),
            ).fetchone()
            if row is None:
                return None
            payload = self._decoded_row(db, row)
            if payload is None:
                return None
            payload["search_id"] = search_id
            payload["created_at"] = float(row["created_at"])
            return payload

    def put(self, cache_key: str, payload: dict[str, Any], fresh_until: float | None = None) -> dict[str, Any]:
        """Store a snapshot. ``fresh_until`` overrides the default freshness
        window (a POSIX timestamp); it is never shorter than one minute so a
        caller that passes a moment already in the past still gets a hit."""
        now = time.time()
        if fresh_until is None:
            fresh_until = now + self.freshness_seconds
        else:
            fresh_until = max(float(fresh_until), now + 60)
        search_id = secrets.token_urlsafe(18)
        stored = dict(payload)
        stored.pop("search_id", None)
        stored.pop("created_at", None)
        blob = self._encode(stored)
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO supermarket_snapshots(search_id, cache_key, created_at, fresh_until, expires_at, payload)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    search_id,
                    cache_key,
                    now,
                    fresh_until,
                    max(now + self.retention_seconds, fresh_until),
                    blob,
                ),
            )
            self._cleanup(db, now)
        result = dict(stored)
        result["search_id"] = search_id
        result["created_at"] = now
        return result

    def health(self) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as db:
            self._cleanup(db, now)
            row = db.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(payload)),0) AS bytes FROM supermarket_snapshots"
            ).fetchone()
        return {
            "snapshots": int(row["n"]),
            "compressed_bytes": int(row["bytes"]),
            "path": str(self.path),
            "freshness_seconds": self.freshness_seconds,
            "retention_seconds": self.retention_seconds,
        }
