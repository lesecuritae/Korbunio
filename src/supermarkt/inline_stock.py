"""Attach bounded live stock to returned offers, never to the price ranking."""
from __future__ import annotations

import re

from .availability import StockRequest, check_availability
from .models import ToolError


def enrich(rows: list[dict], postal: str, check=check_availability) -> list[dict]:
    result = [dict(row) for row in rows]
    for retailer, length in (("dm", 7), ("Rossmann", 6)):
        selected = [row for row in result if row.get("retailer") == retailer]
        if not selected:
            continue
        references = list(dict.fromkeys(str(r.get("article_number", "")) for r in selected
                                        if re.fullmatch(r"[0-9]{" + str(length) + "}", str(r.get("article_number", "")))))[:5]
        for row in selected:
            row["stock"] = {"retailer": retailer, "status": "not_checked",
                            "reason": "Artikelzuordnung nicht belegt" if row.get("article_number") not in references else "Abfrage ausstehend"}
        if not references:
            continue
        try:
            reply = check(StockRequest(retailer=retailer, postal_code=postal, dans=references))
        except ToolError as exc:
            reply = {"status": "unavailable", "results": [], "error": str(exc)}
        products = {str(p.get("dan")): p for p in reply.get("results", []) if isinstance(p, dict)}
        for row in selected:
            dan = row.get("article_number")
            if dan not in references:
                if re.fullmatch(r"[0-9]{" + str(length) + "}", str(dan)):
                    row["stock"]["reason"] = "Abfragelimit dieser Seite; nicht als ausverkauft werten"
                continue
            item = products.get(dan)
            row["stock"] = ({**item, "retailer": retailer} if item else
                            {"retailer": retailer, "dan": dan, "status": reply.get("status", "unavailable"),
                             "error": reply.get("error", "Keine bestätigten Filialdaten")})
    for row in result:
        if row.get("stock"):
            row["stock_summary"] = summary(row["stock"])
    return result


def summary(stock: dict) -> str:
    """Small human-readable counterpart to the full structured result."""
    if stock.get("status") != "ok":
        return "Bestand unbekannt: " + str(stock.get("error") or stock.get("reason") or stock.get("status"))
    parts = []
    for store in stock.get("stores", [])[:3]:
        state = store.get("availability_status")
        if state == "NUR_ONLINE":
            value = "nur online, nicht im Filialsortiment"
        elif store.get("in_stock") is False:
            value = "nicht verfügbar"
        elif store.get("in_stock") is True:
            count = store.get("stock_minimum")
            value = "verfügbar (Menge unbekannt)" if count is None else (
                ("" if store.get("stock_is_exact") else "mindestens ") + str(count) + " Stück")
        else:
            value = "Bestand unbekannt"
        parts.append(f"{store.get('postal_code', '')} {store.get('city', '')}, {store.get('street', '')}: {value}")
    if not parts:
        parts.append("Keine bestätigten Filialdaten; nicht als ausverkauft werten")
    return "Bestand (" + str(stock.get("checked_at", "Zeit unbekannt")) + "): " + "; ".join(parts)
