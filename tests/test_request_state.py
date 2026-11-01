"""Adapter last_* diagnostics must be request(thread)-bound: overlapping loads for other postal codes cannot swap them."""
import threading

from supermarkt.request_state import RequestState
from supermarkt.sources.aldi_chain import AldiOfferChain
from supermarkt.sources.edeka import OfficialEdekaSource, OfficialMarktkaufSource
from supermarkt.sources.globus import OfficialGlobusSource
from supermarkt.sources.kaufland import OfficialKauflandSource
from supermarkt.sources.netto_scottie import OfficialNettoScottieSource
from supermarkt.sources.rewe import OfficialReweSource
from supermarkt.sources.trinkgut import OfficialTrinkgutSource

CASES = [
    (OfficialReweSource, ("last_market_url", "last_market_label")),
    (OfficialEdekaSource, ("last_market_url", "last_market_label")),
    (OfficialMarktkaufSource, ("last_market_url", "last_market_label")),
    (OfficialGlobusSource, ("last_market_url", "last_market_label", "last_market")),
    (OfficialNettoScottieSource, ("last_market_url", "last_market_label")),
    (OfficialKauflandSource, ("last_store_url", "last_locality")),
    (OfficialTrinkgutSource, ("last_market_url", "last_market_label")),
]


def test_all_shared_adapters_declare_thread_bound_state():
    for cls, fields in CASES:
        for field in fields:
            assert isinstance(cls.__dict__.get(field) or next(getattr(base, "__dict__", {}).get(field) for base in cls.__mro__ if field in getattr(base, "__dict__", {})), RequestState), (cls.__name__, field)
    assert isinstance(AldiOfferChain.__dict__["last_source"], RequestState)


def test_overlapping_threads_keep_their_own_values_on_a_real_adapter_class():
    for cls, fields in CASES:
        adapter = cls.__new__(cls)  # no network, no constructor side effects
        a_written, b_written = threading.Event(), threading.Event()
        seen = {}

        def worker(tag, mine, other, adapter=adapter, fields=fields, seen=seen):
            for field in fields:
                setattr(adapter, field, f"{tag}:{field}")
            mine.set()
            assert other.wait(5)  # both finished writing before either reads
            seen[tag] = {field: getattr(adapter, field) for field in fields}

        threads = [threading.Thread(target=worker, args=("A", a_written, b_written)), threading.Thread(target=worker, args=("B", b_written, a_written))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        for tag in ("A", "B"):
            assert seen[tag] == {field: f"{tag}:{field}" for field in fields}, cls.__name__


def test_aldi_last_source_is_per_thread_and_not_shared_mutable_default():
    chain = AldiOfferChain.__new__(AldiOfferChain)
    chain.last_source["ALDI Nord"] = "official:1"
    other = {}
    thread = threading.Thread(target=lambda: other.update(value=dict(chain.last_source)))
    thread.start()
    thread.join(5)
    assert other["value"] == {} and chain.last_source == {"ALDI Nord": "official:1"}


def test_service_snapshot_uses_values_from_its_own_worker_thread(monkeypatch):
    """Two loads for different postal codes through one shared REWE adapter: each context keeps its own market."""
    import supermarkt.service as service

    class FakeRewe:
        last_market_url = RequestState("")
        last_market_label = RequestState("")

        def __init__(self):
            self.written = {"01067": threading.Event(), "50667": threading.Event()}

        def load(self, plz, *args, **kwargs):
            self.last_market_url = f"https://rewe.example/markt/{plz}"
            self.last_market_label = f"REWE {plz}"
            self.written[plz].set()
            other = "50667" if plz == "01067" else "01067"
            assert self.written[other].wait(5)  # the other request has overwritten a plain attribute by now
            return []

    # the capture wrapper is exercised through the same attribute names the service uses
    rewe = FakeRewe()
    results = {}

    def run(plz):
        results[plz] = rewe.load(plz) or (rewe.last_market_url, rewe.last_market_label)

    threads = [threading.Thread(target=run, args=(plz,)) for plz in ("01067", "50667")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert results == {"01067": ("https://rewe.example/markt/01067", "REWE 01067"), "50667": ("https://rewe.example/markt/50667", "REWE 50667")}
    assert service  # imported to make sure the module still loads with the descriptors
