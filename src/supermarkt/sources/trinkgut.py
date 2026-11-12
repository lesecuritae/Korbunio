from __future__ import annotations

from ..request_state import RequestState

import json
import re
import threading
import time
import unicodedata
from dataclasses import replace
from datetime import date, datetime
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

from ..common import (
    build_match_key,
    clean_text,
    deduplicate_offers,
    format_validity,
    normalize_offer_week,
    normalize_pack,
    offer_reference_date,
    offer_week_reference,
    parse_base_price_text,
    parse_deposit_text,
    parse_number,
    today_berlin,
)
from ..http import PostalCodeLocator, curl_cffi_session
from ..images import is_rejected_image_url, normalize_image_url
from ..models import Offer, ToolError, NoLocalMarketError, NoLocalMarketOffers, PartialOffers


class OfficialTrinkgutSource:
    scope_note = RequestState("")
    last_market_label = RequestState("")
    last_market_url = RequestState("")

    BASE = "https://www.trinkgut.de"
    MARKETS_URL = BASE + "/marktsuche"
    OFFERS_URL = BASE + "/angebote/"

    def __init__(
        self,
        locator: PostalCodeLocator,
        timeout_seconds: int = 45,
        *,
        cache_dir: Path | None = None,
        store_cache_ttl_seconds: int = 86400,
        markets_cache_ttl_seconds: int = 86400,
        max_distance_km: float = 40.0,
        deposit_workers: int = 4,
        deposit_cache_ttl_seconds: int = 86400,
    ) -> None:
        self.locator = locator
        self.max_distance_km = max(5.0, min(float(max_distance_km), 300.0))
        self.deposit_workers = max(1, min(int(deposit_workers), 12))
        self.deposit_cache_ttl_seconds = max(300, min(int(deposit_cache_ttl_seconds), 7 * 86400))
        self._deposit_cache: dict[str, tuple[float, float | None]] = {}
        self._coordinate_cache: dict[str, tuple[float, float]] = {}
        self.timeout_seconds = max(10, min(int(timeout_seconds), 90))
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else None
        self.store_cache_ttl_seconds = max(300, min(int(store_cache_ttl_seconds), 7 * 86400))
        self.markets_cache_ttl_seconds = max(300, min(int(markets_cache_ttl_seconds), 7 * 86400))
        self._cache_lock = threading.RLock()
        self._all_markets_mem: list[dict[str, Any]] | None = None
        self._all_markets_loaded_at: float = 0.0

        self.last_market_id = ""
        self.last_market_label = ""
        self.last_market_url = ""
        self.last_discovery = ""
        self.last_distance_km: float | None = None
        self.last_current_count = 0
        self.last_unknown_count = 0

        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _store_cache_path(self) -> Path | None:
        return self.cache_dir / "stores.json" if self.cache_dir is not None else None

    @property
    def _markets_cache_path(self) -> Path | None:
        return self.cache_dir / "markets.json" if self.cache_dir is not None else None

    def _read_store_map(self) -> dict[str, dict[str, Any]]:
        path = self._store_cache_path
        if path is None or not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(value, dict):
            return {}
        return {
            postal: item
            for postal, item in value.items()
            if isinstance(postal, str) and isinstance(item, dict)
        }

    def _write_store_map(self, value: dict[str, dict[str, Any]]) -> None:
        path = self._store_cache_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)

    def _cleanup_store_cache(self, now: float | None = None) -> dict[str, dict[str, Any]]:
        if self.cache_dir is None:
            return {}
        current = time.time() if now is None else float(now)
        with self._cache_lock:
            mapping = self._read_store_map()
            changed = False
            for postal, item in list(mapping.items()):
                try:
                    expires_at = float(item.get("expires_at", 0))
                except (TypeError, ValueError):
                    expires_at = 0
                if expires_at > current:
                    continue
                mapping.pop(postal, None)
                changed = True
            if changed:
                self._write_store_map(mapping)
            return mapping

    def _cached_market(self, postal_code: str) -> tuple[str, str, str, float | None] | None:
        code = clean_text(postal_code)
        mapping = self._cleanup_store_cache()
        item = mapping.get(code)
        if not isinstance(item, dict):
            return None
        market_id = clean_text(item.get("market_id", ""))
        market_url = clean_text(item.get("market_url", ""))
        label = clean_text(item.get("label", ""))
        dist = item.get("distance_km")
        distance_km = float(dist) if dist is not None else None
        if not market_id or not market_url:
            self._drop_cached_market(code)
            return None
        self.last_discovery = "24h-Marktcache"
        self.last_distance_km = distance_km
        return market_id, market_url, label, distance_km

    def _cache_market(
        self,
        postal_code: str,
        market_id: str,
        market_url: str,
        label: str,
        distance_km: float | None = None,
    ) -> None:
        if self.cache_dir is None:
            return
        code = clean_text(postal_code)
        if not code or not market_id or not market_url:
            return
        now = time.time()
        with self._cache_lock:
            mapping = self._cleanup_store_cache(now)
            mapping[code] = {
                "market_id": clean_text(market_id),
                "market_url": clean_text(market_url),
                "label": clean_text(label),
                "distance_km": distance_km,
                "created_at": now,
                "expires_at": now + self.store_cache_ttl_seconds,
            }
            self._write_store_map(mapping)

    def _drop_cached_market(self, postal_code: str) -> None:
        if self.cache_dir is None:
            return
        code = clean_text(postal_code)
        with self._cache_lock:
            mapping = self._read_store_map()
            if mapping.pop(code, None) is not None:
                self._write_store_map(mapping)

    ALLOWED_HOSTS = frozenset({"www.trinkgut.de", "trinkgut.de"})

    @classmethod
    def _is_trinkgut_url(cls, value: str) -> bool:
        """Only https URLs on trinkgut's own host may ever be requested."""
        try:
            parsed = urlparse(value)
        except ValueError:
            return False
        return parsed.scheme == "https" and (parsed.hostname or "").lower() in cls.ALLOWED_HOSTS

    @classmethod
    def _safe_url(cls, value: str, fallback: str) -> str:
        return value if value and cls._is_trinkgut_url(value) else fallback

    def _session(self):
        return curl_cffi_session("trinkgut")

    @staticmethod
    def _slug(value: str) -> str:
        raw = unicodedata.normalize("NFKD", clean_text(value).casefold())
        raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
        return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")

    @staticmethod
    def _parse_truncated_deposit(description: str) -> float | None:
        """Extract deposit from server-truncated card descriptions.

        trinkgut truncates descriptions to a fixed character width in the
        offers listing. Deposit amounts are cut as e.g. 'zzgl. \u20ac 3.10 Pf...'
        or 'zzgl. \u20ac 0.25 Pfand...' – the numeric value is always visible but
        the word 'Pfand' may be absent or incomplete. This fallback covers those
        cases without requiring additional HTTP requests to detail pages.
        """
        if "..." not in description:
            return None
        # Matches: 'zzgl. \u20ac 3.10 Pf...' / 'zzgl. \u20ac 3.10 P...' / 'zzgl. \u20ac 0.25 Pfand...'
        # The amount must not look like a per-litre price (>= 0.05, <= 50).
        match = re.search(
            r"(?:zzgl\.?|zuz(?:\xfc|ue)glich|\+)\s*\u20ac?\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*\u20ac?\s*P(?:f(?:a(?:nd?)?)?)?(?:\.\.\.|\s*$)",
            description,
            re.IGNORECASE,
        )
        if match:
            amount = parse_number(match.group(1))
            if amount is not None and 0.05 <= amount <= 50:
                return amount
        return None

    @staticmethod
    def _distance_km(left: tuple[float, float], right: tuple[float, float]) -> float:
        lat1, lon1 = left
        lat2, lon2 = right
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        lat1r = radians(lat1)
        lat2r = radians(lat2)
        value = sin(dlat / 2.0) ** 2 + cos(lat1r) * cos(lat2r) * sin(dlon / 2.0) ** 2
        return 6371.0088 * 2.0 * asin(sqrt(min(1.0, max(0.0, value))))

    def _postal_coordinates(self, postal_code: str) -> tuple[float, float] | None:
        """Resolve latitude and longitude for a postal code via PostalCodeLocator or Nominatim."""
        remembered = self._coordinate_cache.get(postal_code)
        if remembered is not None:
            return remembered
        http = getattr(self.locator, "http", None)
        if http is not None and hasattr(http, "get_bytes"):
            query = urlencode(
                {
                    "postalcode": postal_code,
                    "country": "Germany",
                    "format": "jsonv2",
                    "addressdetails": 1,
                    "limit": 1,
                }
            )
            try:
                raw_bytes = http.get_bytes(
                    f"https://nominatim.openstreetmap.org/search?{query}",
                    {"Accept": "application/json"},
                )
                payload = json.loads(raw_bytes.decode("utf-8", errors="replace"))
                if isinstance(payload, list) and payload and isinstance(payload[0], dict):
                    lat = float(payload[0].get("lat"))
                    lon = float(payload[0].get("lon"))
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        self._coordinate_cache[postal_code] = (lat, lon)
                        return lat, lon
            except Exception:
                pass
        return None

    def _fetch_all_markets(self, session: Any) -> list[dict[str, Any]]:
        try:
            from bs4 import BeautifulSoup
        except Exception as exc:
            raise ToolError(f"trinkgut benötigt BeautifulSoup: {exc}") from exc

        response = session.get(self.MARKETS_URL, timeout=self.timeout_seconds)
        if response.status_code != 200:
            raise ToolError(f"trinkgut Marktsuche HTTP {response.status_code}")

        soup = BeautifulSoup(response.text, "html.parser")
        tag = soup.find(id="markets--data")
        if tag is None or not tag.string:
            raise ToolError("trinkgut Marktsuche enthielt keine Filialdaten (markets--data)")

        try:
            markets = json.loads(tag.string)
        except Exception as exc:
            raise ToolError(f"trinkgut Filialdaten konnten nicht geparst werden: {exc}") from exc

        if not isinstance(markets, list):
            raise ToolError("trinkgut Filialdaten haben ein unerwartetes Format")

        parsed_markets: list[dict[str, Any]] = []
        for item in markets:
            if not isinstance(item, dict):
                continue
            market_id = clean_text(item.get("id"))
            if not market_id:
                continue
            parsed_markets.append(item)

        if not parsed_markets:
            raise ToolError("trinkgut lieferte keine gültigen Filialen")

        return parsed_markets

    def _get_all_markets(self, session: Any | None = None) -> list[dict[str, Any]]:
        now = time.time()
        with self._cache_lock:
            if self._all_markets_mem and (now - self._all_markets_loaded_at) < self.markets_cache_ttl_seconds:
                return self._all_markets_mem

            path = self._markets_cache_path
            if path is not None and path.exists():
                try:
                    stat = path.stat()
                    if (now - stat.st_mtime) < self.markets_cache_ttl_seconds:
                        cached = json.loads(path.read_text(encoding="utf-8"))
                        if isinstance(cached, list) and cached:
                            self._all_markets_mem = cached
                            self._all_markets_loaded_at = stat.st_mtime
                            return cached
                except (OSError, ValueError, TypeError):
                    pass

        active_session = session or self._session()
        markets = self._fetch_all_markets(active_session)

        with self._cache_lock:
            self._all_markets_mem = markets
            self._all_markets_loaded_at = now
            path = self._markets_cache_path
            if path is not None:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_suffix(path.suffix + ".tmp")
                    tmp.write_text(json.dumps(markets, ensure_ascii=False), encoding="utf-8")
                    tmp.replace(path)
                except OSError:
                    pass

        return markets

    def _market_fields(self, selected: dict[str, Any], distance_suffix: str = "") -> tuple[str, str, str]:
        m_id = clean_text(selected.get("id"))
        name = clean_text(selected.get("name"))
        city = clean_text(selected.get("city"))
        zip_code = clean_text(selected.get("zipCode"))
        label = f"trinkgut {name} ({zip_code} {city}){distance_suffix}".strip()
        url = self._safe_url(clean_text(selected.get("detailURL")), self.MARKETS_URL)
        return m_id, label, url

    def _nearest_market(self, postal_code: str, all_markets: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
        # No exact match for postal code: the geographically nearest market,
        # but only within the configured distance. Never guess a market from
        # numerically close postal codes or take an arbitrary one: those can
        # be hundreds of kilometres away and would be shown as local offers.
        coords = self._postal_coordinates(postal_code)
        if coords is None:
            raise ToolError(
                f"trinkgut: kein Markt mit der PLZ {postal_code}, und der Standort der PLZ "
                "ließ sich nicht bestimmen"
            )

        ranked: list[tuple[float, dict[str, Any]]] = []
        for m in all_markets:
            try:
                m_lat = float(m.get("latitude", 0))
                m_lon = float(m.get("longitude", 0))
            except (ValueError, TypeError):
                continue
            if m_lat == 0 and m_lon == 0:
                continue
            ranked.append((self._distance_km(coords, (m_lat, m_lon)), m))
        if not ranked:
            raise ToolError("trinkgut: die Marktliste enthält keine Standortdaten")

        ranked.sort(key=lambda item: item[0])
        selected_distance, selected = ranked[0]
        if selected_distance > self.max_distance_km:
            near_name = clean_text(selected.get("city")) or clean_text(selected.get("name"))
            raise NoLocalMarketError(
                f"trinkgut: kein Markt im Umkreis von {self.max_distance_km:.0f} km um {postal_code} "
                f"(nächster: {near_name}, {selected_distance:.0f} km)"
            )
        return selected_distance, selected

    def _find_market(
        self,
        postal_code: str,
        *,
        use_cache: bool = True,
        market_id: str = "",
    ) -> tuple[Any, str, str, str, float | None]:
        requested_market_id = clean_text(market_id)
        if use_cache and not requested_market_id:
            cached = self._cached_market(postal_code)
            if cached is not None:
                cached_id, market_url, label, distance_km = cached
                if distance_km is None or distance_km <= self.max_distance_km:
                    return self._session(), cached_id, self._safe_url(market_url, self.MARKETS_URL), label, distance_km

        session = self._session()
        all_markets = self._get_all_markets(session)

        if requested_market_id:
            selected = next((m for m in all_markets if clean_text(m.get("id")) == requested_market_id), None)
            if selected is None:
                raise ToolError(f"Der gewählte trinkgut-Markt {requested_market_id} existiert nicht")
            m_id, label, url = self._market_fields(selected)
            self.last_discovery = "Manuelle Auswahl"
            self.last_distance_km = None
            return session, m_id, url, label, None

        # 1. Look for exact match by postal code
        exact = [m for m in all_markets if clean_text(m.get("zipCode")) == postal_code]
        if exact:
            selected = exact[0]
            m_id, label, url = self._market_fields(selected)
            self.last_discovery = "trinkgut Marktsuche (exakt)"
            self.last_distance_km = 0.0
            self._cache_market(postal_code, m_id, url, label, 0.0)
            return session, m_id, url, label, 0.0

        # 2. No exact match: fall back to the nearest market within range.
        selected_distance, selected = self._nearest_market(postal_code, all_markets)
        self.last_discovery = f"trinkgut Nächstsuche ({selected_distance:.1f} km)"
        dist_suffix = f" [{selected_distance:.1f} km]" if selected_distance is not None else ""
        m_id, label, url = self._market_fields(selected, dist_suffix)
        self.last_distance_km = selected_distance
        self._cache_market(postal_code, m_id, url, label, selected_distance)
        return session, m_id, url, label, selected_distance

    def markets(self, postal_code: str) -> list[dict[str, Any]]:
        """Return exact postal code markets or the closest available markets with distance."""
        all_markets = self._get_all_markets()
        exact = [m for m in all_markets if clean_text(m.get("zipCode")) == postal_code]
        if exact:
            return [
                {
                    "market_id": clean_text(m.get("id")),
                    "market_url": self._safe_url(clean_text(m.get("detailURL")), self.MARKETS_URL),
                    "label": f"trinkgut {clean_text(m.get('name'))} ({clean_text(m.get('zipCode'))} {clean_text(m.get('city'))})",
                    "distance_km": 0.0,
                    "street": clean_text(m.get("street")),
                    "city": clean_text(m.get("city")),
                    "zipCode": clean_text(m.get("zipCode")),
                }
                for m in exact
            ]

        coords = self._postal_coordinates(postal_code)
        if coords is None:
            return []
        ranked: list[tuple[float, dict[str, Any]]] = []
        for m in all_markets:
            try:
                m_lat = float(m.get("latitude", 0))
                m_lon = float(m.get("longitude", 0))
            except (ValueError, TypeError):
                continue
            if m_lat == 0 and m_lon == 0:
                continue
            distance = self._distance_km(coords, (m_lat, m_lon))
            if distance <= self.max_distance_km:
                ranked.append((distance, m))
        ranked.sort(key=lambda item: item[0])
        return [
            {
                "market_id": clean_text(m.get("id")),
                "market_url": self._safe_url(clean_text(m.get("detailURL")), self.MARKETS_URL),
                "label": f"trinkgut {clean_text(m.get('name'))} ({clean_text(m.get('zipCode'))} {clean_text(m.get('city'))}) [{d:.1f} km]",
                "distance_km": round(d, 1),
                "street": clean_text(m.get("street")),
                "city": clean_text(m.get("city")),
                "zipCode": clean_text(m.get("zipCode")),
            }
            for d, m in ranked[:10]
        ]

    @classmethod
    def _parse_validity(cls, soup: Any, reference_date: date | None = None) -> tuple[date | None, date | None, str]:
        """Extract offer validity dates from the page text or intro."""
        text = soup.get_text(" ", strip=True) if hasattr(soup, "get_text") else str(soup)
        match = re.search(r"[Gg]ültig\s+vom\s+(\d{1,2}\.\d{1,2}\.\d{4})\s+bis\s+(\d{1,2}\.\d{1,2}\.\d{4})", text)
        if match:
            try:
                start = datetime.strptime(match.group(1), "%d.%m.%Y").date()
                end = datetime.strptime(match.group(2), "%d.%m.%Y").date()
                return start, end, format_validity(start, end)
            except ValueError:
                pass

        ref = offer_reference_date(reference_date or today_berlin())
        monday = ref.fromordinal(ref.toordinal() - ref.weekday())
        sunday = monday.fromordinal(monday.toordinal() + 6)
        return monday, sunday, format_validity(monday, sunday)

    def _parse_card(
        self,
        card: Any,
        *,
        index: int,
        category: str,
        market_id: str,
        market_url: str,
        validity_label: str,
        valid_from: date | None,
        valid_until: date | None,
    ) -> Offer | None:
        name_node = card.select_one(".product-name")
        title = clean_text(name_node.get_text(" ", strip=True) if name_node else "")
        if not title:
            return None

        # A PAYBACK points badge shares the price class; it is a bonus, never the price.
        price = None
        bonus_labels: list[str] = []
        for price_node in card.select(".product-price"):
            label = clean_text(price_node.get_text(" ", strip=True))
            if any("payback" in name.lower() for name in price_node.get("class", [])) or "°P" in label:
                if label:
                    bonus_labels.append(label)
                continue
            if price is None:
                price = parse_number(label)
        if price is None or price <= 0:
            return None
        bonus_condition = (
            f"PAYBACK: {', '.join(bonus_labels)} (Punkte, kein Preisnachlass)" if bonus_labels else ""
        )

        desc_node = card.select_one(".product-description")
        description = clean_text(desc_node.get_text(" ", strip=True) if desc_node else "")

        base_price, base_unit = parse_base_price_text(description)
        deposit = parse_deposit_text(description) or self._parse_truncated_deposit(description)
        # A truncated second crate quantity cannot justify choosing the first.
        truncated_alternative = bool(re.search(r"[/|]\s*\d+\s*[x×]\s*(?:\d+(?:[,.]\d*)?)?\s*(?:\.{3}|…)", description, re.I))
        pack = "" if truncated_alternative else normalize_pack(f"{title} {description}")
        if truncated_alternative:
            base_price, base_unit = None, ""

        image_url = ""
        img_node = card.select_one("img.product-image") or card.select_one("img")
        if img_node is not None:
            raw_src = clean_text(img_node.get("src"))
            candidate = normalize_image_url(raw_src, base_url=self.BASE)
            if candidate and not is_rejected_image_url(candidate):
                image_url = candidate

        link_node = card.select_one("a.product-image-link") or card.select_one("a[href]")
        product_url = self._safe_url(urljoin(self.BASE, clean_text(link_node.get("href"))), self.OFFERS_URL) if link_node else self.OFFERS_URL

        slug_title = self._slug(title) or f"item-{index}"
        offer_id = f"trinkgut:{market_id}:{slug_title}:{index}"

        return Offer(
            offer_id=offer_id,
            retailer="trinkgut",
            category=clean_text(category) or "Weitere Angebote",
            name=title,
            brand="",
            description=description,
            price=price,
            base_price=base_price,
            base_unit=base_unit,
            pack_signature=pack,
            validity_label=validity_label,
            match_key=build_match_key("", title, pack, offer_id),
            source_url=self.OFFERS_URL,
            product_url=product_url,
            retailer_url=market_url,
            image_url=image_url,
            deposit=deposit,
            benefits=(),
            offer_condition=bonus_condition,
            coverage_note="Packungsalternative in der Quelle abgeschnitten; kein eindeutiger Mengenvergleich" if truncated_alternative else "",
            valid_from=valid_from.isoformat() if valid_from else None,
            valid_until=valid_until.isoformat() if valid_until else None,
        )

    def _deposit_cache_path(self) -> Path | None:
        return self.cache_dir / "trinkgut-deposits.json" if self.cache_dir is not None else None

    def _read_deposit_cache(self, now: float) -> None:
        """Load remembered deposits from disk once and drop the expired ones."""
        with self._cache_lock:
            path = self._deposit_cache_path()
            if path is not None and not self._deposit_cache and path.exists():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    for url, entry in raw.items():
                        if isinstance(entry, dict) and self._is_trinkgut_url(url):
                            value = entry.get("deposit")
                            self._deposit_cache[url] = (float(entry.get("at", 0)), float(value) if value is not None else None)
                except (OSError, ValueError, TypeError):
                    self._deposit_cache = {}
            self._deposit_cache = {
                url: entry
                for url, entry in self._deposit_cache.items()
                if now - entry[0] <= self.deposit_cache_ttl_seconds
            }

    def _write_deposit_cache(self) -> None:
        path = self._deposit_cache_path()
        if path is None:
            return
        with self._cache_lock:
            payload = {url: {"at": at, "deposit": deposit} for url, (at, deposit) in self._deposit_cache.items()}
            try:
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(payload), encoding="utf-8")
                temporary.replace(path)
            except OSError:
                pass

    def _offers_needing_deposit_fetch(self, offers: list[Offer]) -> list[tuple[int, str]]:
        # Identify which offers need enrichment (deposit unknown + truncated desc)
        return [
            (i, o.product_url)
            for i, o in enumerate(offers)
            if o.deposit is None
            and o.product_url
            and o.product_url != self.OFFERS_URL
            and self._is_trinkgut_url(o.product_url)
            and "..." in o.description
        ]

    def _split_cached_deposits(
        self, need_fetch: list[tuple[int, str]], now: float
    ) -> tuple[dict[int, float | None], list[tuple[int, str]]]:
        remembered: dict[int, float | None] = {}
        to_request: list[tuple[int, str]] = []
        for idx, url in need_fetch:
            hit = self._deposit_cache.get(url)
            if hit is not None and now - hit[0] <= self.deposit_cache_ttl_seconds:
                remembered[idx] = hit[1]
            else:
                to_request.append((idx, url))
        return remembered, to_request

    def _fetch_full_description_deposit(self, session: Any, args: tuple[int, str]) -> tuple[int, float | None]:
        idx, url = args
        try:
            from bs4 import BeautifulSoup
            r = session.get(url, timeout=min(self.timeout_seconds, 15))
            if r.status_code != 200:
                return idx, None
            soup = BeautifulSoup(r.text, "html.parser")
            el = soup.select_one("[itemprop=description]")
            if el is None:
                return idx, None
            full_desc = clean_text(el.get_text(" ", strip=True))
            return idx, parse_deposit_text(full_desc)
        except Exception:
            return idx, None

    def _fetch_missing_deposits(self, session: Any, need_fetch: list[tuple[int, str]]) -> list[tuple[int, float | None]]:
        import concurrent.futures
        workers = max(1, min(self.deposit_workers, len(need_fetch)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            fetched = list(executor.map(lambda args: self._fetch_full_description_deposit(session, args), need_fetch))
        stamp = time.time()
        for (_idx, url), (_, deposit) in zip(need_fetch, fetched, strict=True):
            self._deposit_cache[url] = (stamp, deposit)
        self._write_deposit_cache()
        return fetched

    def _enrich_deposits(self, offers: list[Offer], session: Any) -> list[Offer]:
        """Parallel-fetch detail pages for offers where the listing description was
        server-truncated and no deposit could be parsed from the card HTML.

        trinkgut truncates listing descriptions to ~52 characters. For many
        crate items the deposit text ('zzgl. \u20ac X.XX Pfand') is cut before the
        amount is even visible. The detail page always carries the full text in
        ``[itemprop=description]``.
        """
        try:
            from bs4 import BeautifulSoup  # noqa: F401 - validated eagerly; used in the fetch helper below
            import concurrent.futures  # noqa: F401 - validated eagerly; used in the fetch helper below
        except Exception:
            return offers  # if BeautifulSoup is missing we already raised earlier

        need_fetch = self._offers_needing_deposit_fetch(offers)
        # What was read recently is not read again: a deposit does not change
        # from one search to the next, and the site should not be hit for it.
        now = time.time()
        self._read_deposit_cache(now)
        remembered, need_fetch = self._split_cached_deposits(need_fetch, now)

        results: list[tuple[int, float | None]] = list(remembered.items())
        if need_fetch:
            results.extend(self._fetch_missing_deposits(session, need_fetch))
        for idx, deposit in results:
            if deposit is not None:
                old = offers[idx]
                offers[idx] = replace(old, deposit=deposit)
        return offers

    def _fetch_offers_response(
        self,
        postal_code: str,
        requested_market_id: str,
        request_url: str,
        session: Any,
        market_id: str,
        market_url: str,
        market_label: str,
        distance_km: float | None,
    ) -> tuple[Any, str, str, str, float | None, Any]:
        # Set market cookie for personalized store offers
        session.cookies.set("market", market_id, domain="www.trinkgut.de")
        response = session.get(request_url, timeout=self.timeout_seconds)
        if response.status_code != 200 and self.last_discovery == "24h-Marktcache" and not requested_market_id:
            self._drop_cached_market(postal_code)
            session, market_id, market_url, market_label, distance_km = self._find_market(
                postal_code, use_cache=False
            )
            session.cookies.set("market", market_id, domain="www.trinkgut.de")
            response = session.get(request_url, timeout=self.timeout_seconds)
        if response.status_code != 200:
            raise ToolError(f"trinkgut Angebotsseite HTTP {response.status_code}")
        return session, market_id, market_url, market_label, distance_km, response

    def _parse_card_list(
        self,
        cards: Any,
        start_index: int,
        category: str,
        market_id: str,
        market_url: str,
        validity_label: str,
        valid_from: Any,
        valid_until: Any,
    ) -> tuple[list[Offer], int, int]:
        offers: list[Offer] = []
        unknown_cards = 0
        card_index = start_index
        for card in cards:
            card_index += 1
            offer = self._parse_card(
                card,
                index=card_index,
                category=category,
                market_id=market_id,
                market_url=market_url,
                validity_label=validity_label,
                valid_from=valid_from,
                valid_until=valid_until,
            )
            if offer is not None:
                offers.append(offer)
            else:
                unknown_cards += 1
        return offers, unknown_cards, card_index

    def _cards_from_rows(
        self,
        cards_container: Any,
        market_id: str,
        market_url: str,
        validity_label: str,
        valid_from: Any,
        valid_until: Any,
    ) -> tuple[list[Offer], int, int, str]:
        current_category = "Weitere Angebote"
        offers: list[Offer] = []
        unknown_cards = 0
        card_index = 0
        for child in cards_container.children:
            if not getattr(child, "name", None):
                continue
            classes = child.get("class", [])
            if "listing-divider" in classes or any("divider" in c for c in classes):
                cat_heading = child.find(["h1", "h2", "h3", "h4", "h5"])
                if cat_heading:
                    current_category = clean_text(cat_heading.get_text(" ", strip=True))
                continue

            child_offers, child_unknown, card_index = self._parse_card_list(
                child.select(".product-box"), card_index, current_category,
                market_id, market_url, validity_label, valid_from, valid_until,
            )
            offers.extend(child_offers)
            unknown_cards += child_unknown
        return offers, unknown_cards, card_index, current_category

    def load(
        self,
        postal_code: str,
        market_id: str = "",
        offer_week: str = "current",
    ) -> list[Offer]:
        try:
            from bs4 import BeautifulSoup
        except Exception as exc:
            raise ToolError(f"trinkgut benötigt BeautifulSoup: {exc}") from exc

        self.scope_note = ""
        requested_market_id = clean_text(market_id)
        try:
            session, market_id, market_url, market_label, distance_km = self._find_market(
                postal_code, market_id=requested_market_id
            )
        except NoLocalMarketError:
            return NoLocalMarketOffers()

        requested_week = normalize_offer_week(offer_week)
        reference_date = offer_week_reference(requested_week)

        request_url = f"{self.OFFERS_URL}?week=next" if requested_week == "next" else self.OFFERS_URL
        session, market_id, market_url, market_label, distance_km, response = self._fetch_offers_response(
            postal_code, requested_market_id, request_url, session, market_id, market_url, market_label, distance_km
        )

        soup = BeautifulSoup(response.text, "html.parser")
        valid_from, valid_until, validity_label = self._parse_validity(soup, reference_date)

        row = soup.select_one(".cms-listing-row")
        cards_container = row or soup.select_one(".cms-element-product-listing-wrapper") or soup

        offers, unknown_cards, card_index, current_category = self._cards_from_rows(
            cards_container, market_id, market_url, validity_label, valid_from, valid_until
        )

        # Fallback if product-box cards were directly in container
        if not offers:
            offers, fallback_unknown, card_index = self._parse_card_list(
                cards_container.select(".product-box"), card_index, current_category,
                market_id, market_url, validity_label, valid_from, valid_until,
            )
            unknown_cards += fallback_unknown

        self.last_market_id = market_id
        self.last_market_label = market_label
        self.last_market_url = market_url
        self.last_distance_km = distance_km
        self.last_current_count = len(offers)
        self.last_unknown_count = unknown_cards

        if not offers:
            detail = f"; {unknown_cards} Karten konnten nicht ausgewertet werden" if unknown_cards else ""
            raise ToolError(f"trinkgut {postal_code}: keine auswertbaren aktuellen Angebote{detail}")

        # Enrich deposits that could not be parsed from the truncated listing HTML
        offers = self._enrich_deposits(offers, session)

        incomplete_packs = sum(bool(o.coverage_note) for o in offers)
        if incomplete_packs:
            self.scope_note = f"trinkgut: {incomplete_packs} abgeschnittene Packungsalternativen ohne eindeutigen Mengenvergleich"
        parsed = deduplicate_offers(offers)
        return PartialOffers(parsed, f"trinkgut: {unknown_cards} Angebotskarten nicht auswertbar") if unknown_cards else parsed
