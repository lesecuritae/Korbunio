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


def test_reference_audit_detects_missing_article_in_otherwise_filled_catalogue():
    from supermarkt.diagnostics import evaluate_reference_coverage
    from supermarkt.models import RETAILER_SPECS, offer_to_dict
    from test_offer_coverage import kania
    offer = kania()
    reference = {"retailer": "Lidl", "name": offer.name, "price": 3.99, "pack": "400g",
                 "valid_from": "2026-11-09", "valid_until": "2026-11-14", "postal_code": "04109",
                 "source_url": "https://www.lidl.de/c/online-prospekte/s10005610/", "verified": True}
    snapshot = {"postal_code": "04109", "offers": [dict(offer_to_dict(offer), name=f"Fixture article {i}") for i in range(150)]}
    for raw_found, expected in [(False, "UPSTREAM_MISSING"), (True, "PARSER_LOSS"), (None, "NOT_VERIFIED")]:
        report = evaluate_reference_coverage(snapshot, [{**reference, "raw_found": raw_found}])
        assert len(report["retailers"]) == len(RETAILER_SPECS)
        lidl = next(row for row in report["retailers"] if row["retailer"] == "Lidl")
        assert lidl["catalogue_count"] == 150 and lidl["status"] == expected
    snapshot["offers"].append(offer_to_dict(offer))
    report = evaluate_reference_coverage(snapshot, [reference])
    assert next(row for row in report["retailers"] if row["retailer"] == "Lidl")["status"] == "OK"
    # A different postal area's evidence is not regional proof.
    reference["postal_code"] = "50939"
    report = evaluate_reference_coverage(snapshot, [reference])
    assert next(row for row in report["retailers"] if row["retailer"] == "Lidl")["status"] == "NOT_VERIFIED"


def test_reference_field_difference_does_not_invent_a_parser_root_cause():
    from supermarkt.diagnostics import evaluate_reference_coverage
    from supermarkt.models import offer_to_dict
    from test_offer_coverage import kania
    offer = kania()
    reference = {"retailer": "Lidl", "name": offer.name, "price": 2.99, "pack": "400g",
        "postal_code": "04109", "source_url": "https://www.lidl.de/", "verified": True}
    report = evaluate_reference_coverage({"postal_code": "04109", "offers": [offer_to_dict(offer)]}, [reference])
    assert next(row for row in report["retailers"] if row["retailer"] == "Lidl")["status"] == "NOT_VERIFIED"
