"""Backup and restore primitives for intelligence state.

The manager keeps database state, operator configuration, explicitly selected
secret files, and the trusted-network registry in one operator-owned bundle.
It never discovers or exports secrets implicitly.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .network_trust import TrustedNetworkRegistry
from .persistence import PostgreSQLBackend, SQLiteBackend


@dataclass(frozen=True)
class BackupManifest:
    version: int
    created_at: str
    backend: str
    database_file: str
    config_files: tuple[str, ...]
    secret_files: tuple[str, ...]
    trust_registry_file: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "backend": self.backend,
            "database_file": self.database_file,
            "config_files": list(self.config_files),
            "secret_files": list(self.secret_files),
            "trust_registry_file": self.trust_registry_file,
        }


class BackupManager:
    """Create and restore explicit, local intelligence backups."""

    manifest_name = "manifest.json"
    database_name = "intelligence.sqlite3"

    @classmethod
    def create(
        cls,
        store: Any,
        destination: str | Path,
        *,
        config_paths: Iterable[str | Path] = (),
        secret_paths: Iterable[str | Path] = (),
        trust_registry: TrustedNetworkRegistry | None = None,
    ) -> Path:
        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        backend = store.backend
        database_file = cls.database_name if isinstance(backend, SQLiteBackend) else "intelligence.dump"
        backend.backup_to(root / database_file)

        config_dir = root / "config"
        secret_dir = root / "secrets"
        copied_config = cls._copy_files(config_paths, config_dir, mode=None)
        copied_secrets = cls._copy_files(secret_paths, secret_dir, mode=0o600)
        trust_file: str | None = None
        if trust_registry is not None:
            trust_file = "trust-registry.json"
            (root / trust_file).write_text(trust_registry.to_json(), encoding="utf-8")
            os.chmod(root / trust_file, 0o600)

        manifest = BackupManifest(
            version=1,
            created_at=datetime.now(UTC).isoformat(),
            backend="sqlite" if isinstance(backend, SQLiteBackend) else "postgresql",
            database_file=database_file,
            config_files=tuple(copied_config),
            secret_files=tuple(copied_secrets),
            trust_registry_file=trust_file,
        )
        (root / cls.manifest_name).write_text(json.dumps(manifest.as_dict(), indent=2) + "\n", encoding="utf-8")
        return root

    @staticmethod
    def _copy_files(paths: Iterable[str | Path], destination: Path, *, mode: int | None) -> list[str]:
        destination.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for value in paths:
            source = Path(value)
            if not source.is_file():
                raise FileNotFoundError(source)
            target = destination / source.name
            shutil.copy2(source, target)
            if mode is not None:
                os.chmod(target, mode)
            copied.append(str(target.relative_to(destination.parent)))
        return copied

    @classmethod
    def restore(
        cls,
        source: str | Path,
        destination: str | Path,
        *,
        backend: SQLiteBackend | PostgreSQLBackend | None = None,
        restore_config: bool = True,
        restore_secrets: bool = True,
    ) -> TrustedNetworkRegistry | None:
        root = Path(source)
        target = Path(destination)
        manifest = json.loads((root / cls.manifest_name).read_text(encoding="utf-8"))
        target.mkdir(parents=True, exist_ok=True)
        database_source = root / str(manifest["database_file"])
        if manifest["backend"] == "sqlite":
            SQLiteBackend.restore_from(database_source, target / cls.database_name)
        elif backend is not None and isinstance(backend, PostgreSQLBackend):
            backend.restore_from(database_source)
        else:
            raise ValueError("a PostgreSQL backend is required to restore a PostgreSQL dump")

        if restore_config:
            cls._restore_files(root, manifest.get("config_files", []), target / "config", mode=None)
        if restore_secrets:
            cls._restore_files(root, manifest.get("secret_files", []), target / "secrets", mode=0o600)

        trust_file = manifest.get("trust_registry_file")
        if trust_file:
            return TrustedNetworkRegistry.from_json((root / str(trust_file)).read_text(encoding="utf-8"))
        return None

    @staticmethod
    def _restore_files(root: Path, files: Iterable[str], destination: Path, *, mode: int | None) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for relative in files:
            source = root / str(relative)
            if not source.is_file() or source.is_symlink():
                raise FileNotFoundError(source)
            target = destination / source.name
            shutil.copy2(source, target)
            if mode is not None:
                os.chmod(target, mode)


__all__ = ["BackupManifest", "BackupManager"]
