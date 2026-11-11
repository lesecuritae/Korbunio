import pytest
from supermarkt.sources.marktguru import MarktguruClient
from supermarkt.models import ToolError

def mk(pages):
    c=MarktguruClient(object(),2,2)
    c._get_credentials=lambda:("a","b")
    c.http=type("H",(),{})()
    def get_json(url,headers=None):
        import urllib.parse as u
        q=dict(u.parse_qsl(u.urlsplit(url).query))
        return pages(q["q"],int(q["offset"]))
    c.http.get_json=get_json
    return c

def test_partial_pages_keep_page_one_offers_or_flag_partial(monkeypatch):
    """Page 2 fails after page 1 ok: offers of page 1 must not vanish silently."""
    monkeypatch.setattr("supermarkt.sources.marktguru.SEARCH_TERMS",("Obst",))
    def pages(q,off):
        if off==0: return {"results":[{"id":"1"},{"id":"2"}]}
        raise ToolError("HTTP 503")
    offers,errors=mk(pages)._load_once("12345") if False else (None,None)
    c=mk(pages)
    try:
        offers,errors=c._load_once("12345")
    except ToolError:
        offers,errors=[],["raised"]
    assert {o["id"] for o in offers}=={"1","2"}, (offers,errors)

def test_partial_term_failure_is_reported(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.marktguru.SEARCH_TERMS",("Obst","Käse"))
    def pages(q,off):
        if q=="Käse": raise ToolError("HTTP 429")
        return {"results":[{"id":"1"}]}
    offers,errors=mk(pages)._load_once("12345")
    assert offers and any("Käse" in e for e in errors)

def test_pagination_cap_truncation_is_flagged(monkeypatch):
    """Endless source: loop stops after 50 pages silently; truncation must be reported."""
    monkeypatch.setattr("supermarkt.sources.marktguru.SEARCH_TERMS",("Obst",))
    n={"c":0}
    def pages(q,off):
        n["c"]+=1
        return {"results":[{"id":f"{off}a"},{"id":f"{off}b"}]}
    offers,errors=mk(pages)._load_once("12345")
    assert n["c"]<=50
    assert errors, f"{len(offers)} offers, hit cap of {n['c']} pages, no error/partial flag"

def test_empty_payloads_raise_not_ok(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.marktguru.SEARCH_TERMS",("Obst",))
    for payload in ({}, {"results":None}, {"results":"x"}):
        c=mk(lambda q,o,p=payload:p)
        with pytest.raises(ToolError): c.load_offers("12345")

def test_retailer_query_total_failure_is_reported_in_errors():
    def pages(q,off): raise ToolError("HTTP 403")
    offers,errors=mk(pages).load_retailer_queries("12345",["Lidl"])
    assert offers==[] and errors


def test_full_page_of_only_known_offers_is_flagged_not_silently_complete(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.marktguru.SEARCH_TERMS", ("Obst",))
    c = mk(lambda q, off: {"results": [{"id": "1"}, {"id": "2"}]})  # page_size 2: the same full page forever
    offers, errors = c._load_once("12345")
    assert {o["id"] for o in offers} == {"1", "2"}
    assert any("bereits bekannte" in e for e in errors)


def test_declared_total_keeps_fetching_after_a_short_page():
    offsets = []
    def pages(_query, offset):
        offsets.append(offset)
        return {"totalResults": 3, "results": [{"id": "1"}] if offset == 0 else [{"id": "2"}, {"id": "3"}]}
    result = mk(pages)._fetch_query_pages("12345", "Lidl", {})
    assert [row["id"] for row in result] == ["1", "2", "3"]
    assert offsets == [0, 1] and not result.note


def test_empty_last_page_with_remaining_declared_results_keeps_evidence_but_reports_partial():
    result = mk(lambda _q, offset: {"totalResults": 3, "results": [{"id": "1"}, {"id": "2"}] if offset == 0 else []})._fetch_query_pages("12345", "Lidl", {})
    assert len(result) == 2 and "unvollständig" in result.note


def test_a_changed_declared_total_is_not_silently_complete():
    result = mk(lambda _q, offset: {"totalResults": 3 if offset == 0 else 4, "results": [{"id": "1"}, {"id": "2"}] if offset == 0 else [{"id": "3"}]})._fetch_query_pages("12345", "Lidl", {})
    assert len(result) == 2 and "Gesamtzahl" in result.note


@pytest.mark.parametrize("total", [True, -1, "unknown", 0])
def test_invalid_or_contradictory_total_is_a_failure_before_admission(total):
    with pytest.raises(ToolError):
        mk(lambda _q, _o: {"totalResults": total, "results": [{"id": "1"}]})._fetch_query_pages("12345", "Lidl", {})
