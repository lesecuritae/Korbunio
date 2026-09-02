import json
from urllib.parse import parse_qs, urlparse

from supermarkt.http import HttpClient
from supermarkt.region import AldiRegionResolver


class FakeHttp(HttpClient):
    def __init__(self):
        super().__init__(5)
        self.calls = 0

    def get_bytes(self, url, headers=None):
        self.calls += 1
        if "postalcode=" in url:
            return json.dumps([{"lat": "51.05", "lon": "13.74"}]).encode()
        return json.dumps(
            [
                {
                    "lat": "51.051",
                    "lon": "13.741",
                    "display_name": "ALDI Nord",
                    "address": {"postcode": "01067"},
                    "namedetails": {"name": "ALDI Nord"},
                    "extratags": {"website": "https://www.aldi-nord.de/"},
                }
            ]
        ).encode()


def test_region_resolver_prefers_versioned_official_evidence():
    http = FakeHttp()
    resolver = AldiRegionResolver(http)
    resolver.http = http
    assert resolver.detect("01067") == "nord"
    assert resolver.last_provider.startswith("Offizielle ALDI")
    assert http.calls == 0


def test_region_resolver_uses_bounded_fallback_and_cache():
    http = FakeHttp()
    resolver = AldiRegionResolver(http)
    resolver.http = http
    assert resolver.detect("01100") == "nord"
    assert http.calls == 2
    assert resolver.detect("01100") == "nord"
    assert http.calls == 2


def test_markets_preserve_provider_address_and_coordinates():
    http = FakeHttp()
    resolver = AldiRegionResolver(http)
    resolver.http = http
    markets = resolver.markets("01067")
    assert markets[0]["name"] == "ALDI Nord"
    assert markets[0]["postal_code"] == "01067"
    assert markets[0]["latitude"] == 51.051
    assert markets[0]["longitude"] == 13.741
    assert markets[0]["url"] == "https://www.aldi-nord.de/"


def test_retailer_markets_resolve_every_requested_catalog_retailer():
    class RetailerHttp(FakeHttp):
        def get_bytes(self, url, headers=None):
            self.calls += 1
            query = parse_qs(urlparse(url).query)
            if "postalcode" in query:
                return json.dumps([{"lat": "51.32", "lon": "12.29"}]).encode()
            name = "Lidl" if query.get("q", [""])[0].casefold() == "lidl" else "dm-drogerie markt"
            return json.dumps([{"osm_id": name, "lat": "51.321", "lon": "12.291",
                "display_name": f"{name}, Teststraße 1, 04209 Leipzig",
                "address": {"postcode": "04209", "shop": name}, "namedetails": {"name": name},
                "extratags": {"website": "https://example.test/"}}]).encode()

    resolver = AldiRegionResolver(RetailerHttp())
    resolver.http = RetailerHttp()
    markets = resolver.retailer_markets("04209", ("Lidl", "dm"))
    assert {market["retailer"] for market in markets} == {"Lidl", "dm"}
    assert all(market["postal_code"] == "04209" for market in markets)


def test_retailer_markets_classify_plain_aldi_name_from_provider_metadata():
    class AldiHttp(FakeHttp):
        def get_bytes(self, url, headers=None):
            self.calls += 1
            if "postalcode=" in url:
                return json.dumps([{"lat": "51.32", "lon": "12.29"}]).encode()
            return json.dumps([{"osm_id": "allee", "lat": "51.3195", "lon": "12.2918",
                "display_name": "Aldi, Ludwigsburger Straße 9, 04209 Leipzig",
                "address": {"postcode": "04209", "shop": "Aldi"}, "namedetails": {"name": "Aldi"},
                "extratags": {"website": "https://www.aldi-nord.de/filiale/allee"}}]).encode()

    resolver = AldiRegionResolver(AldiHttp())
    resolver.http = AldiHttp()
    markets = resolver.retailer_markets("04209", ("ALDI Nord", "ALDI Süd"))
    assert [(market["market_id"], market["retailer"]) for market in markets] == [("allee", "ALDI Nord")]


def test_unknown_52_postcode_is_not_classified_by_prefix():
    http = FakeHttp()
    resolver = AldiRegionResolver(http)
    resolver.http = http
    assert "52000" not in resolver.OFFICIAL_EVIDENCE
    assert resolver.detect("52000") == "nord"
    assert resolver.last_provider == "Nominatim"
    assert http.calls == 2
    assert resolver.detect("52000") == "nord"
    assert http.calls == 2


def test_leverkusen_is_aldi_sued_without_geocoding():
    """ALDI Süd betreibt 14 Filialen in Leverkusen, ALDI Nord keine.

    Ohne diesen Nachweis lieferte die Nominatim-Umkreissuche "nord", weil im
    gesamten Suchfenster nur zwei Filialen ein verwertbares Nord/Süd-Merkmal
    tragen und beide zu ALDI Nord gehören.
    """
    http = FakeHttp()
    resolver = AldiRegionResolver(http)
    resolver.http = http
    for code in ("51371", "51373", "51375", "51377", "51379", "51381"):
        assert resolver.detect(code) == "sued", code
        assert resolver.last_provider.startswith("Offizielle ALDI")
        assert resolver.last_confidence == "hoch"
    assert http.calls == 0
