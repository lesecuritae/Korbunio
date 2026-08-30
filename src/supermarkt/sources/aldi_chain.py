from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Protocol, Sequence

from ..models import LoadResult, offer_from_dict, offer_to_dict


class AldiOfferProvider(Protocol):
    """Replaceable provider boundary; the resolver never knows providers."""

    def load(self, retailer: str) -> LoadResult: ...


class AldiOfferChain:
    """First-party providers followed by a region-strict last-known-good cache.

    External catalogue adapters stay in SourceLoader and are considered only
    after this chain returns no catalogue, so catalogues are never mixed.
    """

    # v3 invalidates ALDI-Süd catalogues that discarded official brands and
    # used the old multipack-only deposit calculation.
    SCHEMA_VERSION = 3
    TABLE = "aldi_region_catalogues"

    def __init__(self, db_path: Path, providers: Sequence[AldiOfferProvider], ttl_seconds: int = 7 * 86400) -> None:
        self.db_path = Path(db_path)
        self.providers = tuple(providers)
        self.ttl_seconds = max(3600, int(ttl_seconds))
        self._lock = threading.RLock()
        self.last_source: dict[str, str] = {}
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                f"CREATE TABLE IF NOT EXISTS {self.TABLE} ("
                "retailer TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, "
                "fetched_at REAL NOT NULL, payload TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=20)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _put(self, retailer: str, result: LoadResult, now: float) -> None:
        payload = json.dumps([offer_to_dict(item) for item in result.offers], ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connect() as db:
            db.execute(
                f"INSERT INTO {self.TABLE}(retailer,schema_version,fetched_at,payload) VALUES(?,?,?,?) "
                "ON CONFLICT(retailer) DO UPDATE SET schema_version=excluded.schema_version,fetched_at=excluded.fetched_at,payload=excluded.payload",
                (retailer, self.SCHEMA_VERSION, now, payload),
            )

    def _get(self, retailer: str, now: float) -> LoadResult | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                f"SELECT schema_version,fetched_at,payload FROM {self.TABLE} WHERE retailer=?",
                (retailer,),
            ).fetchone()
        if row is None or int(row[0]) != self.SCHEMA_VERSION or now - float(row[1]) > self.ttl_seconds:
            return None
        try:
            offers = [offer_from_dict(item) for item in json.loads(row[2])]
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return LoadResult(offers, []) if offers else None

    def load(self, retailer: str) -> LoadResult:
        if retailer not in {"ALDI Nord", "ALDI Süd"}:
            return LoadResult([], ["Unbekannte ALDI-Region"])
        errors: list[str] = []
        now = time.time()
        for index, provider in enumerate(self.providers, 1):
            try:
                result = provider.load(retailer)
                errors.extend(result.request_errors)
                if result.offers:
                    self._put(retailer, result, now)
                    self.last_source[retailer] = f"official:{index}"
                    return LoadResult(result.offers, errors)
            except Exception as exc:
                errors.append(f"official:{index}: {type(exc).__name__}: {exc}")
        cached = self._get(retailer, now)
        if cached is not None:
            self.last_source[retailer] = "last-known-good"
            return LoadResult(cached.offers, [*errors, "gültiger regionsgleicher Last-known-good-Cache verwendet"])
        self.last_source[retailer] = "failed"
        return LoadResult([], errors)
