from __future__ import annotations

import re
import subprocess
import tempfile
from datetime import date
from typing import Callable
from urllib.parse import urljoin

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
