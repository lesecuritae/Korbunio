from supermarkt.diagnostics import evaluate


def _offers(retailer, count):
    return [{"retailer": retailer} for _ in range(count)]


def test_diagnostics_accepts_complete_required_source_mix():
    offers = []
    for retailer, count in {
        "REWE": 20,
        "Lidl": 100,
        "PENNY": 80,
        "Netto Marken-Discount": 90,
        "Kaufland": 120,
        "EDEKA": 30,
        "ALDI Nord": 70,
    }.items():
        offers.extend(_offers(retailer, count))
    report = evaluate({
        "postal_code": "12345",
        "resolved_aldi_region": "nord",
        "offers": offers,
        "source_states": {},
        "request_errors": [],
        "store_warnings": [],
    })
    assert report["ok"] is True
    assert report["failures"] == []


def test_diagnostics_rejects_partial_lidl_catalogue():
    offers = []
    for retailer, count in {
        "REWE": 20,
        "Lidl": 14,
        "PENNY": 80,
        "Netto Marken-Discount": 90,
        "Kaufland": 120,
        "EDEKA": 30,
        "ALDI Nord": 70,
    }.items():
        offers.extend(_offers(retailer, count))
    report = evaluate({
        "postal_code": "12345",
        "resolved_aldi_region": "nord",
        "offers": offers,
        "source_states": {},
        "request_errors": [],
        "store_warnings": [],
    })
    assert report["ok"] is False
    assert any(item.startswith("Lidl: 14 Treffer") for item in report["failures"])
