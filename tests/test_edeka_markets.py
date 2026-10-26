import pytest

from supermarkt.models import ToolError
from supermarkt.sources.edeka import OfficialEdekaSource, OfficialMarktkaufSource


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class _Session:
    """Answers the market search only; offers are stubbed per market."""

    def __init__(self, markets, status=200):
        self.markets = markets
        self.status = status
        self.searches = []

    def get(self, url, params=None, timeout=None):
        self.searches.append(params)
        return _Response({"markets": self.markets}, self.status)


def _market(market_id, postal, name="EDEKA Test"):
    return {"id": market_id, "name": f"{name} {market_id}", "contact": {"address": {"city": {"zipCode": postal}}}}


def _source(monkeypatch, markets, offers_by_market):
    source = OfficialEdekaSource()
    session = _Session(markets)
    monkeypatch.setattr(source, "_session", lambda: session)
    calls = []

    def fake_load_offers(_session, *, retailer, market_id, market_url, reference_date):
        calls.append(market_id)
        result = offers_by_market[market_id]
        if isinstance(result, Exception):
            raise result
        return result, len(result), 0

    monkeypatch.setattr(source, "_load_offers", fake_load_offers)
    return source, calls


def test_first_market_with_priced_offers_wins(monkeypatch):
    source, calls = _source(
        monkeypatch,
        [_market("1", "26188"), _market("2", "26122")],
        {"1": ["angebot"], "2": ["anderes"]},
    )
    assert source.load("26188") == ["angebot"]
    assert calls == ["1"]
    assert source.last_market_id == "1"


def test_empty_market_falls_through_to_the_next_nearby_one(monkeypatch):
    source, calls = _source(
        monkeypatch,
        [_market("10", "04109"), _market("20", "04103")],
        {"10": [], "20": ["angebot"]},
    )
    assert source.load("04109") == ["angebot"]
    assert calls == ["10", "20"]
    assert source.last_market_id == "20"


def test_a_failing_market_does_not_hide_the_others(monkeypatch):
    source, calls = _source(
        monkeypatch,
        [_market("10", "04109"), _market("20", "04103")],
        {"10": ToolError("EDEKA Angebote HTTP 500"), "20": ["angebot"]},
    )
    assert source.load("04109") == ["angebot"]
    assert calls == ["10", "20"]


def test_exact_postal_code_is_tried_before_nearer_listed_markets(monkeypatch):
    source, calls = _source(
        monkeypatch,
        [_market("1", "26122"), _market("2", "26188")],
        {"1": ["nah"], "2": ["exakt"]},
    )
    assert source.load("26188") == ["exakt"]
    assert calls == ["2"]


def test_gives_up_after_the_candidate_limit_with_a_clear_message(monkeypatch):
    markets = [_market(str(i), "04109") for i in range(1, 12)]
    source, calls = _source(monkeypatch, markets, {str(i): [] for i in range(1, 12)})
    with pytest.raises(ToolError) as error:
        source.load("04109")
    assert len(calls) == OfficialEdekaSource.MAX_MARKET_CANDIDATES
    assert "keiner lieferte Angebote mit Preisen" in str(error.value)
    assert "04109" in str(error.value)


def test_no_market_at_all_keeps_the_old_message(monkeypatch):
    source, _ = _source(monkeypatch, [], {})
    with pytest.raises(ToolError, match="keinen nutzbaren Markt"):
        source.load("04109")


def test_market_search_http_error_is_reported(monkeypatch):
    source = OfficialEdekaSource()
    monkeypatch.setattr(source, "_session", lambda: _Session([], status=403))
    with pytest.raises(ToolError, match="Marktsuche HTTP 403"):
        source.load("04109")


@pytest.mark.parametrize("source_type", [OfficialEdekaSource, OfficialMarktkaufSource])
def test_market_beyond_api_default_page_can_be_selected(monkeypatch, source_type):
    markets = [_market(str(i), "99999") for i in range(10)]
    markets.append(_market("target", "12345", "MARKTKAUF Test"))

    class PagedSession:
        def get(self, _url, params=None, timeout=None):
            # The real service ignores limit and defaults to ten unless size is set.
            return _Response({"markets": markets[:int(params.get("size", 10))]})

    source = source_type()
    monkeypatch.setattr(source, "_session", PagedSession)
    monkeypatch.setattr(source, "_load_offers", lambda _session, **kw: (["offer"], 1, 0) if kw["market_id"] == "target" else ([], 0, 0))
    assert source.load("12345") == ["offer"]
    assert source.last_market_id == "target"
