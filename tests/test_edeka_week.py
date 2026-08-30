from datetime import date

from supermarkt.sources.edeka import OfficialEdekaSource


class Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class Session:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *args, **kwargs):
        return Response(self.payload)


def test_edeka_drops_expired_week_before_mapping(monkeypatch):
    payload = {
        "gueltig_von": "2026-08-03",
        "docs": [
            {"angebotid": "old", "titel": "Alt", "preis": 1.0, "gueltig_bis": "2026-08-08"},
            {
                "angebotid": "new",
                "titel": "Neu",
                "preis": 2.0,
                "gueltig_von": "2026-08-10",
                "gueltig_bis": "2026-08-15",
            },
        ],
    }

    def target_week(start, end):
        target = date(2026, 8, 10)
        return (start is None or start <= target) and (end is None or target <= end)

    monkeypatch.setattr("supermarkt.sources.edeka.date_is_current", target_week)
    source = OfficialEdekaSource()
    offers, raw_count, _ = source._load_offers(
        Session(payload), retailer="EDEKA", market_id="1", market_url="https://example.invalid"
    )
    assert raw_count == 2
    assert [offer.name for offer in offers] == ["Neu"]
