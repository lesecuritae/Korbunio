from urllib.parse import parse_qs, urlsplit

from supermarkt.sources.marktguru import MarktguruClient


class PagedRetailerHttp:
    def __init__(self):
        self.calls = []

    def get_json(self, url, headers):
        self.calls.append(url)
        query = parse_qs(urlsplit(url).query, keep_blank_values=True)
        assert query["q"] == ["Lidl"]
        assert query["zipCode"] == ["12345"]
        offset = int(query["offset"][0])
        if offset == 0:
            return {"results": [{"id": 1}, {"id": 2}]}
        if offset == 2:
            return {"results": [{"id": 3}]}
        return {"results": []}


def test_marktguru_retailer_query_uses_name_and_paginates():
    http = PagedRetailerHttp()
    client = MarktguruClient(http, page_size=2, max_workers=1)
    offers = client._fetch_query_pages("12345", "Lidl", {})
    assert [item["id"] for item in offers] == [1, 2, 3]
    assert len(http.calls) == 2


class RepeatingHttp:
    def __init__(self):
        self.calls = 0

    def get_json(self, url, headers):
        self.calls += 1
        return {"results": [{"id": 1}, {"id": 2}]}


def test_marktguru_retailer_pagination_stops_on_repeated_page():
    http = RepeatingHttp()
    client = MarktguruClient(http, page_size=2, max_workers=1)
    offers = client._fetch_query_pages("12345", "Netto", {})
    assert [item["id"] for item in offers] == [1, 2]
    assert http.calls == 2


def test_marktguru_primary_path_never_uses_empty_retailer_query(monkeypatch):
    client = MarktguruClient(object(), page_size=500, max_workers=1)
    monkeypatch.setattr(client, "_headers", lambda: {})
    seen = []

    def fake_pages(postal_code, query_text, headers):
        seen.append((postal_code, query_text))
        return []

    monkeypatch.setattr(client, "_fetch_query_pages", fake_pages)
    client.load_retailer_queries("12345", ["Lidl", "PENNY", "Netto"])
    assert seen == [("12345", "Lidl"), ("12345", "PENNY"), ("12345", "Netto")]
    assert all(query for _, query in seen)


def test_marktguru_broad_terms_use_paginated_fetch(monkeypatch):
    client = MarktguruClient(object(), page_size=2, max_workers=1)
    monkeypatch.setattr(client, "_headers", lambda: {})
    monkeypatch.setattr("supermarkt.sources.marktguru.SEARCH_TERMS", ("Kaffee", "Milch"))
    seen = []

    def fake_pages(postal_code, query_text, headers):
        seen.append((postal_code, query_text))
        return [{"id": f"{query_text}-1"}, {"id": f"{query_text}-2"}]

    monkeypatch.setattr(client, "_fetch_query_pages", fake_pages)
    offers, errors = client._load_once("12345")
    assert errors == []
    assert {item["id"] for item in offers} == {"Kaffee-1", "Kaffee-2", "Milch-1", "Milch-2"}
    assert set(seen) == {("12345", "Kaffee"), ("12345", "Milch")}
