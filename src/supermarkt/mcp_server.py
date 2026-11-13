"""MCP-Server: Korbuino-Angebote für LLMs abfragbar machen (nur Lesen).

Ein KI-Programm fragt zum Beispiel „Wo ist Kaffee im Angebot?“ und bekommt Händler, den
Preis ohne Bonusprogramm und, wenn es einen öffentlich ausgewiesenen gibt, den Preis mit
Bonusprogramm, dazu Bilder. Der Server bindet ihn unter ``/mcp`` ein (Streamable HTTP);
``python -m supermarkt.mcp_server`` startet ihn für lokale Programme über stdio.

Die Wartezeit ist der schwierige Teil: Für eine neue Postleitzahl lädt der Server alle
Händler, das dauert meist 10 bis 20 Sekunden, bei einer langsamen Quelle länger. Deshalb

* wird die Standard-Postleitzahl (und zuletzt gefragte) im Hintergrund frisch gehalten,
* läuft ein Laden im Hintergrund weiter, auch wenn die Frage abgebrochen wird,
* melden lange Abfragen ihren Fortschritt, und
* bekommt das Programm nach der Frist eine freundliche „gleich noch einmal fragen“-Antwort
  statt eines Zeitüberschreitungsfehlers.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import re
import time
import threading
import hashlib
import json
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from . import grocy, history, kitchenowl, notify, runtime
from .common import format_euro, normalize_keywords, today_berlin, validate_postal_code
from .image_match import match_article
from .images import ImageServiceError
from .loyalty import PROGRAMS
from .models import RETAILER_SPECS, ToolError, resolve_retailer_names

log = logging.getLogger(__name__)

# So lange wartet eine Frage auf das Laden, bevor sie um Geduld bittet.
LOAD_DEADLINE_SECONDS = float(os.environ.get("SUPERMARKT_MCP_DEADLINE_SECONDS", "45"))
MAX_IMAGES = 3
# Schreib-Werkzeug: höchstens so viele neue Artikel pro Stunde (schützt die Einkaufsliste vor Fluten).
SHOPPING_ADDS_PER_HOUR = int(os.environ.get("SUPERMARKT_MCP_SHOPPING_ADDS_PER_HOUR", "30"))
CHECK_LIST_MAX_ITEMS = 30
# Neue Postleitzahlen (Kaltladen) pro 10 Minuten; schützt den Server vor Dauerabfragen.
NEW_POSTAL_CODE_LIMIT = int(os.environ.get("SUPERMARKT_MCP_NEW_POSTAL_CODES_PER_10MIN", "10"))
# Die Angebote wechseln wöchentlich (Donnerstag/Sonntag): Einmal am Tag nachsehen genügt. Der Zwischenspeicher
# entscheidet, ob wirklich neu geladen wird; so ist die Antwort nach dem Wechsel schon warm.
WARM_INTERVAL_SECONDS = 24 * 3600
WARM_WHILE_USED_SECONDS = 7 * 86400
MAX_WARM_POSTAL_CODES = 3

INSTRUCTIONS = (
    "Aktuelle Supermarkt-Angebote in Deutschland. Mit find_offers fragst du, wo ein Produkt gerade "
    "im Angebot ist: Die Antwort nennt Händler und Preis ohne Bonusprogramm (Kundenkarte oder App) und, wo "
    "es einen öffentlich ausgewiesenen Vorteil gibt, den Preis mit Bonusprogramm. Bei manchen Händlern "
    "(zum Beispiel EDEKA, Globus, PAYBACK, Rossmann, Müller) gibt es keinen berechenbaren Bonuspreis; das ist "
    "dann keine Aussage, dass es keinen Vorteil gibt. Preise gelten für die genannte Postleitzahl. Suche mit "
    "dem Produktnamen und, wenn nötig, Synonymen in also_search; die Suche ist eine Textsuche. Wenn es "
    "das Werkzeug add_to_shopping_list gibt, setzt es einen Artikel auf die Einkaufsliste; frage vorher, ob das "
    "gewünscht ist, und nimm Händler und Preis aus dem Fund mit. check_shopping_list zeigt, was von der "
    "Einkaufsliste gerade im Angebot ist."
)


# Häufige Alltagswörter, die im Prospekt anders heißen. Bewusst klein und von Hand gepflegt.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "osterhase": ("schokohase", "schoko-osterhase", "osterhasen"),
    "schokohase": ("osterhase", "osterhasen"),
    "weihnachtsmann": ("schoko-weihnachtsmann", "schokoweihnachtsmann", "nikolaus"),
    "klopapier": ("toilettenpapier", "hygienepapier"),
    "toilettenpapier": ("klopapier", "hygienepapier"),
    "brötchen": ("semmel", "schrippe"),
    "hackfleisch": ("gehacktes", "hack"),
    "sprudel": ("mineralwasser", "sprudelwasser"),
    "mineralwasser": ("sprudel", "wasser"),
    "joghurt": ("jogurt",),
    "jogurt": ("joghurt",),
    "ketchup": ("catchup", "tomatenketchup"),
    "mayo": ("mayonnaise",),
    "pommes": ("pommes frites", "fritten"),
    "eis": ("speiseeis", "eiscreme"),
    "spülmittel": ("geschirrspülmittel", "handspülmittel"),
    "waschmittel": ("vollwaschmittel", "colorwaschmittel", "feinwaschmittel"),
    "cola": ("coca-cola", "pepsi"),
    "nutella": ("nuss-nougat-creme", "nussnougatcreme"),
    "kaffeebohnen": ("bohnenkaffee", "ganze bohne"),
    "schmelzkäse": ("schmelzkäsezubereitung", "streichkäse"),
    "frischkäse": ("doppelrahmfrischkäse", "streichkäse"),
    "tiefkühlpizza": ("pizza", "steinofenpizza"),
    "chips": ("kartoffelchips", "kartoffelsnack"),
}
# Händler, bei denen die Angebotsdaten keinen berechenbaren Bonuspreis hergeben.
NO_COMPUTED_BONUS = ("EDEKA", "Globus", "Rossmann", "Müller")
# Retailers whose app-only prices and coupons are not public (personalised) and therefore never part of the comparison.
APP_ONLY_PRICES = {"Lidl": "Lidl Plus", "PENNY": "PENNY App", "Netto Marken-Discount": "Netto Plus App"}


def _synonyms(product: str) -> list[str]:
    key = " ".join(product.split()).casefold()
    return list(SYNONYMS.get(key, ()))


class Offer(BaseModel):
    retailer: str = Field(description="Händler, z. B. Kaufland")
    product: str
    pack: str = Field(default="", description="Packungsgröße")
    unit_price: str = Field(default="", description="Grundpreis, z. B. 8,95 €/kg")
    price_without_bonus: str = Field(description="Preis ohne Bonusprogramm")
    price_with_bonus: str | None = Field(default=None, description="Günstigerer Mitgliederpreis an der Kasse, nur wenn es einen gibt")
    bonus_credit: str | None = Field(default=None, description="Nachträglich gutgeschriebenes Bonus-Guthaben, z. B. 0,20 € REWE Bonus")
    price_after_credit: str | None = Field(default=None, description="Effektiver Preis nach Abzug des Bonus-Guthabens, z. B. 0,79 €")
    bonus_program: str | None = Field(default=None, description="Welches Programm dafür nötig ist, z. B. Kaufland Card XTRA oder REWE Bonus")
    multi_buy_quantity: int | None = None
    multi_buy_total_price: float | None = None
    single_price: float | None = None
    pack_size: str = ""
    multi_buy_condition: str = ""
    multi_buy_mix_group: str | None = None
    conditional_unit_price: float | None = None
    valid_from: str = ""
    valid_until: str = ""
    valid: str = Field(default="", description="Gültigkeit")
    image_url: str | None = Field(default=None, description="Bild des Angebots (Adresse beim Händler)")
    image_source: str = Field(default="", description="own | same_article_other_retailer; leer = kein Bild geliefert")
    image_match: str = Field(default="", description="exact | substitute (Ersatzbild: gleicher Artikel, andere Packung oder anderer Händler)")
    image_note: str = Field(default="", description="Kurzer Hinweis zur Herkunft eines Ersatzbilds")
    image_fallback_url: str | None = Field(default=None, description="Bildadresse des Ersatzbilds (gehört zu einem anderen Angebot); image_url bleibt unverändert")


class OfferResult(BaseModel):
    postal_code: str
    query: str
    found: int = Field(description="Anzahl Treffer insgesamt")
    offers: list[Offer] = Field(description="Die günstigsten Treffer zuerst (nur die Seite ab offset)")
    returned: int = Field(default=0, description="Anzahl der in offers gelieferten Treffer dieser Seite")
    offset: int = Field(default=0, description="Anzahl übersprungener Treffer vor dieser Seite")
    has_more: bool = Field(default=False, description="True, wenn es weitere Treffer ab offset+returned gibt; die Liste ist dann NICHT vollständig")
    status: Literal["ok", "empty", "partial"] = "ok"
    diagnostics: list[str] = Field(default_factory=list)


class StillLoading(Exception):
    """Die Angebote dieser Postleitzahl werden noch geladen."""


class CatalogueUnavailable(Exception):
    """Expected source outage; not an MCP transport or programming failure."""


mcp = MCPServer("korbuino", instructions=INSTRUCTIONS)

_inflight: dict[tuple, asyncio.Task] = {}
_load_failures: dict[tuple, tuple[float, str]] = {}
FAILED_LOAD_RETRY_SECONDS = 30
MAX_FAILED_LOADS = 128
_last_used: dict[str, float] = {}
_warm_started = False
_new_postal_codes: list[float] = []
_shopping_adds: list[float] = []
_WATCH_DELIVERY_LOCK = threading.Lock()
# Persist IDs independently of labels and aliases.
WATCH_RETAILERS = {
    "rewe": "REWE", "aldi-nord": "ALDI Nord", "aldi-sued": "ALDI Süd", "lidl": "Lidl",
    "penny": "PENNY", "netto": "Netto Marken-Discount", "netto-scottie": "Netto schwarz",
    "kaufland": "Kaufland", "edeka": "EDEKA", "marktkauf": "Marktkauf", "globus": "Globus",
    "famila-nordwest": "famila Nordwest", "aktiv-irma": "aktiv & irma", "combi": "Combi",
    "rossmann": "Rossmann", "mueller": "Müller", "dm": "dm", "trinkgut": "trinkgut", "holab": "HOL’AB!",
}



# ---- laden -------------------------------------------------------------------------------


def _postal_code(value: str) -> str:
    plz = validate_postal_code((value or os.environ.get("SUPERMARKT_DEFAULT_POSTAL_CODE", "")).strip())
    if not plz:
        raise MCPToolError("Bitte eine gültige deutsche Postleitzahl (fünf Ziffern) angeben.")
    return plz


def _retailers(values: list[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    resolved, unknown = resolve_retailer_names(values)
    if unknown:
        raise MCPToolError("Unbekannte Händler: " + ", ".join(unknown) + ". Gültig: " + ", ".join(spec.name for spec in RETAILER_SPECS))
    return tuple(resolved)


def _load_snapshot(plz: str, retailers: tuple[str, ...], refresh: bool = False, offer_week: str = "current") -> dict[str, Any]:
    snapshot, _from_cache = runtime.get_engine().snapshot(plz, "auto", refresh, retailers=retailers, offer_week=offer_week)
    return snapshot


def _check_new_postal_code(plz: str) -> None:
    if plz in _last_used:
        return
    now = time.time()
    _new_postal_codes[:] = [t for t in _new_postal_codes if now - t < 600]
    if len(_new_postal_codes) >= NEW_POSTAL_CODE_LIMIT:
        raise MCPToolError("Zu viele verschiedene Postleitzahlen in kurzer Zeit. Bitte in ein paar Minuten noch einmal fragen.")
    _new_postal_codes.append(now)


def _load_finished(key: tuple, task: asyncio.Task) -> None:
    owned = _inflight.get(key) is task
    if owned:
        _inflight.pop(key, None)
    if task.cancelled():
        return
    # Always retrieve the exception, including after a caller received StillLoading.
    error = task.exception()
    if isinstance(error, ToolError) and owned:
        now = time.monotonic()
        for failed_key, (expires, _detail) in list(_load_failures.items()):
            if expires <= now:
                _load_failures.pop(failed_key, None)
        _load_failures[key] = (now + FAILED_LOAD_RETRY_SECONDS, str(error))
        while len(_load_failures) > MAX_FAILED_LOADS:
            _load_failures.pop(next(iter(_load_failures)))
    elif error is not None and not isinstance(error, ToolError):
        log.error("Background catalogue load failed", exc_info=(type(error), error, error.__traceback__))


async def _snapshot(plz: str, retailers: tuple[str, ...], ctx: Context | None = None) -> dict[str, Any]:
    """Angebote laden, mit Frist. Ein begonnenes Laden läuft weiter und wird gemeinsam genutzt."""
    _check_new_postal_code(plz)
    _last_used[plz] = time.time()
    _start_warmup()
    key = (plz, tuple(sorted(retailers)))
    failure = _load_failures.get(key)
    if failure is not None:
        expires, detail = failure
        if expires > time.monotonic():
            raise CatalogueUnavailable(detail)
        _load_failures.pop(key, None)
    task = _inflight.get(key)
    # A finished task whose done-callback has not run yet is still this key's fresh outcome: reuse it, do not reload or skip the failure throttle.
    if task is None or task.cancelled():
        task = asyncio.ensure_future(asyncio.to_thread(_load_snapshot, plz, retailers))
        _inflight[key] = task
        task.add_done_callback(lambda finished, key=key: _load_finished(key, finished))
    waited = 0.0
    step = 3.0
    while not task.done():
        if waited >= LOAD_DEADLINE_SECONDS:
            raise StillLoading
        await asyncio.wait({task}, timeout=step)
        waited += step
        if ctx is not None and not task.done():
            with contextlib.suppress(Exception):
                await ctx.report_progress(min(waited, LOAD_DEADLINE_SECONDS), LOAD_DEADLINE_SECONDS, "Angebote werden geladen …")
    try:
        return task.result()
    except ToolError as exc:
        raise CatalogueUnavailable(str(exc)) from exc


def _start_warmup() -> None:
    """Hält die zuletzt gefragten Postleitzahlen frisch, solange der MCP benutzt wird."""
    global _warm_started
    if _warm_started or os.environ.get("SUPERMARKT_MCP_WARMUP", "1") == "0":
        return
    with contextlib.suppress(RuntimeError):
        asyncio.get_running_loop().create_task(_warm_loop())
        _warm_started = True


def _watch_postal_codes() -> list[str]:
    try:
        return sorted({watch["postal_code"] for watch in history.list_watches()})
    except Exception:  # noqa: BLE001 - background warmup is best-effort; a storage hiccup must not abort it
        return []


def _check_watches(plz: str, snapshot: dict[str, Any]) -> None:
    """Only acknowledge delivered batches; concurrent checks share a delivery lock."""
    with _WATCH_DELIVERY_LOCK:
        _deliver_watches(plz, snapshot)


def _deliver_watches(plz: str, snapshot: dict[str, Any]) -> None:
    week = snapshot.get("offer_week", "current")
    for watch in history.list_watches(plz):
        selected = _watch_selected_retailers(watch, week)
        if selected is None:
            continue
        keys = _watch_offer_keys(snapshot, watch, selected)
        pending = _pending_watch_keys(watch, keys)
        _notify_watch_batches(watch, keys, pending)


def _watch_selected_retailers(watch: dict[str, Any], week: str) -> tuple[str, ...] | None:
    """Liefert die gewählten Händler einer Beobachtung, oder None wenn Woche oder Händler nicht passen."""
    if watch["offer_week"] not in {week, "all"}:
        return None
    if any(i not in WATCH_RETAILERS for i in watch["retailer_ids"]):
        return None
    return tuple(WATCH_RETAILERS[i] for i in watch["retailer_ids"])


def _watch_offer_keys(snapshot: dict[str, Any], watch: dict[str, Any], selected: tuple[str, ...]) -> dict[str, tuple[Any, str]]:
    """Baut die stabilen Identitäts-Schlüssel (und die Legacy-Schlüssel) der aktuellen Treffer einer Beobachtung."""
    keys: dict[str, tuple[Any, str]] = {}
    for offer in _offers_from(snapshot, watch["query"], None, selected):
        if selected and offer.retailer not in selected:
            continue
        # Server watches have no selected membership list; compare the regular
        # checkout amount. Conditional member prices may only be shown alongside.
        if offer.multi_buy_quantity and re.search(r"card|karte|coupon|kupon|aktivier|mitglied|xtra|\bapp\b", offer.multi_buy_condition, re.IGNORECASE):
            continue  # No verified membership/coupon selection on server watches.
        shown = offer.price_without_bonus
        if watch["max_cents"] is not None and _euro(shown) * 100 > watch["max_cents"] + 0.5:
            continue
        # The same advertised validity retains its identity when preview becomes current.
        # Legacy keys remain readable so an upgrade does not repeat delivered offers.
        legacy = f"{offer.retailer}|{offer.product}|{shown}|{offer.valid}"
        identity = [offer.retailer, offer.product, offer.pack, shown,
                    offer.valid_from or offer.valid, offer.valid_until, offer.multi_buy_quantity]
        stable = "v2:" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        keys[stable] = (offer, legacy)
    return keys


def _pending_watch_keys(watch: dict[str, Any], keys: dict[str, tuple[Any, str]]) -> list[str]:
    """Filtert die Schlüssel, die weder unter dem stabilen noch unter dem Legacy-Schlüssel schon gemeldet wurden."""
    fresh = set(history.unnotified(watch["id"], list(keys)))
    old_fresh = set(history.unnotified(watch["id"], [legacy for _, legacy in keys.values()]))
    return [key for key in keys if key in fresh and keys[key][1] in old_fresh]


def _notify_watch_batches(watch: dict[str, Any], keys: dict[str, tuple[Any, str]], pending: list[str]) -> None:
    """Sendet die ausstehenden Treffer einer Beobachtung in Fünfer-Batches und markiert erfolgreiche als gemeldet."""
    for start in range(0, len(pending), 5):
        batch = pending[start:start + 5]
        lines = []
        for key in batch:
            offer = keys[key][0]
            extra = f" (optional mit {offer.bonus_program}: {offer.price_with_bonus})" if offer.price_with_bonus else ""
            if offer.bonus_credit:
                extra += f" (zusätzlich {offer.bonus_credit} {_program_name(offer)} Guthaben nach dem Kauf; nicht abgezogen)"
            if offer.multi_buy_quantity and offer.multi_buy_total_price is not None:
                extra += f" · {offer.multi_buy_quantity} Stück für insgesamt {format_euro(offer.multi_buy_total_price)}"
                extra += f" ({format_euro(offer.multi_buy_total_price / offer.multi_buy_quantity)} je Stück nur im Mehrkauf)"
                extra += f" · {offer.multi_buy_condition}" if offer.multi_buy_condition else ""
            validity = f" ({offer.valid})" if offer.valid else ""
            lines.append(f"{offer.retailer}: {offer.product} {offer.price_without_bonus}{extra}{validity}")
        try:
            notify.send(f"Korbuino: {watch['query']} im Angebot", "\n".join(lines))
        except notify.NotifyError:
            # Exceptions can contain the secret topic URL or response body.
            log.warning("Benachrichtigung für Beobachtung %s fehlgeschlagen", watch["id"])
            break
        history.mark_notified(watch["id"], batch)


_background_checks: set[asyncio.Task] = set()


async def _check_new_watch(plz: str, offer_week: str) -> None:
    """Prüft eine neue Beobachtung sofort; sonst käme die erste Meldung erst beim nächsten Tagestakt."""
    for week in (("current", "next") if offer_week == "all" else (offer_week,)):
        try:
            snapshot = await asyncio.to_thread(_load_snapshot, plz, (), False, week)
            await asyncio.to_thread(_check_watches, plz, snapshot)
        except Exception:  # noqa: BLE001 - die Beobachtung bleibt gespeichert und wird im Tagestakt erneut geprüft
            log.warning("Sofortprüfung für %s fehlgeschlagen", plz, exc_info=True)


def _spawn_watch_check(plz: str, offer_week: str) -> None:
    if os.environ.get("SUPERMARKT_MCP_WARMUP", "1") == "0":
        return
    task = asyncio.ensure_future(_check_new_watch(plz, offer_week))
    _background_checks.add(task)
    task.add_done_callback(_background_checks.discard)


async def _warm_loop() -> None:
    default = validate_postal_code(os.environ.get("SUPERMARKT_DEFAULT_POSTAL_CODE", "")) or ""
    if default:
        _last_used.setdefault(default, time.time())
    delay = 60.0  # kurz nach dem Start einmal nachsehen, danach im Takt
    while True:
        await asyncio.sleep(delay)
        delay, now = WARM_INTERVAL_SECONDS, time.time()
        recent = sorted((p for p, used in _last_used.items() if now - used < WARM_WHILE_USED_SECONDS), key=lambda p: -_last_used[p])
        for plz in dict.fromkeys([*recent[:MAX_WARM_POSTAL_CODES], *_watch_postal_codes()]):
            try:
                weeks = {"current"}
                for watch in history.list_watches(plz):
                    if watch["offer_week"] in {"next", "all"}:
                        weeks.add("next")
                for week in sorted(weeks):
                    snapshot = await asyncio.to_thread(_load_snapshot, plz, (), False, week)
                    await asyncio.to_thread(_check_watches, plz, snapshot)
            except Exception:  # noqa: BLE001 - Vorwärmen darf nie stören
                log.warning("Vorwärmen für %s fehlgeschlagen", plz, exc_info=True)


# ---- Werkzeuge ---------------------------------------------------------------------------


def _euro(text: str) -> float:
    try:
        return float(text.replace("€", "").replace(".", "").replace(",", ".").strip())
    except ValueError:
        return float("inf")


def _offers_from(snapshot: dict[str, Any], product: str, also_search: list[str] | None, retailers: tuple[str, ...]) -> list[Offer]:
    engine = runtime.get_engine()
    common = {"page": 1, "page_size": 100, "view": "all", "sort": "price", "include_image_urls": True, "retailer_filters": retailers}
    # The page engine ANDs filter_text with keywords. Synonyms/variants are
    # alternatives, so query them independently with the same full-text rules
    # (including brand/description), then merge IDs rather than intersecting.
    queries = [product, *(query for query in normalize_keywords(also_search or ()) if query.casefold() != product.casefold())]
    def pages(programs):
        rows = {}
        available = {}
        for query in queries:
            selected = {**common, "filter_text": query, "keywords": ()}
            first = engine.page(snapshot, loyalty_programs=programs, **selected)
            matches = list(first.get("offers", []))
            for number in range(2, int(first.get("page_count", 1)) + 1):
                matches.extend(engine.page(snapshot, loyalty_programs=programs, **{**selected, "page": number}).get("offers", []))
            for offer in matches:
                rows.setdefault(offer["offer_id"], offer)
            for program in first.get("available_loyalty_programs", []):
                previous = available.get(program["id"])
                if previous is None or program.get("priced_offer_count", 0) > previous.get("priced_offer_count", 0):
                    available[program["id"]] = program
        return {"offers": list(rows.values()), "available_loyalty_programs": list(available.values())}

    plain = pages(())
    programs = tuple(p["id"] for p in plain.get("available_loyalty_programs", []) if p.get("priced_offer_count"))
    with_bonus = pages(programs) if programs else plain
    bonus_by_id = {offer["offer_id"]: offer for offer in with_bonus.get("offers", [])}
    result: list[Offer] = []
    for item in plain.get("offers", []):
        other = bonus_by_id.get(item["offer_id"], item)
        regular = item.get("effective_price")
        discounted = other.get("effective_price")
        cheaper = discounted is not None and regular is not None and discounted < regular
        # Cashback (e.g. REWE Bonus) is credited after checkout, so it never
        # lowers the checkout price or the ranking. It was dropped entirely
        # before; surface it as a separate credit with the effective net price.
        credit = other.get("cashback_credit") or 0.0
        has_credit = credit > 0 and discounted is not None
        borrowed = item.get("image_source") == "same_article_other_retailer"
        result.append(Offer(
            retailer=item["retailer"], product=item["product"], pack=item.get("pack", ""), unit_price=item.get("unit_price", ""),
            price_without_bonus=item["regular_price_text"],
            multi_buy_quantity=item.get("multi_buy_quantity"), multi_buy_total_price=item.get("multi_buy_total_price"),
            single_price=item.get("single_price"), pack_size=item.get("pack_size") or "",
            multi_buy_condition=item.get("multi_buy_condition") or "",
            multi_buy_mix_group=item.get("multi_buy_mix_group"), conditional_unit_price=item.get("conditional_unit_price"),
            price_with_bonus=other["effective_price_text"] if cheaper else None,
            bonus_credit=other.get("cashback_credit_text") if has_credit else None,
            price_after_credit=format_euro(discounted - credit) if has_credit else None,
            bonus_program=(other.get("loyalty_benefit") or None) if (cheaper or has_credit) else None,
            valid=item.get("validity", ""), valid_from=item.get("valid_from") or "", valid_until=item.get("valid_until") or "", image_url=(None if borrowed else item.get("image_url") or None),
            image_source=item.get("image_source") or "", image_match=item.get("image_match") or "", image_note=item.get("image_note") or "",
            image_fallback_url=(item.get("image_url") if borrowed else None),
        ))
    # Offers whose ISO end date is already past (Europe/Berlin) are over; later-starting ones stay (see find_offers).
    today = today_berlin().isoformat()
    result = [offer for offer in result if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", offer.valid_until[:10]) or offer.valid_until[:10] >= today]
    # Ranking stays on the checkout price; cashback is deliberately excluded.
    result.sort(key=lambda offer: _euro(offer.price_with_bonus or offer.price_without_bonus))
    return result


def _search_variants(product: str) -> list[str]:
    """Einzelwörter und gekürzte Beugungsformen („Joghurts“ → „Joghurt“), wenn die ganze Wortgruppe nichts findet."""
    variants: list[str] = []
    for word in re.findall(r"[\wäöüß-]{3,}", product, flags=re.IGNORECASE):
        for form in (word, word[:-1] if word.lower().endswith(("s", "n", "e")) else "", word[:-2] if word.lower().endswith(("en", "er")) else ""):
            if len(form) >= 4 and form.lower() != product.lower() and form not in variants:
                variants.append(form)
    return variants


def _image_block(offer: Offer, url: str | None = None) -> ImageContent | None:
    """Bild des Angebots über den Bilddienst des Servers (Adressprüfung, Zwischenspeicher, Größenlimit)."""
    url = url or offer.image_url
    if not url:
        return None
    try:
        image = runtime.get_image_service().get(source_url=url, product=offer.product, retailer=offer.retailer)
    except (ImageServiceError, ToolError, OSError, ValueError):
        return None
    return ImageContent(type="image", data=base64.b64encode(image.data).decode("ascii"), mime_type=image.content_type)


def _image_with_fallback(offer: Offer, candidates: list[Offer]) -> ImageContent | None:
    """Own image first; otherwise the image of the same article at another retailer, labelled as a substitute."""
    block = _image_block(offer) if offer.image_url else None
    if block is not None:
        offer.image_source, offer.image_match, offer.image_note = "own", "exact", ""
        return block
    if offer.image_fallback_url:  # the catalogue already picked the same article elsewhere (labelled by image_note)
        block = _image_block(offer, offer.image_fallback_url)
        if block is not None:
            return block
    donors = [(other, match_article(offer.product, other.product)) for other in candidates
              if other is not offer and other.retailer != offer.retailer and other.image_url]
    # exact pack matches first, then cheaper-to-explain ones; at most 2 donor attempts keep this bounded.
    ranked = sorted(((other, kind) for other, kind in donors if kind), key=lambda pair: (pair[1] != "exact", pair[0].retailer))[:2]
    for other, kind in ranked:
        block = _image_block(other)
        if block is not None:
            offer.image_fallback_url = other.image_url
            offer.image_source = "same_article_other_retailer"
            offer.image_match = kind
            offer.image_note = (f"Bild von {other.retailer}: gleicher Artikel, gleiche Packung" if kind == "exact"
                                else f"Ersatzbild von {other.retailer}: gleicher Artikel laut Name, Packung abweichend oder unbekannt")
            return block
    return None


def _valid_text(offer: Offer) -> str:
    """Gültigkeit lesbar: deutsche Daten, ohne vorangestellten Händlernamen."""
    text = re.sub(r"(\d{4})-(\d{2})-(\d{2})", r"\3.\2.\1", offer.valid)
    prefix = offer.retailer + ", "
    return text[len(prefix):] if text.startswith(prefix) else text


def _program_name(offer: Offer) -> str:
    """Nur der Programmname ohne angehängten Betrag, z. B. „REWE Bonus“."""
    return (offer.bonus_program or "").split(":", 1)[0].strip() or "Bonusprogramm"


def _summary(result: OfferResult) -> str:
    if result.has_more or result.offset:
        first = result.offset + 1
        lines = [f"{result.returned} von {result.found} Treffern für „{result.query}“ (PLZ {result.postal_code}), Nr. {first}–{result.offset + result.returned}, günstigste zuerst:"]
    else:
        lines = [f"{result.found} Treffer für „{result.query}“ (PLZ {result.postal_code}), günstigste zuerst:"]
    for offer in result.offers:
        line = f"- {offer.retailer}: {offer.product} {offer.pack}".rstrip() + f" – {offer.price_without_bonus} ohne Bonus"
        if offer.price_with_bonus:
            line += f", {offer.price_with_bonus} mit {offer.bonus_program or 'Bonusprogramm'}"
        elif offer.price_after_credit and offer.bonus_credit:
            line += f", effektiv {offer.price_after_credit} mit {offer.bonus_credit} {_program_name(offer)} Guthaben"
        if offer.multi_buy_quantity and offer.multi_buy_total_price is not None:
            line += f" · {offer.multi_buy_quantity} Stück für insgesamt {format_euro(offer.multi_buy_total_price)}"
            line += f" ({format_euro(offer.multi_buy_total_price / offer.multi_buy_quantity)} je Stück nur im Mehrkauf)"
            if offer.multi_buy_condition:
                line += f" · {offer.multi_buy_condition}"
        if offer.unit_price:
            line += f" ({offer.unit_price})"
        valid = _valid_text(offer)
        if valid:
            # Manche Quellen schreiben schon "gültig ..." in die Angabe.
            line += ", " + (valid if "gültig" in valid.casefold() else f"gültig {valid}")
        lines.append(line)
    if result.has_more:
        lines.append(f"UNVOLLSTÄNDIG: {result.found - result.offset - result.returned} weitere Treffer; Rest mit offset={result.offset + result.returned} abrufen (limit höchstens 25). Teurere Treffer, auch andere Marken, stehen weiter hinten.")
    return "\n".join(lines)


def _waiting_result(plz: str, query: str) -> CallToolResult:
    text = (
        f"Die Angebote für die Postleitzahl {plz} werden geladen. Das läuft im Hintergrund weiter; "
        "andere gleichzeitige Abrufe können noch davor liegen. Bitte frage in etwa 30 Sekunden noch einmal "
        "genau dasselbe. Ein laufender Abruf wird dabei gemeinsam genutzt."
    )
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content={"status": "loading", "postal_code": plz, "query": query})


def _unavailable_result(plz: str, query: str, error: CatalogueUnavailable) -> CallToolResult:
    detail = str(error)[:1200]
    return CallToolResult(
        content=[TextContent(type="text", text="Angebotsabruf nicht verfügbar. Ob das Produkt im Angebot ist, bleibt unbekannt. " + detail)],
        structured_content={"status": "unavailable", "postal_code": plz, "query": query, "diagnostics": [detail], "retry_after_seconds": 30},
    )


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def find_offers(
    product: str,
    postal_code: str = "",
    retailers: list[str] | None = None,
    also_search: list[str] | None = None,
    limit: int = 8,
    with_images: bool = True,
    max_images: int = 1,
    offset: int = 0,
    ctx: Context | None = None,
) -> CallToolResult:
    """Welche Angebote gibt es in der aktuellen Woche? Liefert Händler und Preis ohne und, falls vorhanden, mit Bonusprogramm.

    Auch bereits veröffentlichte Angebote späterer Wochentage sind enthalten.
    Ihre Gültigkeit unbedingt nennen; ein Vorschaupreis gilt noch nicht heute.
    Angebote mit bereits abgelaufenem Enddatum werden ausgeblendet.

    Args:
        product: Suchbegriff, z. B. "Kaffee". Leer mit retailers = Angebote dieser Händler durchsehen.
        postal_code: Deutsche Postleitzahl (fünf Ziffern). Leer = Standard des Servers.
        retailers: Nur diese Händler, z. B. ["Kaufland", "REWE"]. Leer = alle. Gültige Namen liefert list_retailers.
        also_search: Weitere Suchbegriffe für dieselbe Frage (ODER), z. B. Synonyme oder Schreibweisen.
        limit: Höchstens so viele Treffer, die günstigsten zuerst (1 bis 25).
        with_images: Bilder der ersten Treffer mitschicken.
        max_images: Wie viele Bilder (0 bis 3, Standard 1); jedes Bild kostet Kontext.
        offset: So viele günstigste Treffer überspringen (Blättern). found ist die Gesamtzahl, returned die Zahl dieser Seite;
            ist has_more wahr, ist die Liste unvollständig. Die Suche prüft Name, Marke und Beschreibung, nicht die Warengruppe:
            Marken, deren Angebot den Begriff nicht enthält, per also_search ergänzen.
    """
    plz = _postal_code(postal_code)
    wanted = _retailers(retailers)
    product = product.strip()
    if not product and not wanted:
        raise MCPToolError("Bitte ein Produkt oder mindestens einen Händler zum Durchsehen angeben.")
    limit = max(1, min(int(limit), 25))
    offset = max(0, int(offset))
    try:
        snapshot = await _snapshot(plz, wanted, ctx)
    except StillLoading:
        return _waiting_result(plz, product)
    except CatalogueUnavailable as exc:
        return _unavailable_result(plz, product, exc)
    offers, widened = await _search_offers_with_widening(snapshot, product, also_search, wanted)
    diagnostics = _offer_diagnostics(snapshot)
    status = "partial" if diagnostics else ("ok" if offers else "empty")
    page = offers[offset:offset + limit]
    result = OfferResult(
        postal_code=plz, query=product or "Alle Angebote", found=len(offers), offers=page, returned=len(page), offset=offset,
        has_more=offset + len(page) < len(offers), status=status, diagnostics=diagnostics,
    )
    if offers and not page:
        text = f"{result.found} Treffer für „{result.query}“ (PLZ {plz}), aber offset={offset} liegt dahinter; es gibt keine weiteren."
        if diagnostics:
            text += "\nAbruf unvollständig: " + " | ".join(diagnostics)
        return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=result.model_dump())
    if not result.offers:
        text = f"Keine Angebote für „{result.query}“ bei der Postleitzahl {plz} gefunden. Versuche einen anderen Begriff oder Synonyme (also_search)."
        if diagnostics:
            text = "Keine Treffer in den verfügbaren Daten; der Abruf ist unvollständig. " + " | ".join(diagnostics)
        return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=result.model_dump())
    content: list[TextContent | ImageContent] = [TextContent(type="text", text=_summary(result))]
    _append_offer_hints(content[0], result, diagnostics, widened)
    if with_images and max_images > 0:
        await _attach_offer_images(content, result, offers, max_images)
    return CallToolResult(content=content, structured_content=result.model_dump())


async def _search_offers_with_widening(
    snapshot: dict[str, Any], product: str, also_search: list[str] | None, wanted: tuple[str, ...]
) -> tuple[list[Any], bool]:
    """Sucht ``product`` im Snapshot; weitet bei leerem Ergebnis auf Wort-Varianten aus."""
    also_search = [*(also_search or []), *_synonyms(product)]
    offers = await asyncio.to_thread(_offers_from, snapshot, product.strip(), also_search, wanted)
    if offers:
        return offers, False
    variants = _search_variants(product)
    if not variants:
        return offers, False
    offers = await asyncio.to_thread(_offers_from, snapshot, product.strip(), [*also_search, *variants], wanted)
    return offers, bool(offers)


def _offer_diagnostics(snapshot: dict[str, Any]) -> list[str]:
    """store_warnings tragen Fallback-Hinweise (z. B. "offizielle Seite nicht lesbar; KaufDA nur ein Ausschnitt");
    Fehler allein würden in die Irre führen."""
    return list(dict.fromkeys(str(note)[:240] for note in [*snapshot.get("request_errors", []), *snapshot.get("store_warnings", [])] if note))[:8]


def _append_offer_hints(text_content: TextContent, result: OfferResult, diagnostics: list[str], widened: bool) -> None:
    """Hängt Diagnose- und Hinweistexte (fehlende Bonuspreise, App-only-Preise) an das Summary-TextContent an."""
    if diagnostics:
        text_content.text += "\nAbruf unvollständig: " + " | ".join(diagnostics)
    if widened:
        text_content.text += "\n(Nichts mit genau diesem Begriff; gezeigt sind ähnliche Treffer zu einzelnen Wörtern.)"
    silent = sorted({offer.retailer for offer in result.offers if offer.retailer in NO_COMPUTED_BONUS and not offer.price_with_bonus})
    if silent:
        text_content.text += f"\nHinweis: Bei {', '.join(silent)} gibt es keinen berechenbaren Bonuspreis; das heißt nicht, dass es keinen Vorteil gibt."
    apps = [APP_ONLY_PRICES[name] for name in APP_ONLY_PRICES if any(offer.retailer == name for offer in result.offers)]
    if apps:
        text_content.text += f"\nHinweis: App-Preise und persönliche Coupons ({', '.join(apps)}) sind nicht enthalten; gezeigt sind die öffentlichen Preise. Dort kann es günstiger sein."


async def _attach_offer_images(
    content: list[TextContent | ImageContent], result: OfferResult, offers: list[Any], max_images: int
) -> None:
    """Hängt bis zu ``max_images`` Produktbilder (eigenes oder vom selben Artikel bei einem anderen Händler) an."""
    wanted_images = min(max_images, MAX_IMAGES)
    found_images = 0
    # Walk the page cheapest-first; each offer tries its own image, then the same article from another retailer.
    # At most 6 offers are tried, so dead image links cannot cause an unbounded number of downloads.
    for offer in result.offers[:6]:
        block = await asyncio.to_thread(_image_with_fallback, offer, offers)
        if block is None:
            continue
        label = f"Bild: {offer.retailer} – {offer.product}"
        if offer.image_source == "same_article_other_retailer":
            label += f" ({offer.image_note})"
        content.append(TextContent(type="text", text=label))
        content.append(block)
        found_images += 1
        if found_images >= wanted_images:
            break
    if not found_images:
        content[0].text += "\nKein passendes Produktbild gefunden (weder eigenes noch von demselben Artikel bei einem anderen Händler)."


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
def list_retailers() -> list[dict[str, Any]]:
    """Welche Händler kennt Korbuino, und welches Bonusprogramm gehört zu welchem?"""
    programs: dict[str, list[str]] = {}
    for program in PROGRAMS:
        for retailer in program.retailers:
            programs.setdefault(retailer, []).append(program.label)
    return [{"name": spec.name, "bonus_programs": programs.get(spec.name, [])} for spec in RETAILER_SPECS]


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def list_bonus_programs(postal_code: str = "", ctx: Context | None = None) -> CallToolResult:
    """Welche Bonusprogramme (Kundenkarten oder Apps) berücksichtigt Korbuino, und für wie viele Angebote gibt es einen Preis?"""
    plz = _postal_code(postal_code)
    try:
        snapshot = await _snapshot(plz, (), ctx)
    except StillLoading:
        return _waiting_result(plz, "")
    except CatalogueUnavailable as exc:
        return _unavailable_result(plz, "Bonusprogramme", exc)
    page = await asyncio.to_thread(
        runtime.get_engine().page, snapshot, page=1, page_size=1, view="best_only", sort="price", loyalty_programs=(),
    )
    programs = [
        {"id": p["id"], "name": p["label"], "retailers": p["retailers"], "offers_with_price": p["priced_offer_count"], "note": p.get("note", "")}
        for p in page.get("available_loyalty_programs", [])
    ]
    text = "\n".join(f"- {p['name']} ({', '.join(p['retailers'])}): {p['offers_with_price']} Angebote mit Preis" for p in programs)
    return CallToolResult(content=[TextContent(type="text", text=text or "Keine Bonusprogramme.")], structured_content={"programs": programs})


# ---- Einkaufsliste (optional, schreibend) ---------------------------------------------------
#
# Nur vorhanden, wenn KitchenOwl im Server eingerichtet ist (Seite /settings oder Umgebungsvariablen).
# Das Werkzeug legt nur Artikel an; es liest, ändert oder löscht nichts.


async def add_to_shopping_list(item: str, retailer: str = "", price: str = "", note: str = "") -> CallToolResult:
    """Setzt einen Artikel auf die Einkaufsliste (KitchenOwl). Legt nur an, ändert und löscht nichts.

    Args:
        item: Artikelname, z. B. "Hochland Schmelzkäse".
        retailer: Händler, bei dem er im Angebot ist (kommt in die Notiz), z. B. "Kaufland".
        price: Preis, der in die Notiz kommt, z. B. "1,59 €".
        note: Weitere Notiz.
    """
    name = " ".join(item.split())[:120]
    if not name:
        raise ValueError("Bitte sage, welcher Artikel auf die Liste soll.")
    parts = [f"bei {' '.join(retailer.split())[:40]}" if retailer.strip() else "", " ".join(price.split())[:20], " ".join(note.split())[:120]]
    description = " · ".join(part for part in parts if part)
    settings = kitchenowl.load()
    grocy_settings = grocy.load() if settings is None else None
    if settings is None and grocy_settings is None:
        raise ValueError("Weder KitchenOwl noch Grocy ist auf diesem Server als Einkaufsliste eingerichtet.")
    now = time.time()
    _shopping_adds[:] = [t for t in _shopping_adds if now - t < 3600]
    if len(_shopping_adds) >= SHOPPING_ADDS_PER_HOUR:
        raise ValueError("Zu viele neue Artikel in dieser Stunde. Bitte später noch einmal.")
    try:
        if grocy_settings is not None:
            outcome = (await asyncio.to_thread(grocy.add_items, grocy_settings, [(name, description, 1.0)]))[0]
            added = outcome["status"] == "added"
        else:
            added = await asyncio.to_thread(kitchenowl.add_item, settings, name, description)
    except (kitchenowl.KitchenOwlError, grocy.GrocyError) as exc:
        raise ValueError(str(exc)) from exc
    if added:
        _shopping_adds.append(now)
    text = f"„{name}“ steht jetzt auf der Einkaufsliste." if added else f"„{name}“ stand schon auf der Einkaufsliste."
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content={"item": name, "added": added, "note": description})


async def check_shopping_list(postal_code: str = "", ctx: Context | None = None) -> CallToolResult:
    """Welche Artikel auf meiner Einkaufsliste (KitchenOwl) sind gerade im Angebot? Nur lesen.

    Args:
        postal_code: Deutsche Postleitzahl (fünf Ziffern). Leer = Standard des Servers.
    """
    settings = kitchenowl.load()
    grocy_settings = grocy.load() if settings is None else None
    if settings is None and grocy_settings is None:
        raise ValueError("Weder KitchenOwl noch Grocy ist auf diesem Server als Einkaufsliste eingerichtet.")
    plz = _postal_code(postal_code)
    try:
        lister = (lambda: grocy.list_items(grocy_settings)) if grocy_settings is not None else (lambda: kitchenowl.list_items(settings))
        items = (await asyncio.to_thread(lister))[:CHECK_LIST_MAX_ITEMS]
    except (kitchenowl.KitchenOwlError, grocy.GrocyError) as exc:
        raise ValueError(str(exc)) from exc
    if not items:
        return CallToolResult(content=[TextContent(type="text", text="Die Einkaufsliste ist leer.")], structured_content={"items": []})
    try:
        snapshot = await _snapshot(plz, (), ctx)
    except StillLoading:
        return _waiting_result(plz, "Einkaufsliste")
    except CatalogueUnavailable as exc:
        return _unavailable_result(plz, "Einkaufsliste", exc)
    rows: list[dict[str, Any]] = []
    lines: list[str] = []
    for entry in items:
        offers = (await asyncio.to_thread(_offers_from, snapshot, entry["name"], None, ()))[:2]
        rows.append({"item": entry["name"], "offers": [offer.model_dump() for offer in offers]})
        if offers:
            best = offers[0]
            price = best.price_with_bonus or best.price_without_bonus
            extra = f" mit {best.bonus_program}" if best.price_with_bonus else ""
            lines.append(f"- {entry['name']}: {best.retailer} {best.product} {price}{extra}")
        else:
            lines.append(f"- {entry['name']}: nicht im Angebot")
    on_offer = sum(1 for row in rows if row["offers"])
    text = f"{on_offer} von {len(rows)} Artikeln der Liste sind im Angebot (PLZ {plz}):\n" + "\n".join(lines)
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content={"postal_code": plz, "items": rows})


def register_shopping_tool() -> bool:
    """Meldet das Einkaufslisten-Werkzeug an, wenn KitchenOwl eingerichtet ist; sonst bleibt es unsichtbar."""
    for name in ("add_to_shopping_list", "check_shopping_list"):
        with contextlib.suppress(Exception):
            mcp.remove_tool(name)
    if kitchenowl.load() is None and grocy.load() is None:
        return False
    mcp.add_tool(add_to_shopping_list, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True))
    mcp.add_tool(check_shopping_list, annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    return True


register_shopping_tool()


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def price_history(product: str, postal_code: str = "", days: int = 90) -> CallToolResult:
    """Wie haben sich die Angebotspreise für ein Produkt entwickelt? Nur was dieser Server selbst gesehen hat.

    Args:
        product: Suchbegriff, alle Wörter müssen im Namen vorkommen, z. B. "Hochland Schmelzkäse".
        postal_code: Deutsche Postleitzahl. Leer = Standard des Servers.
        days: Zeitraum in Tagen (1 bis 400).
    """
    if not product.strip():
        raise ValueError("Bitte sage, für welches Produkt der Verlauf gewünscht ist.")
    plz = _postal_code(postal_code)
    rows = await asyncio.to_thread(history.price_history, product.strip(), plz, int(days))
    if not rows:
        text = (f"Für „{product.strip()}“ hat dieser Server bei PLZ {plz} noch keine Preise gesehen. "
                "Der Verlauf wächst mit jedem Abruf; er beginnt erst ab der Einrichtung dieser Funktion.")
        return CallToolResult(content=[TextContent(type="text", text=text)], structured_content={"postal_code": plz, "history": []})
    def euro(cents: int) -> str:
        return f"{cents / 100:.2f}".replace(".", ",") + " €"

    def german(day: str) -> str:
        return ".".join(reversed(day.split("-")))
    lines = [
        f"- {r['retailer']}: {r['product']} – zuletzt {euro(r['last_cents'])} ({german(r['last_seen'])}), "
        f"niedrigster {euro(r['lowest_cents'])}, höchster {euro(r['highest_cents'])}, an {r['days_seen']} Tag(en) gesehen seit {german(r['first_seen'])}"
        for r in rows
    ]
    return CallToolResult(content=[TextContent(type="text", text=f"Preisverlauf (PLZ {plz}):\n" + "\n".join(lines))],
                          structured_content={"postal_code": plz, "history": rows})


async def watch_product(product: str, max_price: str = "", postal_code: str = "", retailer_ids: list[str] | None = None, offer_week: str = "current") -> CallToolResult:
    """Gib Bescheid, sobald ein Produkt im Angebot ist (optional nur unter einem Preis). Benachrichtigung per ntfy/Webhook.

    Args:
        product: Suchbegriff, z. B. "Kaffee".
        max_price: Höchstpreis in Euro an der Kasse, bei Mehrkauf für das ganze Angebotspaket (nicht je Stück). Leer = jedes Angebot.
        postal_code: Deutsche Postleitzahl. Leer = Standard des Servers.
        retailer_ids: Stabile Händler-IDs, z. B. rewe oder lidl; leer = alle.
        offer_week: current, next oder all. Vorschau nur soweit vom Händler verfügbar.
    """
    selected = tuple(sorted(set(retailer_ids or ())))
    if any(i not in WATCH_RETAILERS for i in selected):
        raise ValueError("Unbekannte Händler-ID. Gültig: " + ", ".join(WATCH_RETAILERS))
    if offer_week not in {"current", "next", "all"}:
        raise ValueError("Angebotszeitraum muss current, next oder all sein.")
    if not product.strip():
        raise ValueError("Bitte sage, welches Produkt beobachtet werden soll.")
    if notify.load() is None:
        raise ValueError("Es ist keine Benachrichtigung eingerichtet (Seite /settings des Servers).")
    plz = _postal_code(postal_code)
    limit = None
    if max_price.strip():
        raw = max_price.replace("€", "").strip()
        euros = _euro(raw if "," in raw else raw.replace(".", ","))
        if euros == float("inf") or euros <= 0:
            raise ValueError("Der Höchstpreis ist keine Zahl, zum Beispiel 5,49.")
        limit = round(euros * 100)
    watch = await asyncio.to_thread(history.add_watch, " ".join(product.split())[:80], limit, plz, selected, offer_week)
    _last_used.setdefault(plz, time.time())
    _start_warmup()
    _spawn_watch_check(plz, offer_week)
    price = f" bis {format_euro(limit / 100)} Kassenpreis (bei Mehrkauf für das gesamte Paket)" if limit is not None else ""
    return CallToolResult(content=[TextContent(type="text", text=f"Ich gebe Bescheid, sobald „{watch['query']}“{price} im Angebot ist (PLZ {plz}, Nr. {watch['id']}).")],
                          structured_content=watch)


async def list_watches() -> CallToolResult:
    """Welche Produkte werden beobachtet?"""
    watches = await asyncio.to_thread(history.list_watches)
    if not watches:
        return CallToolResult(content=[TextContent(type="text", text="Es wird nichts beobachtet.")], structured_content={"watches": []})
    lines = [f"- Nr. {w['id']}: {w['query']}" + (f" unter {w['max_cents'] / 100:.2f} €".replace(".", ",") if w["max_cents"] else "") + f" (PLZ {w['postal_code']}; Händler: {', '.join(w['retailer_ids']) or 'alle'}; Zeitraum: {w['offer_week']})" for w in watches]
    return CallToolResult(content=[TextContent(type="text", text="\n".join(lines))], structured_content={"watches": watches})


async def remove_watch(watch_id: int) -> CallToolResult:
    """Beobachtung beenden.

    Args:
        watch_id: Nummer aus list_watches.
    """
    removed = await asyncio.to_thread(history.remove_watch, int(watch_id))
    text = f"Beobachtung {watch_id} ist beendet." if removed else f"Eine Beobachtung {watch_id} gibt es nicht."
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content={"removed": removed})


def register_watch_tools() -> bool:
    """Beobachten braucht einen Benachrichtigungsweg; ohne ihn sind die Werkzeuge unsichtbar."""
    for name in ("watch_product", "list_watches", "remove_watch"):
        with contextlib.suppress(Exception):
            mcp.remove_tool(name)
    if notify.load() is None:
        return False
    mcp.add_tool(watch_product, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True))
    mcp.add_tool(list_watches, annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    mcp.add_tool(remove_watch, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
    return True


register_watch_tools()


def start_background() -> None:
    """Beim Serverstart aufrufen, damit Beobachtungen auch ohne MCP-Anfrage geprüft werden."""
    if _watch_postal_codes():
        _start_warmup()


def main() -> None:  # pragma: no cover - Einstieg für stdio
    mcp.run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
