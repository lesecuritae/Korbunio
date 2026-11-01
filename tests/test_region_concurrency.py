"""Overlapping ALDI region lookups must not leak diagnostics into each other (shared resolver instance)."""
import threading

from supermarkt.region import AldiRegionResolver


class _Http:
    timeout_seconds = 10


def _resolver():
    resolver = AldiRegionResolver(_Http())
    resolver._postal_coordinates = lambda code: (53.0, 10.0) if code == "11111" else (48.0, 11.0)
    return resolver


def test_overlapping_detects_keep_their_own_region_and_error():
    resolver = _resolver()
    a_done_detect, b_done_detect = threading.Event(), threading.Event()
    out, errors = {}, []

    def stores(region):
        # Nord catalogue near PLZ 11111 only; Süd catalogue near PLZ 22222 only.
        return [{"postcode": "11111", "point": (53.0, 10.0)}] if region == "nord" else [{"postcode": "22222", "point": (48.0, 11.0)}]

    resolver._official_stores = stores

    def worker(code, mine, other):
        try:
            result = resolver.detect(code)
            mine.set()
            assert other.wait(5)  # both detect() calls are finished before either reads its diagnostics
            out[code] = (result, resolver.last_regions, resolver.last_absent_regions, resolver.last_error)
        except Exception as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=("11111", a_done_detect, b_done_detect)),
               threading.Thread(target=worker, args=("22222", b_done_detect, a_done_detect))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not errors
    assert out["11111"][:3] == ("nord", ("nord",), ("sued",))
    assert out["22222"][:3] == ("sued", ("sued",), ("nord",))


def test_failure_of_one_lookup_does_not_leak_its_error_to_another():
    resolver = _resolver()
    first_failed, second_ok = threading.Event(), threading.Event()
    seen = {}

    def stores(region):
        raise OSError("catalogue down") if threading.current_thread().name == "bad" else None

    def good_stores(region):
        return [{"postcode": "22222", "point": (48.0, 11.0)}]

    def bad():
        resolver._official_stores = stores
        resolver.detect("33333")
        first_failed.set()
        assert second_ok.wait(5)
        seen["bad_error"] = resolver.last_error

    def good():
        assert first_failed.wait(5)
        resolver._official_stores = good_stores
        resolver.detect("22222")
        seen["good_error"] = resolver.last_error
        second_ok.set()

    threads = [threading.Thread(target=bad, name="bad"), threading.Thread(target=good, name="good")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert seen["good_error"] == ""
    assert seen["bad_error"] != ""
