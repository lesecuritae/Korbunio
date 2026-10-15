"""Preisverlauf und Beobachtungen (nur lokal, SQLite im Datenordner).

Die Händlerquellen liefern immer nur die aktuelle Woche. Damit man später sehen kann, ob ein
Preis gut ist, schreibt der Server bei jedem frischen Laden mit: pro Tag, Postleitzahl, Händler
und Artikel der niedrigste gesehene Preis. Nach einem Jahr wird aufgeräumt.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import config

log = logging.getLogger(__name__)

RETENTION_DAYS = 400
MAX_WATCHES = 20
_LOCK = threading.Lock()
_pruned_on: str = ""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    day TEXT NOT NULL, plz TEXT NOT NULL, retailer TEXT NOT NULL, key TEXT NOT NULL,
    name TEXT NOT NULL, price_cents INTEGER NOT NULL,
    PRIMARY KEY (day, plz, retailer, key)
);
CREATE INDEX IF NOT EXISTS prices_by_day ON prices(day);
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL, max_cents INTEGER,
    plz TEXT NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notified (
    watch_id INTEGER NOT NULL, offer_key TEXT NOT NULL, PRIMARY KEY (watch_id, offer_key)
);
"""


def _connect() -> sqlite3.Connection:
    config.HISTORY_DB.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.HISTORY_DB, timeout=10)
    connection.executescript(_SCHEMA)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(watches)")}
    if "retailer_ids" not in columns:
        connection.execute("ALTER TABLE watches ADD COLUMN retailer_ids TEXT NOT NULL DEFAULT '[]'")
    if "offer_week" not in columns:
        connection.execute("ALTER TABLE watches ADD COLUMN offer_week TEXT NOT NULL DEFAULT 'current'")
    return connection


def _today() -> str:
    return datetime.now(timezone.utc).astimezone().date().isoformat()


def record(postal_code: str, snapshot: dict[str, Any]) -> None:
    """Preise des frisch geladenen Vergleichs festhalten; darf den Abruf nie stören."""
    global _pruned_on
    try:
        rows = []
        for item in snapshot.get("offers", []):
            if not isinstance(item, dict) or item.get("price") is None:
                continue
            brand, base = str(item.get("brand", "")).strip(), str(item.get("name", "")).strip()
            name = " ".join((base if not brand or brand.casefold() in base.casefold() else f"{brand} {base}").split())
            if not name:
                continue
            key = str(item.get("match_key") or item.get("offer_id") or name)
            rows.append((postal_code, str(item.get("retailer", "")), key, name, round(float(item["price"]) * 100)))
        day = _today()
        with _LOCK, _connect() as db:
            db.executemany(
                "INSERT INTO prices(day, plz, retailer, key, name, price_cents) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(day, plz, retailer, key) DO UPDATE SET price_cents = MIN(price_cents, excluded.price_cents), name = excluded.name",
                [(day, *row) for row in rows],
            )
            if _pruned_on != day:
                db.execute("DELETE FROM prices WHERE day < ?", ((date.fromisoformat(day) - timedelta(days=RETENTION_DAYS)).isoformat(),))
                _pruned_on = day
    except Exception:  # noqa: BLE001 - Mitschreiben ist nur eine Zugabe
        log.warning("Preisverlauf konnte nicht gespeichert werden", exc_info=True)


def price_history(query: str, postal_code: str, days: int = 180) -> list[dict[str, Any]]:
    """Gesehene Preise je Händler und Artikel, die zu allen Wörtern der Suche passen."""
    words = [word.casefold() for word in query.split() if word.strip()]
    if not words:
        return []
    since = (date.fromisoformat(_today()) - timedelta(days=max(1, min(days, RETENTION_DAYS)))).isoformat()
    with _LOCK, _connect() as db:
        rows = db.execute(
            "SELECT day, retailer, key, name, price_cents FROM prices WHERE plz = ? AND day >= ? ORDER BY day",
            (postal_code, since),
        ).fetchall()
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for day, retailer, key, name, cents in rows:
        haystack = name.casefold()
        if not all(word in haystack for word in words):
            continue
        entry = grouped.setdefault((retailer, key), {"retailer": retailer, "product": name, "points": []})
        entry["points"].append((day, cents))
    result = []
    for entry in grouped.values():
        cents = [c for _, c in entry["points"]]
        result.append({
            "retailer": entry["retailer"], "product": entry["product"],
            "first_seen": entry["points"][0][0], "last_seen": entry["points"][-1][0],
            "last_cents": cents[-1], "lowest_cents": min(cents), "highest_cents": max(cents), "days_seen": len(cents),
            "points": entry["points"][-30:],
        })
    result.sort(key=lambda row: (-row["days_seen"], row["retailer"], row["product"]))
    return result[:20]


def retailer_status() -> list[dict[str, Any]]:
    """Wann wurde je Händler zuletzt etwas gesehen, und wie viele Angebote an diesem Tag? (alle Postleitzahlen)"""
    with _LOCK, _connect() as db:
        rows = db.execute(
            "SELECT p.retailer, p.day, COUNT(DISTINCT p.key) FROM prices p JOIN "
            "(SELECT retailer, MAX(day) AS day FROM prices GROUP BY retailer) m ON m.retailer = p.retailer AND m.day = p.day "
            "GROUP BY p.retailer, p.day ORDER BY p.retailer"
        ).fetchall()
    today = date.fromisoformat(_today())
    return [{"retailer": r, "last_day": d, "offers": n, "days_ago": (today - date.fromisoformat(d)).days} for r, d, n in rows]


# ---- Beobachtungen ------------------------------------------------------------------------


def add_watch(query: str, max_cents: int | None, postal_code: str,
              retailer_ids: tuple[str, ...] = (), offer_week: str = "current") -> dict[str, Any]:
    if offer_week not in {"current", "next", "all"}:
        raise ValueError("Angebotszeitraum muss current, next oder all sein.")
    selected = sorted(set(retailer_ids))
    encoded = json.dumps(selected)
    with _LOCK, _connect() as db:
        existing = db.execute(
            "SELECT id FROM watches WHERE lower(query) = lower(?) AND plz = ? AND retailer_ids = ? AND offer_week = ?",
            (query, postal_code, encoded, offer_week),
        ).fetchone()
        if existing:
            watch_id = existing[0]
            db.execute("UPDATE watches SET max_cents = ? WHERE id = ?", (max_cents, watch_id))
        else:
            if db.execute("SELECT COUNT(*) FROM watches").fetchone()[0] >= MAX_WATCHES:
                raise ValueError(f"Es sind höchstens {MAX_WATCHES} Beobachtungen möglich. Bitte erst eine entfernen.")
            cursor = db.execute(
                "INSERT INTO watches(query, max_cents, plz, created, retailer_ids, offer_week) VALUES (?, ?, ?, ?, ?, ?)",
                (query, max_cents, postal_code, _today(), encoded, offer_week),
            )
            watch_id = cursor.lastrowid
    return {"id": watch_id, "query": query, "max_cents": max_cents, "postal_code": postal_code,
            "retailer_ids": selected, "offer_week": offer_week}


def list_watches(postal_code: str | None = None) -> list[dict[str, Any]]:
    with _LOCK, _connect() as db:
        sql = "SELECT id, query, max_cents, plz, retailer_ids, offer_week FROM watches"
        rows = db.execute(sql + (" WHERE plz = ?" if postal_code else "") + " ORDER BY id",
                          (postal_code,) if postal_code else ()).fetchall()
    return [{"id": i, "query": q, "max_cents": m, "postal_code": p,
             "retailer_ids": json.loads(r), "offer_week": w} for i, q, m, p, r, w in rows]


def remove_watch(watch_id: int) -> bool:
    with _LOCK, _connect() as db:
        db.execute("DELETE FROM notified WHERE watch_id = ?", (watch_id,))
        return db.execute("DELETE FROM watches WHERE id = ?", (watch_id,)).rowcount > 0


def unnotified(watch_id: int, keys: list[str]) -> list[str]:
    """Schlüssel, für die noch nicht Bescheid gesagt wurde."""
    with _LOCK, _connect() as db:
        done = {row[0] for row in db.execute("SELECT offer_key FROM notified WHERE watch_id = ?", (watch_id,))}
    return [key for key in keys if key not in done]


def mark_notified(watch_id: int, keys: list[str]) -> None:
    with _LOCK, _connect() as db:
        db.executemany("INSERT OR IGNORE INTO notified(watch_id, offer_key) VALUES (?, ?)", [(watch_id, key) for key in keys])
