"""Strict KaufDA single-offer images used only to enrich official Globus data."""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime
from math import isfinite
from typing import Any, Optional
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup

from ..categories import category_decision
from ..common import build_match_key, clean_brand, clean_text, format_validity, normalize_pack, parse_number, offer_validity
from ..config import BERLIN
from ..http import HttpClient
from ..images import is_rejected_image_url, normalize_image_url
from ..models import Offer, ToolError
from ..loyalty import parse_public_loyalty_prices


class KaufdaGlobusImageSource:
    BASE = "https://www.kaufda.de/{city}/Globus/p-r37"
    MAX_RESPONSE = 2_000_000

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def load(self, locality: str) -> list[Offer]:
        city = quote(clean_text(locality), safe="-")
        if not city:
            return []
        url = self.BASE.format(city=city)
        payload = self.http.get_bytes(url, {"Accept": "text/html"})
        if len(payload) > self.MAX_RESPONSE:
            raise ToolError("KaufDA-Globus-Seite überschreitet das Größenlimit")
        return self.parse(payload.decode("utf-8", errors="replace"), url)

    @classmethod
    def parse(cls, page: str, source_url: str) -> list[Offer]:
        match = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            page,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            raise ToolError("KaufDA lieferte keine strukturierten Globus-Bilddaten")
        try:
            payload = json.loads(html.unescape(match.group(1)))
            information = payload["props"]["pageProps"]["pageInformation"]
            items = information["offers"]["main"]["items"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ToolError("KaufDA-Globus-Bilddaten haben ein unerwartetes Format") from exc
        if not isinstance(items, list):
            raise ToolError("KaufDA-Globus-Angebotsliste hat ein unerwartetes Format")

        result: list[Offer] = []
        for raw in items:
            if not isinstance(raw, dict) or clean_text(raw.get("type")).upper() != "OFFER":
                continue
            if clean_text(raw.get("publisherName")).upper() != "GLOBUS":
                continue
            prices = raw.get("prices") if isinstance(raw.get("prices"), dict) else {}
            price = parse_number(prices.get("mainPrice"))
            name = clean_text(raw.get("title"))
            if not name or price is None or price <= 0:
                continue
            images = raw.get("offerImages") if isinstance(raw.get("offerImages"), dict) else {}
            urls = images.get("url") if isinstance(images.get("url"), dict) else {}
            image_url = normalize_image_url(urls.get("normal") or urls.get("large"))
            parsed = urlsplit(image_url) if image_url else None
            folded = image_url.casefold()
            if (
                not image_url
                or is_rejected_image_url(image_url)
                or not parsed
                or parsed.hostname != "content-media.bonial.biz"
                or "seo-offer" not in folded
                or "seo-brochure" in folded
            ):
                continue
            brand = clean_brand(raw.get("brand"))
            display_name = name if not brand or brand.casefold() in name.casefold() else f"{brand} {name}"
            description = clean_text(raw.get("description"))
            pack = normalize_pack(f"{display_name} {description}")
            start, end = _local_date(raw.get("validFrom")), _local_date(raw.get("validUntil"))
            identifier = clean_text(raw.get("id")) or build_match_key(brand, name, pack, image_url)
            result.append(Offer(
                offer_id=f"kaufda-globus-image:{identifier}", retailer="Globus", category="Bildabgleich",
                name=display_name, brand=brand, description=description, price=price,
                base_price=None, base_unit="", pack_signature=pack,
                validity_label=format_validity(start, end),
                match_key=build_match_key(brand, name, pack, identifier), source_url=source_url,
                image_url=image_url, source_category="KaufDA Einzelangebot",
                valid_from=start.isoformat() if start else None,
                valid_until=end.isoformat() if end else None,
            ))
        return result


def _local_date(value: Any) -> Optional[date]:
    text = clean_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(BERLIN)
        return parsed.date()
    except ValueError:
        return None



def _viewer_prices(deals: Any) -> tuple[Optional[float], Optional[float]]:
    """(regulärer Preis, App-Preis) aus den Preisangaben eines Prospektangebots."""
    regular_values: set[float] = set()
    member_values: set[float] = set()
    reference_values: set[float] = set()
    for deal in deals if isinstance(deals, list) else []:
        if not isinstance(deal, dict):
            continue
        if deal.get("currencyCode") not in (None, "EUR"):
            continue
        price = parse_number(deal.get("min"))
        if price is None or price <= 0 or not isfinite(price):
            continue
        if deal.get("max") is not None and parse_number(deal.get("max")) != price:
            continue  # A price range is not a specific pack's payable price.
        conditions = " ".join(clean_text(value) for c in deal.get("conditions", []) if isinstance(c, dict) for value in c.values()).casefold()
        kind = clean_text(deal.get("type")).upper()
        member = bool(re.fullmatch(r"mit (?:der )?(?:[\wäöüß -]+ app|lidl plus|netto\+|kaufland card)", conditions.strip()))
        without = bool(re.fullmatch(r"\s*ohne (?:app|lidl plus)\s*", conditions))
        if kind in {"SALES_PRICE", "SPECIAL_PRICE"} and member and not without:
            member_values.add(price)
        elif kind in {"SALES_PRICE", "SPECIAL_PRICE"} and (not conditions or without or conditions.strip() in {"auch online", "auch online erhältlich"}):
            regular_values.add(price)
        elif kind == "REGULAR_PRICE" and not conditions:
            reference_values.add(price)
        # Other conditions (coupons, quantity thresholds, cashback) must not
        # silently turn into an unconditional price.
    regular = next(iter(regular_values)) if len(regular_values) == 1 else None
    app = next(iter(member_values)) if len(member_values) == 1 else None
    reference = next(iter(reference_values)) if len(reference_values) == 1 else None
    if len(regular_values) > 1:
        return None, None  # No product-specific association for conflicting cash prices.
    # A declared normal price can supply the without-membership price; an RRP cannot.
    return regular if regular is not None else reference if app is not None else None, app


def _product_deals(deals: Any, product: dict[str, Any], count: int) -> list[dict[str, Any]]:
    values = [deal for deal in deals if isinstance(deal, dict)] if isinstance(deals, list) else []
    if count == 1:
        return values

    def key(value: Any) -> str:
        return re.sub(r"[^\w]", "", clean_text(value).casefold())

    title, brand = key(product.get("name")), key(product.get("brandName"))
    matched = [deal for deal in values if key(deal.get("description")) in {title, brand + title}]
    if matched:
        return matched
    # Without an exact association, shared amounts must agree for each kind.
    for kind in {deal.get("type") for deal in values}:
        prices = {parse_number(deal.get("min")) for deal in values if deal.get("type") == kind}
        if len(prices) > 1:
            return []
    return values


class KaufdaRetailerSource:
    """KaufDA's public offer page of one retailer.

    Used as a fallback for a retailer whose own site cannot be read without a
    browser (Müller answers a plain request with a client challenge). The page
    lists the current highlighted offers as structured data; it is a partial
    view of the range, so it never replaces a first-party catalogue that worked.
    """

    BASE = "https://www.kaufda.de/Geschaefte/{slug}"
    VIEWER_API = "https://content-viewer-be.kaufda.de/v1/brochures/{brochure}/pages"
    # Legacy default location: does not establish regional applicability for other retailers.
    VIEWER_QUERY = {"partner": "kaufda_web", "lat": "51.16", "lng": "10.45"}
    MAX_RESPONSE = 3_000_000
    MAX_VIEWER_RESPONSE = 6_000_000

    def __init__(self, http: HttpClient, retailer: str, publisher_name: str, slug: str, use_viewer: bool = False) -> None:
        self.http = http
        self.retailer = retailer
        self.publisher_name = publisher_name
        self.slug = slug
        self.use_viewer = use_viewer

    @property
    def url(self) -> str:
        return self.BASE.format(slug=quote(self.slug, safe="-"))

    def load(self, target: Optional[date] = None) -> list[Offer]:
        payload = self.http.get_bytes(self.url, {"Accept": "text/html", "Accept-Language": "de-DE,de;q=0.9"})
        if len(payload) > self.MAX_RESPONSE:
            raise ToolError(f"KaufDA-{self.retailer}-Seite überschreitet das Größenlimit")
        text = payload.decode("utf-8", errors="replace")
        if self.use_viewer:
            # Das ganze Prospekt (deutlich mehr als die Hervorhebungen der Händlerseite); ein Fehler fällt auf die Seite zurück.
            try:
                viewer = self._viewer_offers(text, target)
            except (ToolError, ValueError, KeyError, TypeError):
                viewer = []
            if viewer:
                return viewer
        return self.parse(text, target)

    def load_regional(self, locality: str, target: Optional[date] = None, coordinates: tuple[float, float] | None = None) -> list[Offer]:
        """Supplement only a publisher-linked city brochure, never a national default.

        A city is not a branch/stock guarantee. Unknown cities and missing viewer
        data are explicit failures; the caller must retain its primary catalogue.
        """
        def city_key(value: str) -> str:
            return clean_text(value).casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")

        if not clean_text(locality):
            raise ToolError(f"KaufDA-{self.retailer}: Ort nicht bestätigt")
        payload = self.http.get_bytes(self.url, {"Accept": "text/html"})
        if len(payload) > self.MAX_RESPONSE:
            raise ToolError("KaufDA-Händlerseite überschreitet das Größenlimit")
        regional_url = ""
        for link in BeautifulSoup(payload, "html.parser").select("a[href]"):
            parsed = urlsplit(link["href"])
            parts = parsed.path.strip("/").split("/")
            if (parsed.scheme == "https" and parsed.hostname == "www.kaufda.de"
                    and len(parts) == 3 and city_key(parts[0]) == city_key(locality)
                    and parts[1].casefold() == self.slug.casefold()
                    and re.fullmatch(r"p-r\d+", parts[2])):
                regional_url = parsed.geturl()
                break
        if not regional_url:
            raise ToolError(f"KaufDA-{self.retailer}: kein verifizierter Ortslink für {clean_text(locality)}")
        page = self.http.get_bytes(regional_url, {"Accept": "text/html"})
        if len(page) > self.MAX_RESPONSE:
            raise ToolError("KaufDA-Ortsseite überschreitet das Größenlimit")
        text = page.decode("utf-8", errors="replace")
        if not self._brochure_ids(text):
            raise ToolError(f"KaufDA-{self.retailer}: kein regionaler Prospekt verfügbar")
        if coordinates is None:
            raise ToolError(f"KaufDA-{self.retailer}: Ortskoordinaten nicht bestätigt")
        return self._viewer_offers(text, target, regional_url, coordinates)

    def _brochure_ids(self, page: str, require_publisher: bool = False) -> list[str]:
        match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', page, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return []
        try:
            brochures = json.loads(html.unescape(match.group(1)))["props"]["pageProps"]["pageInformation"]["brochures"]["viewer"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return []
        ids = []
        for entry in brochures if isinstance(brochures, list) else []:
            publisher = entry.get("publisher") if isinstance(entry, dict) and isinstance(entry.get("publisher"), dict) else {}
            name = clean_text(publisher.get("name"))
            if isinstance(entry, dict) and re.fullmatch(r"\d{6,12}", str(entry.get("id", ""))) and ((not name and not require_publisher) or name.casefold() == self.publisher_name.casefold()):
                ids.append(str(entry["id"]))
        return ids[:2]

    def _viewer_offers(self, page: str, target: Optional[date], source_url: str = "", coordinates: tuple[float, float] | None = None) -> list[Offer]:
        offers: list[Offer] = []
        query = self.VIEWER_QUERY if coordinates is None else {"partner": "kaufda_web", "lat": str(coordinates[0]), "lng": str(coordinates[1])}
        for brochure in self._brochure_ids(page, require_publisher=bool(source_url)):
            url = self.VIEWER_API.format(brochure=brochure) + "?" + "&".join(f"{k}={v}" for k, v in query.items())
            payload = self.http.get_bytes(url, {"Accept": "application/json"})
            if len(payload) > self.MAX_VIEWER_RESPONSE:
                raise ToolError(f"KaufDA-Prospekt von {self.retailer} überschreitet das Größenlimit")
            offers.extend(self.parse_viewer(json.loads(payload.decode("utf-8", errors="replace")), brochure, target, source_url))
        return offers

    def parse_viewer(self, data: dict[str, Any], brochure: str, target: Optional[date] = None, source_url: str = "") -> list[Offer]:
        """Angebote aus den Seiten des Prospekts. Regulärer Preis = Preis „ohne App“; ein App-Preis steht nur in der Beschreibung."""
        pages = data.get("contents") if isinstance(data, dict) else None
        if not isinstance(pages, list):
            raise ToolError(f"KaufDA-Prospekt von {self.retailer} hat ein unerwartetes Format")
        result: list[Offer] = []
        seen: set[str] = set()
        for page in pages:
            for entry in page.get("offers", []) if isinstance(page, dict) else []:
                content = entry.get("content") if isinstance(entry, dict) else None
                if not isinstance(content, dict) or content.get("type") != "offer" or not content.get("products"):
                    continue
                identifier = clean_text(content.get("id"))
                if not identifier or identifier in seen:
                    continue
                profile = (content.get("publicationProfiles") or [{}])[0].get("validity", {})
                start, end = _local_date(profile.get("startDate")), _local_date(profile.get("endDate"))
                if target is not None and not offer_validity({"validityDates": [{"from": start.isoformat() if start else "", "to": end.isoformat() if end else ""}]}, target)[0]:
                    continue
                seen.add(identifier)
                products = content["products"]
                if not isinstance(products, list):
                    raise ToolError(f"KaufDA-{self.retailer}: Produktliste hat ein unerwartetes Format")
                for product_index, product in enumerate(products):
                    if not isinstance(product, dict):
                        raise ToolError(f"KaufDA-{self.retailer}: Produkt hat ein unerwartetes Format")
                    regular, app = _viewer_prices(_product_deals(content.get("deals"), product, len(products)))
                    product_identifier = identifier if len(products) == 1 else f"{identifier}:{product_index}"
                    title = clean_text(product.get("name"))
                    if not title or regular is None or regular <= 0:
                        continue
                    brand = clean_brand(product.get("brandName"))
                    name = title if not brand or brand.casefold() in title.casefold() else f"{brand} {title}"
                    description = clean_text(" ".join(clean_text(d.get("paragraph")) for d in product.get("description", []) if isinstance(d, dict)))
                    paths = product.get("categoryPaths")
                    leaf = clean_text(paths[-1].get("name")) if isinstance(paths, list) and paths and isinstance(paths[-1], dict) else ""
                    compact_title = re.sub(r"[^\w]", "", title.casefold())
                    compact_leaf = re.sub(r"[^\w]", "", leaf.casefold())
                    if compact_title and compact_leaf.startswith(compact_title) and compact_leaf != compact_title:
                        # Index only a published specific compound (Wildschwein ->
                        # Wildschweingulasch), not every broad breadcrumb/category.
                        description = clean_text(f"{description} · Quellkategorie: {leaf}")
                    if app is not None and app < regular:
                        label = "Lidl Plus" if self.retailer == "Lidl" else f"{self.retailer} App"
                        description = clean_text(f"{description} · mit der {label} {format(app, '.2f').replace('.', ',')} €")
                    pack = normalize_pack(f"{name} {description}")
                    images = product.get("images")
                    product_image = images[0].get("url") if isinstance(images, list) and images and isinstance(images[0], dict) else ""
                    image_url = normalize_image_url(product_image or content.get("image"))
                    if image_url and (is_rejected_image_url(image_url) or urlsplit(image_url).hostname != "content-media.bonial.biz"):
                        image_url = ""
                    decision = category_decision("", self.retailer, name, description, brand)
                    result.append(Offer(
                        offer_id=f"kaufda-{self.slug.casefold()}:{product_identifier}", retailer=self.retailer, category=decision.category,
                        name=name, brand=brand, description=description, price=regular,
                        benefits=parse_public_loyalty_prices(description, regular, self.retailer),
                        base_price=None, base_unit="", pack_signature=pack,
                        validity_label=format_validity(start, end),
                        match_key=build_match_key(brand, title, pack, product_identifier), source_url=source_url or self.url,
                        image_url=image_url, source_category=decision.source_category,
                        detected_category=decision.detected_category, category_conflict=decision.category_conflict,
                        valid_from=start.isoformat() if start else None,
                        valid_until=end.isoformat() if end else None,
                        coverage_note=f"Angebote aus dem Prospekt über KaufDA ({self.retailer}); regionale Abdeckung nicht bestätigt.",
                    ))
        return result

    def parse(self, page: str, target: Optional[date] = None) -> list[Offer]:
        match = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            page,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            raise ToolError(f"KaufDA lieferte keine strukturierten {self.retailer}-Angebote")
        try:
            payload = json.loads(html.unescape(match.group(1)))
            items = payload["props"]["pageProps"]["pageInformation"]["offers"]["main"]["items"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ToolError(f"KaufDA-{self.retailer}-Angebote haben ein unerwartetes Format") from exc
        if not isinstance(items, list):
            raise ToolError(f"KaufDA-{self.retailer}-Angebotsliste hat ein unerwartetes Format")

        result: list[Offer] = []
        for raw in items:
            if not isinstance(raw, dict) or clean_text(raw.get("type")).upper() != "OFFER":
                continue
            if clean_text(raw.get("publisherName")).casefold() != self.publisher_name.casefold():
                continue
            start, end = _local_date(raw.get("validFrom")), _local_date(raw.get("validUntil"))
            if target is not None and not offer_validity({"validityDates": [{"from": start.isoformat() if start else "", "to": end.isoformat() if end else ""}]}, target)[0]:
                continue
            prices = raw.get("prices") if isinstance(raw.get("prices"), dict) else {}
            price = parse_number(prices.get("mainPrice"))
            title = clean_text(raw.get("title"))
            if not title or price is None or price <= 0:
                continue
            brand = clean_brand(raw.get("brand"))
            name = title if not brand or brand.casefold() in title.casefold() else f"{brand} {title}"
            description = clean_text(raw.get("description"))
            pack = normalize_pack(f"{name} {description}")
            images = raw.get("offerImages") if isinstance(raw.get("offerImages"), dict) else {}
            urls = images.get("url") if isinstance(images.get("url"), dict) else {}
            image_url = normalize_image_url(urls.get("normal") or urls.get("large") or urls.get("thumbnail"))
            if image_url and (is_rejected_image_url(image_url) or urlsplit(image_url).hostname != "content-media.bonial.biz"):
                image_url = ""
            identifier = clean_text(raw.get("id")) or build_match_key(brand, title, pack, "")
            decision = category_decision("", self.retailer, name, description, brand)
            result.append(Offer(
                offer_id=f"kaufda-{self.slug.casefold()}:{identifier}", retailer=self.retailer, category=decision.category,
                name=name, brand=brand, description=description, price=price,
                base_price=None, base_unit="", pack_signature=pack,
                validity_label=format_validity(start, end),
                match_key=build_match_key(brand, title, pack, identifier), source_url=self.url,
                image_url=image_url, source_category=decision.source_category,
                detected_category=decision.detected_category, category_conflict=decision.category_conflict,
                valid_from=start.isoformat() if start else None,
                valid_until=end.isoformat() if end else None,
                coverage_note=f"Ausschnitt der Angebote über KaufDA ({self.retailer}); regionale Abdeckung nicht bestätigt.",
            ))
        return result
