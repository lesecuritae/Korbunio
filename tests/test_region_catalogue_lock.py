import json, threading
from unittest.mock import patch
from supermarkt.http import HttpClient
from supermarkt.models import ToolError
from supermarkt.region import AldiRegionResolver


def payload(region):
    loc = [{"name": "ALDI " + ("SÜD" if region == "sued" else "Nord"), "country": "DE", "zip": "50939", "lat": 50.9, "lng": 6.9}]
    p = {"status": "SUCCESS", "response": {"locations": loc}}
    if region == "sued":
        return json.dumps(p).encode()
    page = {"props": {"pageProps": {"apiData": [["STORE_UBERALL_LOCATIONS_GET", {"res": p}]]}}}
    return ('<script id="__NEXT_DATA__">' + json.dumps(page) + '</script>').encode()


class Http(HttpClient):
    def __init__(self):
        super().__init__(3)
        self.block_region, self.release, self.entered = None, threading.Event(), threading.Event()
        self.fail = False
    def get_bytes(self, url, headers=None):
        region = "sued" if "uberall" in url else "nord"
        if region == self.block_region:
            self.entered.set(); assert self.release.wait(20)
        if self.fail:
            raise ToolError("503")
        return payload(region)


def make(h):
    r = AldiRegionResolver(h); r.http = h; return r


def test_second_region_blocked_while_first_does_io():
    h = Http(); h.block_region = "nord"; r = make(h)
    t = threading.Thread(target=r._official_stores, args=("nord",)); t.start()
    assert h.entered.wait(5)
    done = threading.Event()
    def other():
        r._official_stores("sued"); done.set()
    t2 = threading.Thread(target=other); t2.start()
    finished_while_blocked = done.wait(1.5)
    h.release.set(); t.join(); t2.join()
    assert finished_while_blocked, "sued catalogue (different region, no I/O dependency) was blocked by nord I/O under the lock"


def test_cached_fresh_hit_blocked_while_other_region_refreshes():
    h = Http(); r = make(h)
    with patch("supermarkt.region.time.monotonic", return_value=0):
        r._official_stores("sued")
    h.block_region = "nord"
    t = threading.Thread(target=r._official_stores, args=("nord",)); t.start()
    assert h.entered.wait(5)
    done = threading.Event()
    t2 = threading.Thread(target=lambda: (r._official_stores("sued"), done.set())); t2.start()
    ok = done.wait(1.5)
    h.release.set(); t.join(); t2.join()
    assert ok, "fresh cache hit for sued blocked behind nord network I/O"


def test_failed_refresh_after_expiry_is_fail_closed_not_silently_stale():
    # Product decision: an expired catalogue is not served as confirmed evidence when the refresh fails.
    h = Http(); r = make(h)
    with patch("supermarkt.region.time.monotonic", return_value=0):
        r._official_stores("nord")
    h.fail = True
    with patch("supermarkt.region.time.monotonic", return_value=10 * 3600):
        try:
            r._official_stores("nord")
            outcome = "served"
        except ToolError:
            outcome = "raises"
    assert outcome == "raises"
    with patch("supermarkt.region.time.monotonic", return_value=100):
        assert r._official_stores("nord")  # still within TTL of the original good load
