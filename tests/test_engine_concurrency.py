import threading
from concurrent.futures import ThreadPoolExecutor

from supermarkt import service


def make_engine(monkeypatch, tmp_path, load):
    monkeypatch.setattr(service, "CACHE_DB", tmp_path / "snapshots.sqlite3")
    monkeypatch.setattr(service, "SourceLoader", lambda: type("Loader", (), {"load": staticmethod(load)})())
    monkeypatch.setattr(service.history, "record", lambda *_args: None)
    return service.SupermarketEngine()


def test_independent_catalogues_overlap_through_real_engine_and_sqlite(monkeypatch, tmp_path):
    overlap = threading.Barrier(3, timeout=3)

    def load(_postal_code, _region, **kwargs):
        overlap.wait()
        return {"offers": [], "retailers": list(kwargs["retailers"])}

    engine = make_engine(monkeypatch, tmp_path, load)
    names = ["REWE", "Combi", "dm"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(engine.snapshot, "01067", "auto", retailers=(name,)) for name in names]
        results = [future.result(timeout=5) for future in futures]
    assert [result[0]["retailers"] for result in results] == [[name] for name in names]
    assert all(not cached for _snapshot, cached in results)
    assert len({snapshot["search_id"] for snapshot, _cached in results}) == 3


def test_equivalent_keys_still_share_one_refresh(monkeypatch, tmp_path):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def load(_postal_code, _region, **_kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(3)
        return {"offers": []}

    engine = make_engine(monkeypatch, tmp_path, load)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(engine.snapshot, "01067", "auto", retailers=names)
                   for names in [("REWE", "Combi"), ("Combi", "REWE")] * 4]
        assert entered.wait(3)
        release.set()
        results = [future.result(timeout=5) for future in futures]
    assert len(calls) == 1
    assert len({snapshot["search_id"] for snapshot, _cached in results}) == 1
    assert sum(not cached for _snapshot, cached in results) == 1


def test_refresh_capacity_is_bounded_across_distinct_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "MAX_WORKERS", 2)
    two_entered = threading.Event()
    release = threading.Event()
    guard = threading.Lock()
    active = 0
    maximum = 0

    def load(_postal_code, _region, **_kwargs):
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                two_entered.set()
        try:
            assert release.wait(3)
            return {"offers": []}
        finally:
            with guard:
                active -= 1

    engine = make_engine(monkeypatch, tmp_path, load)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(engine.snapshot, "01067", "auto", retailers=(str(i),)) for i in range(8)]
        try:
            assert two_entered.wait(3)
        finally:
            release.set()
        for future in futures:
            future.result(timeout=5)
    assert maximum == 2
