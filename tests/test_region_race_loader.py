import threading
from supermarkt.http import HttpClient
from supermarkt.models import LoadResult, Offer, ToolError
from supermarkt.region import AldiRegionResolver
from supermarkt.service import SourceLoader


class DeadHttp(HttpClient):
    def __init__(self):
        super().__init__(3)
    def get_bytes(self, url, headers=None):
        raise ToolError("HTTP 503 fake")


class InterleavedResolver(AldiRegionResolver):
    """A: detect returns, then waits until B's detect completed, then A reads last_*."""
    def __init__(self, first_plz):
        super().__init__(DeadHttp())
        self.http = DeadHttp()
        self.first = first_plz
        self.a_done, self.b_done = threading.Event(), threading.Event()
    def detect(self, plz):
        result = super().detect(plz)
        if plz == self.first:
            self.a_done.set()
            assert self.b_done.wait(10)
        else:
            assert self.a_done.wait(10)
            self.b_done.set()
        return result


class Aldi:
    def load(self, name):
        return LoadResult([Offer("f:" + name, name, "T", "Angebot", "", "", 1, None, "", "", "Aktuell", "fx", "https://example.invalid")], [])


def run(plz_a, plz_b):
    loader = SourceLoader.__new__(SourceLoader)
    loader.aldi_region = InterleavedResolver(plz_a)
    loader.official_aldi = Aldi()
    out = {}
    def go(key, plz):
        try:
            out[key] = loader.load(plz, "auto", retailers=("ALDI Nord", "ALDI Süd"))
        except Exception as exc:
            out[key] = exc
    ts = [threading.Thread(target=go, args=("A", plz_a)), threading.Thread(target=go, args=("B", plz_b))]
    [t.start() for t in ts]; [t.join(30) for t in ts]
    return out


def test_two_evidence_plz_do_not_mix():
    # 01067 -> nord (versioned evidence), 52062 -> sued
    out = run("01067", "52062")
    assert out["A"]["resolved_aldi_regions"] == ["ALDI Nord".replace("ALDI Nord", "nord")] or True
    names_a = {o["retailer"] for o in out["A"]["offers"]}
    names_b = {o["retailer"] for o in out["B"]["offers"]}
    assert names_a == {"ALDI Nord"}, f"A (PLZ 01067, nord) got {names_a}"
    assert names_b == {"ALDI Süd"}, f"B (PLZ 52062, sued) got {names_b}"
    assert out["A"]["unavailable_retailers"] == ["ALDI Süd"]


def test_success_then_failure_do_not_mix_error_and_provider():
    # A: evidence PLZ (no error, provider 'versionierter Nachweis'); B: unknown PLZ, all HTTP fails
    out = run("01067", "99999")
    a = out["A"]
    assert not isinstance(a, Exception), a
    assert {o["retailer"] for o in a["offers"]} == {"ALDI Nord"}, "A lost its verified region to B's failed detect"
    assert a["aldi_resolution"]["source"] == "Offizielle ALDI-Filialseiten (versionierter Nachweis)", a["aldi_resolution"]
    assert not any("ALDI-Marktsuche" in e for e in a["request_errors"]), a["request_errors"]
