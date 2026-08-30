from __future__ import annotations

import html
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterable, Optional
from urllib.parse import urlencode

from ..common import clean_text, find_marktguru_keys, first_regex_group
from ..config import MARKTGURU_HOME, MARKTGURU_SEARCH_API, SEARCH_TERMS
from ..http import HttpClient
from ..models import ToolError

class MarktguruClient:
    def __init__(self, http: HttpClient, page_size: int, max_workers: int) -> None:
        self.http = http
        self.page_size = max(1, min(page_size, 1000))
        self.max_workers = max(1, max_workers)
        self._credentials: Optional[tuple[str, str]] = None
        self._credentials_lock = threading.Lock()

    def _headers(self) -> dict[str, str]:
        api_key, client_key = self._get_credentials()
        return {
            "Accept": "application/json",
            "x-apikey": api_key,
            "x-clientkey": client_key,
        }

    def load_offers(self, postal_code: str) -> tuple[list[dict[str, Any]], list[str]]:
        """Load the broad regional offer set used as the primary catalogue.

        The API search parameter is a real search query. An empty ``q`` is not
        treated as a reliable catalogue endpoint, so the proven term-based
        search is intentionally retained.
        """
        failures: list[str] = []
        for attempt in range(2):
            try:
                return self._load_once(postal_code)
            except Exception as exc:
                failures.append(f"Versuch {attempt + 1}: {type(exc).__name__}: {exc}")
                self._clear_credentials()
        raise ToolError("Marktguru blieb nach erneutem Abruf ohne Daten: " + " | ".join(failures))

    def _load_once(self, postal_code: str) -> tuple[list[dict[str, Any]], list[str]]:
        headers = self._headers()
        collected: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._fetch_query_pages, postal_code, term, headers): term
                for term in SEARCH_TERMS
            }
            for future in as_completed(futures):
                term = futures[future]
                try:
                    offers = future.result()
                except Exception as exc:
                    errors.append(f"{term}: {type(exc).__name__}: {exc}")
                    continue
                self._merge_unique(collected, offers)

        if not collected:
            details = f" ({', '.join(errors[:6])})" if errors else ""
            raise ToolError(f"Keine regionalen Angebotsdaten empfangen{details}")
        return list(collected.values()), errors

    def load_retailer_queries(
        self,
        postal_code: str,
        retailer_names: Iterable[str],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Fill retailers missing from the broad regional search.

        ``q`` is a search query rather than a dedicated retailer endpoint, so
        these results are never treated as a replacement for a retailer that
        already has offers in the broad catalogue.
        """
        terms = [clean_text(name) for name in retailer_names if clean_text(name)]
        terms = list(dict.fromkeys(terms))
        if not terms:
            return [], []

        headers = self._headers()
        collected: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(terms))) as executor:
            futures = {
                executor.submit(self._fetch_query_pages, postal_code, term, headers): term
                for term in terms
            }
            for future in as_completed(futures):
                term = futures[future]
                try:
                    offers = future.result()
                except Exception as exc:
                    errors.append(f"Marktguru Händlerabfrage {term}: {type(exc).__name__}: {exc}")
                    continue
                self._merge_unique(collected, offers)
        return list(collected.values()), errors

    @staticmethod
    def _merge_unique(target: dict[str, dict[str, Any]], offers: Iterable[dict[str, Any]]) -> int:
        added = 0
        for offer in offers:
            key = str(offer.get("id") or json.dumps(offer, sort_keys=True, ensure_ascii=False))
            if key in target:
                continue
            target[key] = offer
            added += 1
        return added

    def _fetch_page(
        self,
        postal_code: str,
        query_text: str,
        offset: int,
        headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        query = urlencode(
            {
                "as": "web",
                "limit": self.page_size,
                "offset": max(0, int(offset)),
                "q": query_text,
                "zipCode": postal_code,
            }
        )
        payload = self.http.get_json(f"{MARKTGURU_SEARCH_API}?{query}", headers)
        results = payload.get("results")
        return [item for item in results if isinstance(item, dict)] if isinstance(results, list) else []

    def _fetch_query_pages(
        self,
        postal_code: str,
        query_text: str,
        headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        collected: dict[str, dict[str, Any]] = {}
        offset = 0
        for _ in range(50):
            page = self._fetch_page(postal_code, query_text, offset, headers)
            if not page:
                break
            added = self._merge_unique(collected, page)
            if len(page) < self.page_size or added == 0:
                break
            offset += len(page)
        return list(collected.values())

    def _clear_credentials(self) -> None:
        with self._credentials_lock:
            self._credentials = None

    def _get_credentials(self) -> tuple[str, str]:
        with self._credentials_lock:
            if self._credentials is None:
                self._credentials = self._read_credentials()
            return self._credentials

    def _read_credentials(self) -> tuple[str, str]:
        raw = html.unescape(self.http.get_bytes(MARKTGURU_HOME).decode("utf-8", errors="replace"))
        for content in re.findall(
            r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            try:
                api_key, client_key = find_marktguru_keys(json.loads(content))
            except (json.JSONDecodeError, TypeError):
                continue
            if api_key and client_key:
                return api_key, client_key

        api_key = first_regex_group(
            raw,
            (
                r'["\'](?:x_)?apiKey["\']\s*:\s*["\']([^"\']+)',
                r'["\']x_apikey["\']\s*:\s*["\']([^"\']+)',
            ),
        )
        client_key = first_regex_group(
            raw,
            (
                r'["\'](?:x_)?clientKey["\']\s*:\s*["\']([^"\']+)',
                r'["\']x_clientkey["\']\s*:\s*["\']([^"\']+)',
            ),
        )
        if not api_key or not client_key:
            raise ToolError("Marktguru-Zugangsdaten konnten nicht automatisch gelesen werden")
        return api_key, client_key
