from supermarkt import cache
from supermarkt.cache import PersistentSnapshotStore


def test_snapshot_freshness_and_result_retention_are_separate(monkeypatch, tmp_path):
    now = [1_000_000.0]
    monkeypatch.setattr(cache.time, "time", lambda: now[0])
    store = PersistentSnapshotStore(tmp_path / "cache.sqlite3", freshness_minutes=30, retention_hours=168, max_snapshots=100)

    first = store.put("postal:01067", {"postal_code": "01067", "offers": []})
    assert store.get_by_key("postal:01067")["search_id"] == first["search_id"]

    now[0] += 31 * 60
    assert store.get_by_key("postal:01067") is None
    assert store.get_by_id(first["search_id"])["postal_code"] == "01067"

    second = store.put("postal:01067", {"postal_code": "01067", "offers": [1]})
    assert second["search_id"] != first["search_id"]
    assert store.get_by_id(first["search_id"])["offers"] == []
    assert store.get_by_id(second["search_id"])["offers"] == [1]


def test_expired_result_is_removed(monkeypatch, tmp_path):
    now = [2_000_000.0]
    monkeypatch.setattr(cache.time, "time", lambda: now[0])
    store = PersistentSnapshotStore(tmp_path / "cache.sqlite3", freshness_minutes=30, retention_hours=1, max_snapshots=100)
    result = store.put("postal:01067", {"postal_code": "01067"})

    now[0] += 3601
    assert store.get_by_id(result["search_id"]) is None


def test_snapshot_limit_keeps_newest_results(monkeypatch, tmp_path):
    now = [3_000_000.0]
    monkeypatch.setattr(cache.time, "time", lambda: now[0])
    store = PersistentSnapshotStore(tmp_path / "cache.sqlite3", freshness_minutes=30, retention_hours=168, max_snapshots=4)
    ids = []
    for index in range(6):
        ids.append(store.put(f"key:{index}", {"index": index})["search_id"])
        now[0] += 1

    assert store.get_by_id(ids[0]) is None
    assert store.get_by_id(ids[1]) is None
    assert [store.get_by_id(item)["index"] for item in ids[2:]] == [2, 3, 4, 5]


def test_old_snapshot_table_is_discarded(monkeypatch, tmp_path):
    import sqlite3

    now = [4_000_000.0]
    monkeypatch.setattr(cache.time, "time", lambda: now[0])
    path = tmp_path / "cache.sqlite3"

    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE supermarket_snapshots_old (
                search_id TEXT PRIMARY KEY,
                cache_key TEXT NOT NULL,
                created_at REAL NOT NULL,
                fresh_until REAL NOT NULL,
                expires_at REAL NOT NULL,
                payload BLOB NOT NULL
            )
            """
        )
        payload = PersistentSnapshotStore._encode({"postal_code": "01067", "offers": [1]})
        db.execute(
            "INSERT INTO supermarket_snapshots_old VALUES(?,?,?,?,?,?)",
            ("old-id", "postal:01067", now[0], now[0] + 1800, now[0] + 3600, payload),
        )

    store = PersistentSnapshotStore(path, freshness_minutes=30, retention_hours=1, max_snapshots=100)
    assert store.get_by_id("old-id") is None
    assert store.get_by_key("postal:01067") is None

    with sqlite3.connect(path) as db:
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "supermarket_snapshots_old" not in names
    assert "supermarket_snapshots" in names


def test_corrupt_snapshot_is_removed_instead_of_breaking_cache(tmp_path):
    import sqlite3

    path = tmp_path / "cache.sqlite3"
    store = PersistentSnapshotStore(path, freshness_minutes=30, retention_hours=1, max_snapshots=100)
    result = store.put("postal:01067", {"postal_code": "01067"})

    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE supermarket_snapshots SET payload = ? WHERE search_id = ?",
            (b"not-zlib", result["search_id"]),
        )

    assert store.get_by_key("postal:01067") is None
    assert store.get_by_id(result["search_id"]) is None


def test_corrupt_snapshot_lookup_by_id_removes_entry(tmp_path):
    import sqlite3

    path = tmp_path / "cache.sqlite3"
    store = PersistentSnapshotStore(path, freshness_minutes=30, retention_hours=1, max_snapshots=100)
    result = store.put("postal:01067", {"postal_code": "01067"})

    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE supermarket_snapshots SET payload = ? WHERE search_id = ?",
            (PersistentSnapshotStore._encode(["not", "a", "mapping"]), result["search_id"]),
        )

    assert store.get_by_id(result["search_id"]) is None
    assert store.get_by_key("postal:01067") is None
