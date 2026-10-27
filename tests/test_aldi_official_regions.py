"""Server geography regressions: synthetic official catalogues, no live requests."""
import json

import pytest
from unittest.mock import patch

from supermarkt.http import HttpClient
from supermarkt.models import LoadResult, Offer, ToolError
from supermarkt.region import AldiRegionResolver
from supermarkt.service import SourceLoader


def store(region, code, lat, lon):
    return {"name": "ALDI " + ("SÜD" if region == "sued" else "Nord"),
            "country": "DE", "zip": code, "lat": lat, "lng": lon}


class OfficialHttp(HttpClient):
    def __init__(self, north=None, south=None, fail=()):
        super().__init__(3)
        self.north = north if north is not None else [store("nord", "51503", 50.95, 7.2)]
        self.south = south if south is not None else [store("sued", "50939", 50.917714, 6.936162)]
        self.fail = fail
        self.calls = []

    def get_bytes(self, url, headers=None):
        self.calls.append(url)
        region = "sued" if "uberall.com" in url else "nord"
        if "nominatim" in url:
            if "postalcode=" in url:
                return json.dumps([{"lat": "50.9080605", "lon": "6.9247881",
                                    "address": {"postcode": "50939", "country_code": "de"}}]).encode()
            # Sparse OSM metadata: the only tagged chain is far-away Nord.
            return json.dumps([{"lat": "50.95", "lon": "7.2", "display_name": "ALDI Nord",
                                "address": {"postcode": "51503"}, "namedetails": {"name": "ALDI Nord"},
                                "extratags": {"website": "https://www.aldi-nord.de/"}}]).encode()
        if region in self.fail:
            raise ToolError("HTTP 503 bei offiziellem Filialdienst")
        payload = {"status": "SUCCESS", "response": {"locations": self.south if region == "sued" else self.north}}
        if region == "sued":
            return json.dumps(payload).encode()
        page = {"props": {"pageProps": {"apiData": [["STORE_UBERALL_LOCATIONS_GET", {"res": payload}]]}}}
        return ('<script id="__NEXT_DATA__">' + json.dumps(page) + '</script>').encode()


def resolver(http):
    value = AldiRegionResolver(http)
    value.http = http
    return value


def test_cologne_uses_official_south_instead_of_distant_tagged_north():
    http = OfficialHttp()
    value = resolver(http)
    assert value.detect("50939") == "sued"
    assert value.last_regions == ("sued",)
    assert value.last_absent_regions == ("nord",)
    assert not any("nominatim" in url for url in http.calls)
    value.detect("50939")
    assert len(http.calls) == 2  # Bounded catalogue cache, not a PLZ exception.


def test_official_border_keeps_both_chains():
    value = resolver(OfficialHttp(north=[store("nord", "50939", 50.92, 6.94)]))
    assert value.detect("50939") == "auto"
    assert set(value.last_regions) == {"nord", "sued"}
    assert value.last_absent_regions == ()


def test_failed_north_does_not_block_south_or_prove_north_absent():
    http = OfficialHttp(fail=("nord",))
    value = resolver(http)
    assert value.detect("50939") == "sued"
    assert value.last_absent_regions == ()
    assert "503" in value.last_error
    http.fail = ()
    assert value.detect("50939") == "sued"
    assert value.last_absent_regions == ("nord",)
    assert len(http.calls) == 3  # Failed responses are not cached as absence.


def test_catalogue_expires_and_changed_store_list_is_reloaded():
    http = OfficialHttp()
    value = resolver(http)
    with patch("supermarkt.region.time.monotonic", return_value=100):
        assert value.detect("50939") == "sued"
    http.north = [store("nord", "50939", 50.92, 6.94)]
    with patch("supermarkt.region.time.monotonic", return_value=3701):
        assert value.detect("50939") == "auto"
    assert set(value.last_regions) == {"nord", "sued"}
    assert len(http.calls) == 4


@pytest.mark.parametrize("address", [{}, {"postcode": "12345", "country_code": "de"},
                                      {"postcode": "50939", "country_code": "at"}])
def test_unconfirmed_geocode_cannot_establish_absence(address):
    http = OfficialHttp(south=[store("sued", "50937", 50.92, 6.94)])
    original = http.get_bytes
    def get(url, headers=None):
        if "postalcode=" in url:
            return json.dumps([{"lat": "50.91", "lon": "6.93", "address": address}]).encode()
        return original(url, headers)
    http.get_bytes = get
    value = resolver(http)
    assert value.detect("50939") == "auto"
    assert value.last_absent_regions == ()
    assert value.last_regions == ()
    assert "PLZ" in value.last_error


def test_empty_south_catalogue_is_unknown_rather_than_absent():
    value = resolver(OfficialHttp(south=[]))
    assert value.detect("50939") == "auto"
    assert value.last_regions == ()
    assert value.last_absent_regions == ("nord",)
    assert value.last_error


def test_distant_nominatim_store_never_selects_a_chain():
    value = resolver(OfficialHttp(fail=("nord", "sued")))
    assert value.detect("50939") == "auto"
    assert value.last_regions == ()
    assert value.last_absent_regions == ()
    assert value.last_error


@pytest.mark.parametrize("lat,lon", [(float("nan"), 6.9), (50.9, float("inf")), (95, 6.9)])
def test_invalid_official_coordinates_cannot_prove_market_absence(lat, lon):
    value = resolver(OfficialHttp(south=[store("sued", "50939", lat, lon)]))
    assert value.detect("50939") == "auto"
    assert "sued" not in value.last_absent_regions


def test_loader_fetches_south_for_reported_docker_postcode():
    loader = SourceLoader.__new__(SourceLoader)
    loader.aldi_region = resolver(OfficialHttp())
    calls = []
    class Aldi:
        def load(self, retailer):
            calls.append(retailer)
            return LoadResult([Offer("fixture:1", retailer, "Test", "Testangebot", "", "", 1,
                                     None, "", "", "Aktuell", "fixture", "https://example.invalid")], [])
    loader.official_aldi = Aldi()
    result = loader.load("50939", "auto", retailers=("ALDI Süd",))
    assert calls == ["ALDI Süd"]
    assert len(result["offers"]) == 1
    assert "ALDI Süd" not in result["unavailable_retailers"]


def test_unresolved_selected_chain_reports_diagnostic_alongside_other_offers(caplog):
    loader = SourceLoader.__new__(SourceLoader)
    loader.aldi_region = resolver(OfficialHttp(south=[]))
    class Rewe:
        last_market_url = ""
        def load(self, _code):
            return [Offer("fixture:2", "REWE", "Test", "Testangebot", "", "", 1,
                          None, "", "", "Aktuell", "fixture", "https://example.invalid")]
    loader.official_rewe = Rewe()
    result = loader.load("50939", "auto", retailers=("ALDI Süd", "REWE"))
    assert "ALDI Süd" not in result["unavailable_retailers"]
    assert any("ALDI Süd" in error for error in result["request_errors"])
    assert "ALDI" in caplog.text
