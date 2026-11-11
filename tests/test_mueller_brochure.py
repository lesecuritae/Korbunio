"""Dated Müller brochure authority; no general assortment or false regional claim."""
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from supermarkt.models import ToolError
from supermarkt.sources.brochures import MuellerBrochureSource
from supermarkt.sources.kaufda import KaufdaRetailerSource
from test_mueller_kaufda import _loader

FIXTURE = Path(__file__).parent / "fixtures/offer_coverage/kaufda_mueller_brochure.json"
DAY = date(2026, 11, 10)


class Http:
    def __init__(self, publisher="Müller"):
        self.calls = []
        self.publisher = publisher

    def get_bytes(self, url, headers=None):
        self.calls.append(url)
        if "Geschaefte" in url:
            data = {"props": {"pageProps": {"pageInformation": {"brochures": {"viewer": [
                {"id": "2501311481", "publisher": {"name": self.publisher, "type": "RETAILER"}},
                {"id": "2501298321", "publisher": {"name": "Nutella", "type": "MANUFACTURER"}},
            ]}}}}}
            return f'<script id="__NEXT_DATA__">{json.dumps(data)}</script>'.encode()
        assert "2501311481" in url
        assert "lat=51.34" in url and "lng=12.37" in url
        return FIXTURE.read_bytes()


def source(http):
    return MuellerBrochureSource(http, SimpleNamespace(coordinates=lambda _p: (51.34, 12.37)))


def test_dated_brochure_preserves_seven_published_prices_quantities_and_actual_app_price():
    http = Http()
    offers = source(http).load_week("04109", DAY)
    assert len(http.calls) == 2 and all("aktionen" not in u for u in http.calls)
    assert {o.name: (o.price, o.pack_signature) for o in offers} == {
        "MUGLER ALIEN": (69.95, "60ml"), "Armani Sì": (45.95, "30ml"),
        "Lancôme Idôle": (38.95, "25ml"), "BOSS ALIVE Eau de Parfum": (32.45, "30ml"),
        "ISSEY MIYAKE L'EAU D'ISSEY POUR HOMME": (42.95, "40ml"),
        "BURBERRY HERO": (42.95, "50ml"), "BOSS BOTTLED BEYOND": (54.95, "50ml"),
    }
    assert all(o.valid_from == "2026-11-02" and o.valid_until == "2026-11-14" for o in offers)
    assert all("regionale Abdeckung nicht bestätigt" in o.coverage_note for o in offers)
    issey = next(o for o in offers if "ISSEY" in o.name)
    assert [(b.program_id, b.value) for b in issey.benefits] == [("mueller_blueten", 37.95)]


def test_brochure_never_substitutes_another_publisher_default_coordinates_or_general_highlights():
    with pytest.raises(ToolError, match="eigener Händlerprospekt"):
        source(Http(publisher="dm")).load_week("04109", DAY)
    http = Http()
    with pytest.raises(ToolError, match="Ortskoordinaten"):
        MuellerBrochureSource(http, SimpleNamespace(coordinates=lambda _p: None)).load_week("04109", DAY)
    assert not http.calls
    with pytest.raises(ToolError, match="Zielwoche"):
        source(Http()).load_week("04109", date(2026, 11, 16))


def test_main_loader_labels_brochure_honestly_and_keeps_scope_warning(monkeypatch):
    monkeypatch.setattr("supermarkt.common.today_berlin", lambda: DAY)
    adapter = source(Http())
    loader = _loader(KaufdaRetailerSource(None, "Müller", "Müller", "Mueller"))
    loader.official_mueller = adapter
    result = loader.load("04109", "auto", retailers=("Müller",))
    assert len(result["offers"]) == 7
    assert result["source_states"]["Müller"] == "KaufDA-Händlerprospekt"
    assert any("Filialgeltung" in w for w in result["store_warnings"])
    assert not result["request_errors"] and not result["incomplete_retailers"]
