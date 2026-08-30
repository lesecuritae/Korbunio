from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

from .service import SourceLoader

REQUIRED_MINIMUMS = {
    "REWE": 10,
    "Lidl": 50,
    "PENNY": 50,
    "Netto Marken-Discount": 50,
    "Kaufland": 50,
    "EDEKA": 10,
}
OPTIONAL_RETAILERS = ("Marktkauf", "Globus", "Combi", "famila Nordwest")


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
    }


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
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    if len(args.postal_code) != 5 or not args.postal_code.isdigit():
        parser.error("postal_code muss aus genau fünf Ziffern bestehen")

    try:
        result = SourceLoader().load(args.postal_code, args.aldi_region)
        report = evaluate(result)
    except Exception as exc:
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
