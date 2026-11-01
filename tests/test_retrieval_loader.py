from types import SimpleNamespace
from supermarkt.service import SourceLoader
from supermarkt.compare import OfferMapper
from supermarkt.models import ToolError

def loader(mg):
    l=SourceLoader.__new__(SourceLoader)
    l.aldi_region=SimpleNamespace(last_error="",last_regions=(),last_absent_regions=())
    l.marktguru=mg; l.mapper=OfferMapper()
    return l

def test_failed_aggregator_for_selected_retailer_is_never_clean_empty():
    class M:
        def load_offers(self,p): raise ToolError("HTTP 429")
        def load_retailer_queries(self,p,n): raise ToolError("HTTP 429")
    try:
        r=loader(M()).load("12345","auto",retailers=("Lidl",))
    except ToolError as e:
        assert "429" in str(e); return
    assert r["request_errors"], "empty-but-ok without request_errors"

def test_empty_but_responding_aggregator_is_flagged():
    class M:
        def load_offers(self,p): return [],[]
        def load_retailer_queries(self,p,n): return [],[]
    try:
        r=loader(M()).load("12345","auto",retailers=("Lidl",))
    except ToolError:
        return
    assert r["request_errors"], r
