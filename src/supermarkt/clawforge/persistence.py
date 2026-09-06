"""Small database boundary used by the intelligence repository.

The current deployment uses SQLite, but schema changes run through a backend
and migration interface so a PostgreSQL implementation can be introduced
without changing the intelligence domain objects.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol


class DatabaseBackend(Protocol):
    """Minimal connection boundary shared by future database backends."""

    def connect(self) -> Any:
        """Return a transactional connection."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


class MigrationRunner:
    """Apply migrations once and retain their versions in the database."""

    table = "schema_migrations"

    @classmethod
    def run(cls, connection: Any, migrations: Iterable[Migration]) -> None:
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {cls.table} ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        applied = {
            int(row[0])
            for row in connection.execute(f"SELECT version FROM {cls.table}").fetchall()
        }
        for migration in sorted(migrations, key=lambda item: item.version):
            if migration.version in applied:
                continue
            connection.executescript(migration.sql)
            connection.execute(
                f"INSERT INTO {cls.table}(version,name,applied_at) VALUES(?,?,datetime('now'))",
                (migration.version, migration.name),
            )
        connection.commit()


class SQLiteBackend:
    """SQLite backend with WAL and bounded lock waits."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection


__all__ = ["DatabaseBackend", "Migration", "MigrationRunner", "SQLiteBackend"]
