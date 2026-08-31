from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any


class SearchCapacityError(RuntimeError):
    pass


class SearchJobStore:
    """Bounded process-local status registry; durable results stay in SQLite."""

    def __init__(self, engine: Any, retention_seconds: int = 3600, max_pending: int = 8) -> None:
        self.engine = engine
        self.retention_seconds = retention_seconds
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="korbklar-search")
        self._capacity = threading.BoundedSemaphore(max(2, int(max_pending)))

    def start(self, postal_code: str, aldi_region: str = "auto", refresh: bool = False, retailers: tuple[str, ...] = (), rewe_market_id: str = "", netto_market_id: str = "", offer_week: str = "current") -> str:
        if not self._capacity.acquire(blocking=False):
            raise SearchCapacityError("Zu viele Suchaufträge aktiv; bitte kurz warten.")
        job_id = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._purge(now)
            self._jobs[job_id] = {"job_id": job_id, "status": "waiting", "postal_code": postal_code, "aldi_region": aldi_region,
                "source": "KorbKlar", "retailer": "Alle Händler", "category": "Alle Kategorien",
                "step": "Suche wird vorbereitet", "progress": 0, "processed_sources": 0,
                "total_sources": 0, "processed_products": 0, "created_at": now, "updated_at": now}
        try:
            self._pool.submit(self._run, job_id, postal_code, aldi_region, refresh, retailers, rewe_market_id, netto_market_id, offer_week)
        except Exception:
            with self._lock:
                self._jobs.pop(job_id, None)
            self._capacity.release()
            raise
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._jobs.get(job_id)
            return dict(value) if value else None

    def _progress(self, job_id: str, **fields: str) -> None:
        with self._lock:
            if job_id in self._jobs:
                total = int(fields.get("total_sources", self._jobs[job_id].get("total_sources", 0)) or 0)
                if "processed_sources" in fields and total:
                    fields["processed_sources"] = min(max(0, int(fields["processed_sources"])), total)
                self._jobs[job_id].update(fields, updated_at=time.time())

    def _run(self, job_id: str, postal_code: str, aldi_region: str, refresh: bool = False, retailers: tuple[str, ...] = (), rewe_market_id: str = "", netto_market_id: str = "", offer_week: str = "current") -> None:
        try:
            snapshot_kwargs = {"progress": lambda **fields: self._progress(job_id, **fields), "retailers": retailers, "rewe_market_id": rewe_market_id, "netto_market_id": netto_market_id}
            if offer_week == "next":
                snapshot_kwargs["offer_week"] = "next"
            snapshot, from_cache = self.engine.snapshot(postal_code, aldi_region, refresh, **snapshot_kwargs)
            self._progress(job_id, status="completed", step="Vergleich ist bereit", progress=100,
                source="Cache" if from_cache else "Live-Quellen", retailer="Alle Händler",
                category="Alle Kategorien", processed_products=len(snapshot.get("offers", [])), search_id=snapshot["search_id"])
        except Exception as exc:
            self._progress(job_id, status="failed", step="Suche fehlgeschlagen", error=str(exc))
        finally:
            self._capacity.release()

    def _purge(self, now: float) -> None:
        for key in [key for key, value in self._jobs.items() if now - value["updated_at"] > self.retention_seconds]:
            self._jobs.pop(key, None)
