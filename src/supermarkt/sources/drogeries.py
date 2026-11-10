from __future__ import annotations

import re
import subprocess
import tempfile
import threading
import time
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from typing import Callable
from urllib.parse import parse_qs, urlsplit, urlencode, urljoin

from ..common import (
    build_match_key,
    clean_text,
    normalize_pack,
    parse_base_price_text,
    parse_number,
)
from ..http import HttpClient
from ..models import Offer, ToolError, PartialOffers
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
        with tempfile.TemporaryDirectory(prefix="korbunio-rossmann-") as profile:
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
    # /c/online-angebote/ now redirects (HTTP 308) to the flyer page, which lists no products. The "Aktionen" pages of the
    # main departments still render priced product tiles in plain HTML.
    OFFERS_URLS = (
        "https://www.mueller.de/c/drogerie/aktionen/",
        "https://www.mueller.de/c/haushalt/aktionen/",
        "https://www.mueller.de/c/schreibwaren/aktionen/",
        "https://www.mueller.de/c/spielwaren/aktionen/",
        "https://www.mueller.de/c/naturshop/aktionen/",
        "https://www.mueller.de/c/multi-media/aktionen/",
        "https://www.mueller.de/c/struempfe/aktionen/",
        "https://www.mueller.de/c/handarbeit/aktionen/",
        "https://www.mueller.de/c/tiershop/aktionen/",
    )
    OFFERS_URL = OFFERS_URLS[0]
    MAX_PAGES_PER_DEPARTMENT = 200
    MAX_RESPONSE = 4_000_000
    CHALLENGE_MESSAGE = (
        "Müller verlangt eine Browser-Prüfung (Client Challenge) und ist ohne Browser nicht lesbar; "
        "die Angebote kommen dann von KaufDA."
    )

    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self.last_market_url = "https://www.mueller.de/storefinder/"
        self.last_market_label = "Müller"
        self._catalogue = PartialOffers()
        self._catalogue_at = 0.0
        self._catalogue_lock = threading.Lock()

    def load(self, postal_code: str) -> list[Offer]:
        # The online catalogue is shared by postal areas; do not fetch all
        # department pages again for every regional comparison.
        with self._catalogue_lock:
            ttl = 60 if self._catalogue.note else 30 * 60
            if self._catalogue and time.monotonic() - self._catalogue_at < ttl:
                return PartialOffers(self._catalogue, self._catalogue.note)
            catalogue = self._load_catalogue(postal_code)
            self._catalogue = catalogue
            self._catalogue_at = time.monotonic()
            return PartialOffers(catalogue, catalogue.note)

    def _load_catalogue(self, postal_code: str) -> PartialOffers:
        del postal_code
        # Two bounded requests at a time, shared by all postal areas through
        # load()'s catalogue lock/cache. Never spawn one request per page.
        result: list[Offer] = []
        seen: set[str] = set()
        failures = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            for part in pool.map(self._load_department, self.OFFERS_URLS):
                if part.note:
                    failures.append(part.note)
                for offer in part:
                    if offer.offer_id not in seen:
                        seen.add(offer.offer_id)
                        result.append(offer)
        if not result:
            if any(code in failure for failure in failures for code in ("HTTP 403", "HTTP 429")):
                raise ToolError(self.CHALLENGE_MESSAGE)
            raise ToolError(" | ".join(failures) or "Müller lieferte keine lesbaren Online-Angebote")
        return PartialOffers(result, " | ".join(failures))

    def _load_department(self, department: str) -> PartialOffers:
        from bs4 import BeautifulSoup
        result: list[Offer] = []
        seen: set[str] = set()
        failures: list[ToolError] = []
        url = department
        department_ids: set[str] = set()
        for number in range(1, self.MAX_PAGES_PER_DEPARTMENT + 1):
            try:
                payload = self.http.get_bytes(url, {"Accept": "text/html"})
                if len(payload) > self.MAX_RESPONSE:
                    raise ToolError("Müller-Antwort überschreitet das Größenlimit")
                soup = BeautifulSoup(payload, "html.parser")
                parsed = self._parse(BeautifulSoup, url, payload, page=soup)
                page_ids = self._listing_ids(soup)
                if not page_ids:
                    visible = soup.get_text(" ", strip=True).casefold()
                    title = soup.title.get_text().casefold() if soup.title else ""
                    blocked = any(word in visible for word in ("verify you are human", "client challenge", "access denied", "captcha"))
                    # One retry for a transient empty listing, never for an access challenge.
                    if "aktion" in title and not blocked:
                        payload = self.http.get_bytes(url, {"Accept": "text/html"})
                        if len(payload) > self.MAX_RESPONSE:
                            raise ToolError("Müller-Antwort überschreitet das Größenlimit")
                        soup = BeautifulSoup(payload, "html.parser")
                        parsed = self._parse(BeautifulSoup, url, payload, page=soup)
                        page_ids = self._listing_ids(soup)
                    if not page_ids:
                        raise ToolError("Müller lieferte keine lesbaren Produktkarten")
                if page_ids <= department_ids:
                    raise ToolError("Müller wiederholt eine Seite; Katalog unvollständig")
                department_ids.update(page_ids)
                for offer in parsed:
                    if offer.offer_id not in seen:
                        seen.add(offer.offer_id)
                        result.append(offer)
                pages = {}
                for link in soup.select("a[href]"):
                    candidate = urlsplit(urljoin(department, link["href"]))
                    query = parse_qs(candidate.query)
                    if (candidate.scheme == "https" and candidate.hostname == "www.mueller.de"
                            and candidate.path == urlsplit(department).path and set(query) == {"page"}
                            and len(query["page"]) == 1 and query["page"][0].isdigit()):
                        pages[int(query["page"][0])] = candidate.geturl()
                if number + 1 not in pages:
                    if any(value > number for value in pages):
                        raise ToolError("Müller Pagination überspringt eine Seite; Katalog unvollständig")
                    break
                if number == self.MAX_PAGES_PER_DEPARTMENT:
                    raise ToolError("Müller Seitenlimit erreicht; Katalog unvollständig")
                url = pages[number + 1]
            except ToolError as exc:
                failures.append(ToolError(f"{url}: {exc}"))
                break
        return PartialOffers(result, " | ".join(map(str, failures)))

    @staticmethod
    def _listing_ids(page) -> set[str]:
        # Pagination identity comes from all readable products, not only Sale.
        # A page of regular assortment must not terminate the offer scan.
        ids = set()
        for card in page.select("article"):
            link = card.select_one("a[data-product-id][href]")
            if (link and card.select_one("[class*='product-tile__product-name']")
                    and card.select_one('[data-testid="plp-currentPrice-label"]')):
                ids.add(clean_text(link.get("data-product-id")))
        return ids - {""}

    def _parse(self, BeautifulSoup, url: str, payload: bytes, page=None) -> list[Offer]:
        page = page if page is not None else BeautifulSoup(payload.decode("utf-8", errors="replace"), "html.parser")
        result: list[Offer] = []
        for index, card in enumerate(page.select("article"), 1):
            # Aktion category pages also contain regular assortment, "Neu",
            # own brands and multipacks. Neither category nor UVP comparison
            # alone proves an offer. Require the retailer's explicit Sale badge.
            badges = {clean_text(n.get_text(" ", strip=True)).casefold()
                for n in card.select("[class*='product-badges__text']")}
            if "sale" not in badges:
                continue
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
                price, base_price, base_unit, pack, "Online-Sale (ohne veröffentlichten Zeitraum)",
                build_match_key("", name, pack, offer_id), url,
                image_url=urljoin(url, clean_text(image.get("src"))) if image else "",
                product_url=urljoin(url, clean_text(link.get("href"))),
                retailer_url=self.last_market_url,
                coverage_note="Von Müller als Sale markierter Online-Artikel; keine vollständige Wochenprospektabdeckung; Filialpreis und Filialbestand können abweichen",
            ))
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
        products = []
        seen_pages: set[str] = set()
        for page in range(4):
            query = urlencode({"query": "ausverkauf", "pageSize": 500, "currentPage": page})
            payload = self.http.get_json(f"{self.SEARCH_API}?{query}",
                {"Accept": "application/json", "Referer": self.OFFERS_URL})
            batch = payload.get("products")
            if not isinstance(batch, list) or any(not isinstance(product, dict) for product in batch):
                raise ToolError("dm lieferte einen unerwarteten Angebotskatalog")
            pages = payload.get("totalPages")
            if pages is not None and (not isinstance(pages, int) or isinstance(pages, bool) or not 1 <= pages <= 4):
                raise ToolError("dm Seitenzahl unbekannt oder Seitenlimit überschritten")
            import json
            fingerprint = json.dumps(batch, sort_keys=True, ensure_ascii=False)
            if batch and fingerprint in seen_pages:
                raise ToolError("dm wiederholt eine Seite; Katalog unvollständig")
            if batch:
                seen_pages.add(fingerprint)
            if not batch and pages and page < pages - 1:
                raise ToolError("dm Folgeseite fehlt; Katalog unvollständig")
            products.extend(batch)
            if len(products) > 2000:
                raise ToolError("dm Katalog überschreitet das Größenlimit")
            if (pages is not None and page + 1 >= pages) or (pages is None and len(batch) < 500):
                break
        else:
            raise ToolError("dm Seitenlimit erreicht; Katalog unvollständig")
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
