"""Small database boundary used by the intelligence repository.

The current deployment uses SQLite, but schema changes run through a backend
and migration interface so a PostgreSQL implementation can be introduced
without changing the intelligence domain objects.
"""

from __future__ import annotations

import sqlite3
import subprocess
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol


class DatabaseBackend(Protocol):
    """Minimal connection boundary shared by future database backends."""

    def connect(self) -> Any:
        """Return a transactional connection."""

    def backup_to(self, destination: str | Path) -> None:
        """Write a portable backend backup to ``destination``."""


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
        applied = set()
        for row in connection.execute(f"SELECT version FROM {cls.table}").fetchall():
            applied.add(int(row[0] if not isinstance(row, Mapping) else row["version"]))
        for migration in sorted(migrations, key=lambda item: item.version):
            if migration.version in applied:
                continue
            connection.executescript(migration.sql)
            connection.execute(
                f"INSERT INTO {cls.table}(version,name,applied_at) VALUES(?,?,CURRENT_TIMESTAMP)",
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

    def backup_to(self, destination: str | Path) -> None:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        source = self.connect()
        try:
            output = sqlite3.connect(target)
            try:
                source.backup(output)
            finally:
                output.close()
        finally:
            source.close()

    @staticmethod
    def restore_from(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        source_db = sqlite3.connect(source_path)
        try:
            target_db = sqlite3.connect(destination_path)
            try:
                source_db.backup(target_db)
            finally:
                target_db.close()
        finally:
            source_db.close()


class _PostgreSQLConnection:
    """Adapt psycopg's connection to the repository's tiny DB interface."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    @staticmethod
    def _sql(sql: str) -> str:
        sql = sql.replace("MIN(indicators.first_seen,excluded.first_seen)", "LEAST(indicators.first_seen,excluded.first_seen)")
        sql = sql.replace("MAX(indicators.last_seen,excluded.last_seen)", "GREATEST(indicators.last_seen,excluded.last_seen)")
        sql = sql.replace("MIN(first_seen,?)", "LEAST(first_seen,?)")
        return re.sub(r"\?", "%s", sql)

    def execute(self, sql: str, params: Iterable[Any] = ()) -> Any:
        return self._connection.execute(self._sql(sql), tuple(params))

    def executescript(self, sql: str) -> None:
        for statement in (part.strip() for part in sql.split(";")):
            if statement:
                statement = statement.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
                self.execute(statement)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "_PostgreSQLConnection":
        return self

    def __exit__(self, exc_type: Any, _exc: Any, _tb: Any) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()


class PostgreSQLBackend:
    """Optional psycopg backend for the same intelligence repository."""

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN must not be empty")
        self.dsn = dsn

    def connect(self) -> _PostgreSQLConnection:
        try:
            psycopg = __import__("psycopg")
            rows = __import__("psycopg.rows", fromlist=["dict_row"])
        except ImportError as exc:  # pragma: no cover - optional deployment dependency
            raise RuntimeError("Install the 'postgres' extra to use PostgreSQLBackend") from exc
        return _PostgreSQLConnection(psycopg.connect(self.dsn, row_factory=rows.dict_row))

    def backup_to(self, destination: str | Path) -> None:
        output = Path(destination)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as handle:
            subprocess.run(["pg_dump", "--format=custom", self.dsn], check=True, stdout=handle)

    def restore_from(self, source: str | Path) -> None:
        subprocess.run(["pg_restore", "--clean", "--if-exists", "--dbname", self.dsn, str(source)], check=True)


def backend_from_environment(env: Mapping[str, str], sqlite_path: str | Path) -> DatabaseBackend:
    """Select a backend without importing optional PostgreSQL dependencies."""
    kind = env.get("CLAWFORGE_INTELLIGENCE_BACKEND", "sqlite").strip().casefold()
    if kind in {"postgres", "postgresql"}:
        dsn = env.get("CLAWFORGE_POSTGRES_DSN", "").strip()
        if not dsn:
            raise ValueError("CLAWFORGE_POSTGRES_DSN is required for PostgreSQL backend")
        return PostgreSQLBackend(dsn)
    if kind != "sqlite":
        raise ValueError(f"unsupported intelligence backend: {kind}")
    return SQLiteBackend(sqlite_path)


__all__ = [
    "DatabaseBackend",
    "Migration",
    "MigrationRunner",
    "PostgreSQLBackend",
    "SQLiteBackend",
    "backend_from_environment",
]
