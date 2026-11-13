from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any
from pathlib import Path

from .common import filter_offers, normalize_pack, clean_text
from .models import RETAILER_SPECS, offer_from_dict

from .service import SourceLoader

REQUIRED_MINIMUMS = {
    "REWE": 10,
    "Lidl": 50,
    "PENNY": 50,
    "Netto Marken-Discount": 50,
    "Kaufland": 50,
    "EDEKA": 10,
}
OPTIONAL_RETAILERS = ("Marktkauf", "Globus", "famila Nordwest", "aktiv & irma", "Combi")


def evaluate(result: dict[str, Any]) -> dict[str, Any]:
    counts = Counter(
        item.get("retailer")
        for item in result.get("offers", [])
        if isinstance(item, dict) and item.get("retailer")
    )
    resolved = str(result.get("resolved_aldi_region") or "")
    aldi_name = "ALDI Nord" if resolved == "nord" else "ALDI Süd" if resolved == "sued" else ""

    failures: list[str] = []
    for retailer, minimum in REQUIRED_MINIMUMS.items():
        count = int(counts.get(retailer, 0))
        if count < minimum:
            failures.append(f"{retailer}: {count} Treffer, erwartet mindestens {minimum}")

    if not aldi_name:
        failures.append("ALDI: Region konnte nicht bestimmt werden")
    elif int(counts.get(aldi_name, 0)) < 20:
        failures.append(f"{aldi_name}: {counts.get(aldi_name, 0)} Treffer, erwartet mindestens 20")

    optional = {
        name: int(counts.get(name, 0))
        for name in OPTIONAL_RETAILERS
    }
    return {
        "postal_code": result.get("postal_code"),
        "resolved_aldi_region": resolved,
        "counts": dict(sorted((str(k), int(v)) for k, v in counts.items())),
        "source_states": result.get("source_states") or {},
        "request_errors": result.get("request_errors") or [],
        "store_warnings": result.get("store_warnings") or [],
        "optional_counts": optional,
        "failures": failures,
        "ok": not failures,
        "coverage_status": "NOT_VERIFIED",  # Count thresholds are reachability checks only.
    }


def evaluate_reference_coverage(result: dict[str, Any], references: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare independently verified published articles, including filled catalogues.

    `raw_found` is separate upstream evidence supplied by the audit, never
    inferred from a successful HTTP request or from the number of other offers.
    `verified` attests only the stated source/region/time sample, not completeness.
    """
    offers = [offer_from_dict(item) for item in result.get("offers", []) if isinstance(item, dict)]
    rows = []
    for spec in RETAILER_SPECS:
        selected = [ref for ref in references if ref.get("retailer") == spec.name]
        articles = []
        for ref in selected:
            status, reason = "NOT_VERIFIED", "Independent source/region evidence missing"
            matches = []
            if ref.get("verified") is True and str(ref.get("source_url", "")).startswith("https://") and ref.get("postal_code") == result.get("postal_code"):
                matches = [offer for offer in offers if offer.retailer == spec.name
                    and clean_text(offer.name).casefold() == clean_text(ref.get("name")).casefold()]
                exact = [offer for offer in matches if offer.price == ref.get("price")
                    and normalize_pack(offer.pack_signature) == normalize_pack(ref.get("pack", ""))
                    and offer.valid_from == ref.get("valid_from") and offer.valid_until == ref.get("valid_until")]
                if exact:
                    query = ref.get("query") or ref["name"]
                    status = "OK" if filter_offers(exact, query) else "SEARCH_MISMATCH"
                    reason = "Published reference sample matched" if status == "OK" else "Stored article not found by reference query"
                elif matches:
                    status, reason = "NOT_VERIFIED", "Name present, but price/pack/validity differs; raw evidence needed to classify the cause"
                elif spec.name in result.get("unavailable_retailers", []):
                    status, reason = "DATE_REGION_FILTER", "Reference article removed by market/region selection"
                elif ref.get("raw_found") is True:
                    status, reason = "PARSER_LOSS", "Reference present upstream but absent after import"
                elif ref.get("raw_found") is False:
                    status, reason = "UPSTREAM_MISSING", "Published reference absent from inspected upstream response"
                elif result.get("source_states", {}).get(spec.name) == "Abruffehler":
                    status, reason = "SOURCE_UNAVAILABLE", "Source request failed"
            articles.append({"name": ref.get("name"), "source_url": ref.get("source_url"),
                "status": status, "reason": reason, "stored_name_matches": len(matches)})
        statuses = {article["status"] for article in articles}
        rows.append({"retailer": spec.name, "catalogue_count": sum(offer.retailer == spec.name for offer in offers),
            "reference_count": len(articles), "status": "OK" if statuses == {"OK"} else "NOT_VERIFIED" if not statuses else ",".join(sorted(statuses)),
            "articles": articles})
    return {"postal_code": result.get("postal_code"), "scope": "reference samples only", "retailers": rows}


def _print_report(report: dict[str, Any]) -> None:
    print(f"PLZ: {report['postal_code']}")
    print(f"ALDI-Region: {report['resolved_aldi_region'] or 'unbekannt'}")
    print("\nHändler:")
    states = report["source_states"]
    for retailer, count in report["counts"].items():
        print(f"  {retailer:12} {count:4}  {states.get(retailer, 'unbekannt')}")

    missing_states = [
        name for name, state in states.items()
        if name not in report["counts"] and state not in {"keine Treffer", "kein Markt"}
    ]
    for retailer in missing_states:
        print(f"  {retailer:12} {0:4}  {states.get(retailer)}")

    if report["request_errors"]:
        print("\nQuellenfehler:")
        for item in report["request_errors"]:
            print(f"  - {item}")
    if report["store_warnings"]:
        print("\nHinweise:")
        for item in report["store_warnings"]:
            print(f"  - {item}")

    print("\nPflichtquellen:", "OK" if report["ok"] else "FEHLER")
    for failure in report["failures"]:
        print(f"  - {failure}")
    print(
        "Optionale Händler: "
        + ", ".join(f"{name}={count}" for name, count in report["optional_counts"].items())
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live-Diagnose der Supermarktquellen für eine Postleitzahl")
    parser.add_argument("postal_code", help="fünfstellige deutsche Postleitzahl")
    parser.add_argument("--aldi-region", choices=("auto", "nord", "sued"), default="auto")
    parser.add_argument("--references", type=Path, help="JSON array of independently verified offer references")
    parser.add_argument("--snapshot", type=Path, help="Evaluate an existing JSON snapshot without live requests")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    if len(args.postal_code) != 5 or not args.postal_code.isdigit():
        parser.error("postal_code muss aus genau fünf Ziffern bestehen")

    try:
        result = json.loads(args.snapshot.read_text()) if args.snapshot else SourceLoader().load(args.postal_code, args.aldi_region)
        if result.get("postal_code") != args.postal_code:
            raise ValueError("Snapshot postal code does not match request")
        report = evaluate(result)
        if args.references:
            report["reference_coverage"] = evaluate_reference_coverage(result, json.loads(args.references.read_text()))
    except Exception as exc:  # CLI entrypoint: turn any failure into a clean exit instead of a traceback
        if args.as_json:
            print(json.dumps({"ok": False, "fatal_error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        else:
            print(f"FATAL: {type(exc).__name__}: {exc}")
        return 2

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_report(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
