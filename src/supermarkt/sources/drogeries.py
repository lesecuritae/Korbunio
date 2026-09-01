from __future__ import annotations

import re
import subprocess
import tempfile
import threading
import time
from datetime import date
from typing import Callable
from urllib.parse import urlencode, urljoin

from ..common import (
    build_match_key,
    clean_text,
    normalize_pack,
    parse_base_price_text,
    parse_number,
)
from ..http import HttpClient
from ..models import Offer, ToolError
from .browser import chromium_command


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


class OfficialRossmannSource:
    OFFERS_URL = "https://www.rossmann.de/de/angebote/m/angebote/"

    def __init__(self, renderer: Callable[[str], str] | None = None, timeout_seconds: int = 25) -> None:
        self.timeout_seconds = timeout_seconds
        self.renderer = renderer or self._render
        self.last_market_url = "https://www.rossmann.de/de/filialen/index.html"
        self.last_market_label = "Rossmann"

    def _render(self, url: str) -> str:
        with tempfile.TemporaryDirectory(prefix="korbklar-rossmann-") as profile:
            try:
                result = subprocess.run(  # noqa: S603 - fixed browser executable and arguments
                    [
                        chromium_command(), "--headless=new", "--no-sandbox", "--disable-gpu",
                        "--disable-software-rasterizer", "--disable-crashpad-for-testing", "--single-process",
                        "--disable-dev-shm-usage", "--virtual-time-budget=12000",
                        f"--user-data-dir={profile}", "--dump-dom", url,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=max(20, self.timeout_seconds + 15),
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ToolError(f"Rossmann-Browserabruf fehlgeschlagen: {exc}") from exc
        # Alpine Chromium can terminate its browser process with a non-zero
        # status after --dump-dom has already produced the complete document.
        # Validate the document itself instead of discarding that usable output.
        if len(result.stdout) < 20_000:
            raise ToolError("Rossmann lieferte keine vollständig gerenderte Angebotsseite")
        if len(result.stdout.encode("utf-8")) > 5_000_000:
            raise ToolError("Rossmann-Antwort überschreitet das Größenlimit")
        return result.stdout

    @staticmethod
    def _validity(text: str) -> tuple[date | None, date | None]:
        match = re.search(
            r"Gültig\s+ab\s+\w+\s*:\s*(\d{2})\.(\d{2})\.\s*-\s*(\d{2})\.(\d{2})\.(\d{4})",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None, None
        try:
            return date(int(match[5]), int(match[2]), int(match[1])), date(int(match[5]), int(match[4]), int(match[3]))
        except ValueError:
            return None, None

    def load(self, postal_code: str) -> list[Offer]:
        del postal_code
        try:
            from bs4 import BeautifulSoup
        except Exception as exc:  # pragma: no cover
            raise ToolError(f"Rossmann benötigt BeautifulSoup: {exc}") from exc
        page = BeautifulSoup(self.renderer(self.OFFERS_URL), "html.parser")
        start, end = self._validity(page.get_text(" ", strip=True))
        result: list[Offer] = []
        for index, card in enumerate(page.select('[data-testid="product-card"]'), 1):
            text = clean_text(card.get_text(" ", strip=True))
            if "Aus der Werbung" not in text:
                continue
            link = card.select_one('a[href*="/p/"]')
            image = card.select_one("img[src]")
            name_node = card.select_one('[data-testid="product-brandAndName"]')
            name = clean_text(name_node.get_text(" ", strip=True) if name_node else "")
            if not name:
                name = clean_text(image.get("alt") if image else "")
            if not name and link:
                name = clean_text(link.get_text(" ", strip=True))
            price_node = card.select_one('[data-testid="product-price"]') or card.select_one('[aria-label*="preis" i]')
            price_text = clean_text(price_node.get_text(" ", strip=True) if price_node else "")
            price_match = re.search(r"(\d+[,.]\d{2})\s*€", price_text or text)
            price = parse_number(price_match[1]) if price_match else None
            if not name or price is None or price <= 0:
                continue
            details_node = card.select_one('[data-testid="product-baseprice"]')
            details = clean_text(details_node.get_text(" ", strip=True) if details_node else "")
            if not details:
                detail_match = re.search(r"(\d+(?:[,.]\d+)?\s*(?:ml|l|g|kg|Stk\.?|Stück)[^€]{0,20}\([^)]*€[^)]*\))", text, re.I)
                details = clean_text(detail_match[1]) if detail_match else text
            base_price, base_unit = parse_base_price_text(details)
            pack = normalize_pack(details)
            offer_id = f"rossmann:{index}:{_slug(name)}"
            product_url = urljoin(self.OFFERS_URL, clean_text(link.get("href")) if link else "")
            result.append(Offer(
                offer_id, "Rossmann", "Drogerie", name, "", details, price,
                base_price, base_unit, pack, "Aktuelle Werbung" if not start else f"{start:%d.%m.}–{end:%d.%m.%Y}",
                build_match_key("", name, pack, offer_id), self.OFFERS_URL,
                image_url=urljoin(self.OFFERS_URL, clean_text(image.get("src"))) if image else "",
                product_url=product_url, retailer_url=self.last_market_url,
                coverage_note="Offizielle Rossmann-Werbung; lokale Verfügbarkeit vorbehalten",
                valid_from=start.isoformat() if start else None,
                valid_until=end.isoformat() if end else None,
            ))
        if not result:
            raise ToolError("Rossmann lieferte keine lesbaren Werbeangebote")
        return result


class OfficialMuellerSource:
    OFFERS_URL = "https://www.mueller.de/c/online-angebote/"
    MAX_RESPONSE = 4_000_000

    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self.last_market_url = "https://www.mueller.de/storefinder/"
        self.last_market_label = "Müller"

    def load(self, postal_code: str) -> list[Offer]:
        del postal_code
        try:
            from bs4 import BeautifulSoup
        except Exception as exc:  # pragma: no cover
            raise ToolError(f"Müller benötigt BeautifulSoup: {exc}") from exc
        payload = self.http.get_bytes(self.OFFERS_URL, {"Accept": "text/html"})
        if len(payload) > self.MAX_RESPONSE:
            raise ToolError("Müller-Antwort überschreitet das Größenlimit")
        page = BeautifulSoup(payload.decode("utf-8", errors="replace"), "html.parser")
        result: list[Offer] = []
        for index, card in enumerate(page.select("article"), 1):
            name_node = card.select_one("[class*='product-tile__product-name']")
            price_node = card.select_one('[data-testid="plp-currentPrice-label"]')
            link = card.select_one("a[data-product-id][href]") or card.select_one('a[href*="/p/"]')
            name = clean_text(name_node.get_text(" ", strip=True) if name_node else "")
            price = parse_number(clean_text(price_node.get_text(" ", strip=True) if price_node else ""))
            if not name or price is None or price <= 0 or link is None:
                continue
            capacity = card.select_one("[class*='product-price__capacity']")
            base = card.select_one("[class*='product-price__base-price']")
            details = clean_text(capacity.get_text(" ", strip=True) if capacity else "")
            base_text = clean_text(base.get_text(" ", strip=True) if base else "")
            base_price, base_unit = parse_base_price_text(re.sub(r"/\s*1\s+(?=[A-Za-z])", "/ ", base_text))
            pack = normalize_pack(f"{name} {details}")
            product_id = clean_text(link.get("data-product-id")) or str(index)
            offer_id = f"mueller:{product_id}"
            image = card.select_one("img[src*='products']") or card.select_one("img[src]")
            result.append(Offer(
                offer_id, "Müller", "Drogerie und Haushalt", name, "", details,
                price, base_price, base_unit, pack, "Aktuelles Online-Angebot",
                build_match_key("", name, pack, offer_id), self.OFFERS_URL,
                image_url=urljoin(self.OFFERS_URL, clean_text(image.get("src"))) if image else "",
                product_url=urljoin(self.OFFERS_URL, clean_text(link.get("href"))),
                retailer_url=self.last_market_url,
                coverage_note="Offizielles Müller-Online-Angebot; Filialpreis und Filialbestand können abweichen",
            ))
        if not result:
            raise ToolError("Müller lieferte keine lesbaren Online-Angebote")
        return result


class OfficialDmSource:
    """Public dm clearance catalogue.

    dm explicitly does not publish changing weekly promotions. Its official
    clearance catalogue is therefore the only public offer source we expose.
    Availability is deliberately not presented as branch-specific.
    """

    OFFERS_URL = "https://www.dm.de/ausverkauf"
    SEARCH_API = "https://product-search.services.dmtech.com/de/search"

    def __init__(self, http: HttpClient, cache_ttl_seconds: int = 30 * 60) -> None:
        self.http = http
        self.cache_ttl_seconds = max(60, cache_ttl_seconds)
        self.last_market_url = "https://www.dm.de/store/"
        self.last_market_label = "dm (Ausverkauf online)"
        self._cached: tuple[Offer, ...] = ()
        self._cached_at = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _category(values: object) -> str:
        categories = " ".join(clean_text(value) for value in values) if isinstance(values, list) else clean_text(values)
        folded = categories.casefold()
        mappings = (
            ("Baby & Kind", ("baby", "kind", "windel")),
            ("Tierbedarf", ("tier", "hund", "katze")),
            ("Haushalt & Reinigung", ("haushalt", "reinig", "wasch", "spül", "papier", "seifenspender")),
            ("Snacks", ("bonbon", "fruchtgummi", "schokolade", "riegel", "snack")),
            ("Frühstück & Brotaufstriche", ("brotaufstrich", "marmelade", "müsli")),
            ("Getränke", ("kaffee", "tee", "getränk", "saft")),
            ("Vorräte & Grundnahrungsmittel", ("saat", "körner", "lebensmittel", "nahrung")),
            ("Wohnen, Freizeit & Non-Food", ("kleidung", "textil", "deko", "kerze", "accessoire", "spiel", "usb", "kabel", "strumpf", "socke")),
            ("Drogerie & Körperpflege", ("pflege", "kosmetik", "make-up", "nägel", "nagel", "haar", "parfum", "deo", "hygiene", "creme", "lip", "gesund", "vitamin", "mineral", "rasier", "duft")),
        )
        return next((category for category, terms in mappings if any(term in folded for term in terms)), "Drogerie & Körperpflege")

    @staticmethod
    def _price_value(value: object) -> float | None:
        if not isinstance(value, dict):
            return None
        current = value.get("price")
        if not isinstance(current, dict) or not isinstance(current.get("current"), dict):
            return None
        return parse_number(current["current"].get("value"))

    def _fetch(self) -> list[Offer]:
        query = urlencode({"query": "ausverkauf", "pageSize": 500, "currentPage": 0})
        payload = self.http.get_json(
            f"{self.SEARCH_API}?{query}",
            {"Accept": "application/json", "Referer": self.OFFERS_URL},
        )
        products = payload.get("products")
        if not isinstance(products, list) or len(products) > 2_000:
            raise ToolError("dm lieferte einen unerwarteten Angebotskatalog")
        result: list[Offer] = []
        for product in products:
            if not isinstance(product, dict) or not isinstance(product.get("tileData"), dict):
                continue
            tile = product["tileData"]
            eyecatchers = tile.get("eyecatchers")
            if not isinstance(eyecatchers, list) or not any(
                isinstance(item, dict) and "ausverkauf" in clean_text(item.get("alt")).casefold()
                for item in eyecatchers
            ):
                continue
            title_data = tile.get("title") if isinstance(tile.get("title"), dict) else {}
            brand_data = tile.get("brand") if isinstance(tile.get("brand"), dict) else {}
            name = clean_text(product.get("title")) or clean_text(title_data.get("tileHeadline"))
            brand = clean_text(product.get("brandName")) or clean_text(brand_data.get("name"))
            price = self._price_value(tile.get("price"))
            if not name or price is None or price <= 0:
                continue
            price_data = tile.get("price") if isinstance(tile.get("price"), dict) else {}
            infos = price_data.get("tileInfos") if isinstance(price_data.get("tileInfos"), list) else []
            details = " · ".join(clean_text(value) for value in infos if clean_text(value))
            base_price, base_unit = parse_base_price_text(details)
            previous = price_data.get("price", {}).get("previous") if isinstance(price_data.get("price"), dict) else None
            previous_text = clean_text(previous.get("value")) if isinstance(previous, dict) else ""
            description = f"Vorher {previous_text}" if previous_text else "dm-Ausverkauf"
            images = tile.get("images") if isinstance(tile.get("images"), list) else []
            image_url = next(
                (clean_text(image.get("tileSrc")) for image in images if isinstance(image, dict) and clean_text(image.get("tileSrc"))),
                "",
            )
            tracking = tile.get("trackingData") if isinstance(tile.get("trackingData"), dict) else {}
            category = self._category(tracking.get("categories"))
            product_id = clean_text(tile.get("dan")) or clean_text(product.get("dan")) or clean_text(tile.get("gtin"))
            product_path = clean_text(tile.get("self"))
            offer_id = f"dm:{product_id or _slug(name)}"
            pack = normalize_pack(f"{name} {details}")
            result.append(Offer(
                offer_id=offer_id,
                retailer="dm",
                category=category,
                name=name,
                brand=brand,
                description=description,
                price=price,
                base_price=base_price,
                base_unit=base_unit,
                pack_signature=pack,
                validity_label="Aktueller Ausverkauf",
                match_key=build_match_key(brand, name, pack, offer_id),
                source_url=self.OFFERS_URL,
                image_url=image_url,
                product_url=urljoin("https://www.dm.de/", product_path),
                retailer_url=self.last_market_url,
                coverage_note="Offizieller dm-Ausverkauf; Onlinepreis, lokale Filialverfügbarkeit unbekannt",
            ))
        if not result:
            raise ToolError("dm lieferte keine lesbaren Ausverkaufsangebote")
        return result

    def load(self, postal_code: str) -> list[Offer]:
        del postal_code
        now = time.monotonic()
        with self._lock:
            if self._cached and now - self._cached_at < self.cache_ttl_seconds:
                return list(self._cached)
            offers = tuple(self._fetch())
            self._cached = offers
            self._cached_at = now
            return list(offers)
