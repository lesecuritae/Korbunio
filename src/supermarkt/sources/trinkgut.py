from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from datetime import date, datetime
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode, urljoin

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
from ..http import PostalCodeLocator
from ..images import is_rejected_image_url, normalize_image_url
from ..models import Offer, ToolError


class OfficialTrinkgutSource:
    BASE = "https://www.trinkgut.de"
    MARKETS_URL = BASE + "/marktsuche"
    OFFERS_URL = BASE + "/angebote/"

    def __init__(
        self,
        locator: PostalCodeLocator,
        timeout_seconds: int = 45,
        *,
        cache_dir: Optional[Path] = None,
        store_cache_ttl_seconds: int = 86400,
        markets_cache_ttl_seconds: int = 86400,
    ) -> None:
        self.locator = locator
        self.timeout_seconds = max(10, min(int(timeout_seconds), 90))
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else None
        self.store_cache_ttl_seconds = max(300, min(int(store_cache_ttl_seconds), 7 * 86400))
        self.markets_cache_ttl_seconds = max(300, min(int(markets_cache_ttl_seconds), 7 * 86400))
        self._cache_lock = threading.RLock()
        self._all_markets_mem: Optional[list[dict[str, Any]]] = None
        self._all_markets_loaded_at: float = 0.0

        self.last_market_id = ""
        self.last_market_label = ""
        self.last_market_url = ""
        self.last_discovery = ""
        self.last_distance_km: Optional[float] = None
        self.last_current_count = 0
        self.last_unknown_count = 0

        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _store_cache_path(self) -> Optional[Path]:
        return self.cache_dir / "stores.json" if self.cache_dir is not None else None

    @property
    def _markets_cache_path(self) -> Optional[Path]:
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

    def _cleanup_store_cache(self, now: Optional[float] = None) -> dict[str, dict[str, Any]]:
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

    def _cached_market(self, postal_code: str) -> Optional[tuple[str, str, str, Optional[float]]]:
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
        distance_km: Optional[float] = None,
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

    def _session(self):
        try:
            from curl_cffi import requests as curl_requests
        except Exception as exc:
            raise ToolError(f"trinkgut benötigt curl_cffi: {exc}") from exc
        return curl_requests.Session(impersonate="chrome")

    @staticmethod
    def _slug(value: str) -> str:
        raw = unicodedata.normalize("NFKD", clean_text(value).casefold())
        raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
        return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")

    @staticmethod
    def _parse_truncated_deposit(description: str) -> Optional[float]:
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

    def _postal_coordinates(self, postal_code: str) -> Optional[tuple[float, float]]:
        """Resolve latitude and longitude for a postal code via PostalCodeLocator or Nominatim."""
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

    def _get_all_markets(self, session: Optional[Any] = None) -> list[dict[str, Any]]:
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

    def _find_market(
        self,
        postal_code: str,
        *,
        use_cache: bool = True,
        market_id: str = "",
    ) -> tuple[Any, str, str, str, Optional[float]]:
        requested_market_id = clean_text(market_id)
        if use_cache and not requested_market_id:
            cached = self._cached_market(postal_code)
            if cached is not None:
                cached_id, market_url, label, distance_km = cached
                return self._session(), cached_id, market_url, label, distance_km

        session = self._session()
        all_markets = self._get_all_markets(session)

        if requested_market_id:
            selected = next((m for m in all_markets if clean_text(m.get("id")) == requested_market_id), None)
            if selected is None:
                raise ToolError(f"Der gewählte trinkgut-Markt {requested_market_id} existiert nicht")
            m_id = clean_text(selected.get("id"))
            name = clean_text(selected.get("name"))
            city = clean_text(selected.get("city"))
            zip_code = clean_text(selected.get("zipCode"))
            label = f"trinkgut {name} ({zip_code} {city})".strip()
            url = clean_text(selected.get("detailURL")) or self.MARKETS_URL
            self.last_discovery = "Manuelle Auswahl"
            self.last_distance_km = None
            return session, m_id, url, label, None

        # 1. Look for exact match by postal code
        exact = [m for m in all_markets if clean_text(m.get("zipCode")) == postal_code]
        if exact:
            selected = exact[0]
            m_id = clean_text(selected.get("id"))
            name = clean_text(selected.get("name"))
            city = clean_text(selected.get("city"))
            zip_code = clean_text(selected.get("zipCode"))
            label = f"trinkgut {name} ({zip_code} {city})".strip()
            url = clean_text(selected.get("detailURL")) or self.MARKETS_URL
            self.last_discovery = "trinkgut Marktsuche (exakt)"
            self.last_distance_km = 0.0
            self._cache_market(postal_code, m_id, url, label, 0.0)
            return session, m_id, url, label, 0.0

        # 2. No exact match for postal code: select geographically nearest market
        coords = self._postal_coordinates(postal_code)
        selected = None
        selected_distance: Optional[float] = None

        if coords is not None:
            ranked: list[tuple[float, dict[str, Any]]] = []
            for m in all_markets:
                try:
                    m_lat = float(m.get("latitude", 0))
                    m_lon = float(m.get("longitude", 0))
                except (ValueError, TypeError):
                    continue
                if m_lat == 0 and m_lon == 0:
                    continue
                d = self._distance_km(coords, (m_lat, m_lon))
                ranked.append((d, m))

            if ranked:
                ranked.sort(key=lambda item: item[0])
                selected_distance, selected = ranked[0]
                self.last_discovery = f"trinkgut Nächstsuche ({selected_distance:.1f} km)"

        if selected is None:
            # Fallback: nearest numeric zip code difference
            try:
                target_num = int(postal_code)
                ranked_zip = sorted(
                    all_markets,
                    key=lambda m: abs(int(clean_text(m.get("zipCode")) or "99999") - target_num)
                    if (clean_text(m.get("zipCode")) or "").isdigit()
                    else 999999,
                )
                selected = ranked_zip[0]
                self.last_discovery = "trinkgut PLZ-Annäherung"
                selected_distance = None
            except (ValueError, IndexError):
                selected = all_markets[0]
                self.last_discovery = "trinkgut Standardmarkt"
                selected_distance = None

        m_id = clean_text(selected.get("id"))
        name = clean_text(selected.get("name"))
        city = clean_text(selected.get("city"))
        zip_code = clean_text(selected.get("zipCode"))
        dist_suffix = f" [{selected_distance:.1f} km]" if selected_distance is not None else ""
        label = f"trinkgut {name} ({zip_code} {city}){dist_suffix}".strip()
        url = clean_text(selected.get("detailURL")) or self.MARKETS_URL
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
                    "market_url": clean_text(m.get("detailURL")),
                    "label": f"trinkgut {clean_text(m.get('name'))} ({clean_text(m.get('zipCode'))} {clean_text(m.get('city'))})",
                    "distance_km": 0.0,
                    "street": clean_text(m.get("street")),
                    "city": clean_text(m.get("city")),
                    "zipCode": clean_text(m.get("zipCode")),
                }
                for m in exact
            ]

        coords = self._postal_coordinates(postal_code)
        if coords is not None:
            ranked: list[tuple[float, dict[str, Any]]] = []
            for m in all_markets:
                try:
                    m_lat = float(m.get("latitude", 0))
                    m_lon = float(m.get("longitude", 0))
                except (ValueError, TypeError):
                    continue
                if m_lat == 0 and m_lon == 0:
                    continue
                d = self._distance_km(coords, (m_lat, m_lon))
                ranked.append((d, m))
            ranked.sort(key=lambda item: item[0])
            return [
                {
                    "market_id": clean_text(m.get("id")),
                    "market_url": clean_text(m.get("detailURL")),
                    "label": f"trinkgut {clean_text(m.get('name'))} ({clean_text(m.get('zipCode'))} {clean_text(m.get('city'))}) [{d:.1f} km]",
                    "distance_km": round(d, 1),
                    "street": clean_text(m.get("street")),
                    "city": clean_text(m.get("city")),
                    "zipCode": clean_text(m.get("zipCode")),
                }
                for d, m in ranked[:10]
            ]

        # Numeric fallback
        try:
            target_num = int(postal_code)
            ranked_zip = sorted(
                all_markets,
                key=lambda m: abs(int(clean_text(m.get("zipCode")) or "99999") - target_num)
                if (clean_text(m.get("zipCode")) or "").isdigit()
                else 999999,
            )
            return [
                {
                    "market_id": clean_text(m.get("id")),
                    "market_url": clean_text(m.get("detailURL")),
                    "label": f"trinkgut {clean_text(m.get('name'))} ({clean_text(m.get('zipCode'))} {clean_text(m.get('city'))})",
                    "distance_km": None,
                    "street": clean_text(m.get("street")),
                    "city": clean_text(m.get("city")),
                    "zipCode": clean_text(m.get("zipCode")),
                }
                for m in ranked_zip[:10]
            ]
        except (ValueError, IndexError):
            return []

    @classmethod
    def _parse_validity(cls, soup: Any, reference_date: Optional[date] = None) -> tuple[Optional[date], Optional[date], str]:
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
        valid_from: Optional[date],
        valid_until: Optional[date],
    ) -> Optional[Offer]:
        name_node = card.select_one(".product-name")
        title = clean_text(name_node.get_text(" ", strip=True) if name_node else "")
        if not title:
            return None

        price_node = card.select_one(".product-price span") or card.select_one(".product-price")
        price = parse_number(price_node.get_text(" ", strip=True) if price_node else None)
        if price is None or price <= 0:
            return None

        desc_node = card.select_one(".product-description")
        description = clean_text(desc_node.get_text(" ", strip=True) if desc_node else "")

        base_price, base_unit = parse_base_price_text(description)
        deposit = parse_deposit_text(description) or self._parse_truncated_deposit(description)
        pack = normalize_pack(f"{title} {description}")

        image_url = ""
        img_node = card.select_one("img.product-image") or card.select_one("img")
        if img_node is not None:
            raw_src = clean_text(img_node.get("src"))
            candidate = normalize_image_url(raw_src, base_url=self.BASE)
            if candidate and not is_rejected_image_url(candidate):
                image_url = candidate

        link_node = card.select_one("a.product-image-link") or card.select_one("a[href]")
        product_url = urljoin(self.BASE, clean_text(link_node.get("href"))) if link_node else self.OFFERS_URL

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
            valid_from=valid_from.isoformat() if valid_from else None,
            valid_until=valid_until.isoformat() if valid_until else None,
        )

    def _enrich_deposits(self, offers: list[Offer], session: Any) -> list[Offer]:
        """Parallel-fetch detail pages for offers where the listing description was
        server-truncated and no deposit could be parsed from the card HTML.

        trinkgut truncates listing descriptions to ~52 characters. For many
        crate items the deposit text ('zzgl. \u20ac X.XX Pfand') is cut before the
        amount is even visible. The detail page always carries the full text in
        ``[itemprop=description]``.
        """
        try:
            from bs4 import BeautifulSoup
            import concurrent.futures
        except Exception:
            return offers  # if BeautifulSoup is missing we already raised earlier

        # Identify which offers need enrichment (deposit unknown + truncated desc)
        need_fetch: list[tuple[int, str]] = [
            (i, o.product_url)
            for i, o in enumerate(offers)
            if o.deposit is None and o.product_url and o.product_url != self.OFFERS_URL and "..." in o.description
        ]
        if not need_fetch:
            return offers

        def fetch_full_desc(args: tuple[int, str]) -> tuple[int, Optional[float]]:
            idx, url = args
            try:
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

        workers = min(12, len(need_fetch))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            for idx, deposit in executor.map(fetch_full_desc, need_fetch):
                if deposit is not None:
                    old = offers[idx]
                    offers[idx] = Offer(
                        offer_id=old.offer_id,
                        retailer=old.retailer,
                        category=old.category,
                        name=old.name,
                        brand=old.brand,
                        description=old.description,
                        price=old.price,
                        base_price=old.base_price,
                        base_unit=old.base_unit,
                        pack_signature=old.pack_signature,
                        validity_label=old.validity_label,
                        match_key=old.match_key,
                        source_url=old.source_url,
                        product_url=old.product_url,
                        retailer_url=old.retailer_url,
                        image_url=old.image_url,
                        deposit=deposit,
                        benefits=old.benefits,
                        valid_from=old.valid_from,
                        valid_until=old.valid_until,
                    )
        return offers

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

        requested_market_id = clean_text(market_id)
        session, market_id, market_url, market_label, distance_km = self._find_market(
            postal_code, market_id=requested_market_id
        )

        requested_week = normalize_offer_week(offer_week)
        reference_date = offer_week_reference(requested_week)

        # Set market cookie for personalized store offers
        session.cookies.set("market", market_id, domain="www.trinkgut.de")

        request_url = f"{self.OFFERS_URL}?week=next" if requested_week == "next" else self.OFFERS_URL
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

        soup = BeautifulSoup(response.text, "html.parser")
        valid_from, valid_until, validity_label = self._parse_validity(soup, reference_date)

        row = soup.select_one(".cms-listing-row")
        cards_container = row or soup.select_one(".cms-element-product-listing-wrapper") or soup

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

            for card in child.select(".product-box"):
                card_index += 1
                offer = self._parse_card(
                    card,
                    index=card_index,
                    category=current_category,
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

        # Fallback if product-box cards were directly in container
        if not offers:
            for card in cards_container.select(".product-box"):
                card_index += 1
                offer = self._parse_card(
                    card,
                    index=card_index,
                    category=current_category,
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

        return deduplicate_offers(offers)
