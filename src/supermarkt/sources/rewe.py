from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import unicodedata
from datetime import date
from pathlib import Path
import uuid
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

from ..common import build_match_key, clean_text, deduplicate_offers, normalize_offer_week, normalize_pack, offer_reference_date, offer_week_reference, parse_base_price_text, parse_deposit_text, parse_number, today_berlin
from ..http import PostalCodeLocator
from ..models import LoyaltyBenefit, Offer, ToolError
from .browser import chromium_command

class OfficialReweSource:
    BASE = "https://www.rewe.de"
    INCLUDE_ENDPOINT = BASE + "/api/frontend-includes"

    def __init__(
        self,
        locator: PostalCodeLocator,
        timeout_seconds: int = 45,
        *,
        cache_dir: Optional[Path] = None,
        store_cache_ttl_seconds: int = 86400,
    ) -> None:
        self.locator = locator
        self.timeout_seconds = max(10, min(int(timeout_seconds), 90))
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else None
        self.store_cache_ttl_seconds = max(300, min(int(store_cache_ttl_seconds), 7 * 86400))
        self._cache_lock = threading.RLock()
        self.last_market_id = ""
        self.last_market_label = ""
        self.last_market_url = ""
        self.last_discovery = ""
        self.last_current_count = 0
        self.last_bonus_only_count = 0
        self.last_unknown_count = 0
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _store_cache_path(self) -> Optional[Path]:
        return self.cache_dir / "stores.json" if self.cache_dir is not None else None

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

    def _cached_market(self, postal_code: str) -> Optional[tuple[str, str, str]]:
        code = clean_text(postal_code)
        mapping = self._cleanup_store_cache()
        item = mapping.get(code)
        if not isinstance(item, dict):
            return None
        market_id = clean_text(item.get("market_id", ""))
        market_url = clean_text(item.get("market_url", ""))
        label = clean_text(item.get("label", ""))
        if not market_id or not market_url.startswith(self.BASE + "/angebote/"):
            self._drop_cached_market(code)
            return None
        self.last_discovery = "24h-Marktcache"
        return market_id, market_url, label

    def _cache_market(self, postal_code: str, market_id: str, market_url: str, label: str) -> None:
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

    @staticmethod
    def _slug(value: str) -> str:
        raw = unicodedata.normalize("NFKD", clean_text(value).casefold())
        raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
        return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")

    @staticmethod
    def _money(node: Any) -> Optional[float]:
        if node is None:
            return None
        match = re.search(r"(?<!\d)(\d{1,4}(?:[.,]\d{1,2})?)\s*€", clean_text(node.get_text(" ", strip=True) if hasattr(node, "get_text") else node))
        return parse_number(match.group(1)) if match else None

    @staticmethod
    def _product_image(card: Any, page_url: str) -> str:
        root = card.select_one(".cor-offer-image") if card is not None else None
        if root is None:
            return ""
        candidates: list[str] = []
        for node in root.select("img,source"):
            for attr in ("data-src", "src", "data-srcset", "srcset"):
                raw = clean_text(node.get(attr))
                if not raw:
                    continue
                for part in raw.split(","):
                    url = clean_text(part.strip().split(" ", 1)[0])
                    if url:
                        candidates.append(urljoin(page_url, url))
        for url in candidates:
            folded = url.casefold()
            if "img.rewe-static.de" not in folded:
                continue
            if any(token in folded for token in (".svg", "loyalty", "bonus", "logo", "icon", "placeholder", "header_")):
                continue
            return url
        return ""

    @staticmethod
    def _target_week(day: Optional[date] = None) -> str:
        current = day or today_berlin()
        return "next" if current.weekday() == 6 else "current"

    @staticmethod
    def _week_label(day: Optional[date] = None) -> str:
        reference = offer_reference_date(day)
        monday = reference.fromordinal(reference.toordinal() - reference.weekday())
        sunday = reference.fromordinal(monday.toordinal() + 6)
        return f"{monday:%d.%m.}–{sunday:%d.%m.%Y}"

    @classmethod
    def _market_week_url(cls, market_url: str, day: Optional[date] = None) -> str:
        if cls._target_week(day) != "next":
            return market_url
        separator = "&" if "?" in market_url else "?"
        return f"{market_url}{separator}week=next"

    def _session(self):
        try:
            from curl_cffi import requests as curl_requests
        except Exception as exc:
            raise ToolError(f"REWE benötigt curl_cffi: {exc}") from exc
        return curl_requests.Session(impersonate="chrome")

    @staticmethod
    def _offer_root(soup: Any, week: str) -> Any:
        """Find the requested REWE offer-week container across known layouts."""
        week = "next" if clean_text(week).casefold() == "next" else "current"
        selectors = (
            f"#sos-categories-{week}",
            f".sos-categories-{week}",
            f'[data-categories-week-value="{week}"]',
            f'[data-testid="sos-categories"][data-categories-week-value="{week}"]',
            f'.sos-week-tabs__content[data-week="{week}"]',
        )
        for selector in selectors:
            node = soup.select_one(selector)
            if node is not None:
                return node

        # REWE also marks individual category blocks with test ids such as
        # "sos-category-...-week-next". Walk up to their categories parent.
        marker = soup.select_one(f'[data-testid$="-week-{week}"]')
        node = marker
        while node is not None:
            if clean_text(node.get("data-categories-week-value")).casefold() == week:
                return node
            classes = {clean_text(value).casefold() for value in (node.get("class") or [])}
            if f"sos-categories-{week}" in classes:
                return node
            node = getattr(node, "parent", None)
        return None


    @classmethod
    def _best_offer_root(cls, soup: Any, week: str, request_url: str = "") -> Any:
        """Return the requested week root, with a guarded active-DOM fallback.

        REWE has used several container names for the active offer week. On a
        URL that explicitly selects ``week=next`` the active container can still
        carry a generic/current-looking class. In that case choose the container
        that actually contains the most offer nodes instead of failing the whole
        retailer.
        """
        root = cls._offer_root(soup, week)
        if root is not None:
            return root

        explicit_next = week == "next" and "week=next" in clean_text(request_url).casefold()
        selectors = (
            '[data-testid="sos-categories"]',
            '[data-controller="categories"]',
            '.sos-categories',
            '[class*="sos-categories"]',
        )
        candidates: list[Any] = []
        seen: set[int] = set()
        for selector in selectors:
            for candidate in soup.select(selector):
                marker = id(candidate)
                if marker in seen:
                    continue
                seen.add(marker)
                candidates.append(candidate)

        def score(candidate: Any) -> int:
            wrappers = len(cls._offer_wrappers(candidate))
            cards = len(candidate.select('.cor-offer-renderer-tile'))
            return max(wrappers, cards)

        ranked = sorted(((score(node), node) for node in candidates), key=lambda item: item[0], reverse=True)
        if ranked and ranked[0][0] > 0 and (explicit_next or len(ranked) == 1):
            return ranked[0][1]

        # Last resort for a fully rendered page where REWE removed the week
        # container but kept the offer tiles. This is safe for an explicitly
        # selected next-week URL; deduplication later removes repeated tiles.
        if explicit_next and soup.select('.cor-offer-renderer-tile'):
            return soup
        return None

    def _render_market_page(self, market_url: str) -> str:
        """Render the market page only when the plain HTTP response lacks offer DOM."""
        errors: list[str] = []
        for headless in ("--headless=new", "--headless"):
            try:
                completed = subprocess.run(
                    [
                        chromium_command(), headless, "--no-sandbox", "--disable-gpu",
                        "--disable-software-rasterizer", "--disable-crashpad-for-testing", "--single-process",
                        "--disable-dev-shm-usage", "--lang=de-DE",
                        "--virtual-time-budget=12000", "--dump-dom", market_url,
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=min(self.timeout_seconds + 25, 120),
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
                continue
            page = completed.stdout or ""
            if "<html" in page.casefold():
                return page
            errors.append(f"Chromium rc={completed.returncode}")
        raise ToolError("REWE Angebotsseite konnte nicht gerendert werden: " + " | ".join(errors[-3:]))

    @staticmethod
    def _offer_wrappers(root: Any) -> list[Any]:
        if root is None:
            return []
        selectors = (
            '.sos-offer[data-offer-nan]',
            '[data-controller="offer"][data-offer-nan]',
            '[data-offer-nan]',
        )
        for selector in selectors:
            nodes = root.select(selector)
            if nodes:
                return list(nodes)
        return []

    @classmethod
    def _collect_offer_cards(cls, root: Any, market_id: str) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
        """Collect offer metadata and already rendered cards from one REWE week."""
        unique: dict[str, dict[str, str]] = {}
        rendered: dict[str, Any] = {}
        for wrapper in cls._offer_wrappers(root):
            nan = clean_text(wrapper.get("data-offer-nan"))
            wwident = clean_text(wrapper.get("data-offer-wwident")) or market_id
            if not nan:
                continue
            unique.setdefault(nan, {
                "nan": nan,
                "wwident": wwident,
                "category": clean_text(wrapper.get("data-category")),
            })
            card = wrapper.select_one(".cor-offer-renderer-tile")
            if card is not None:
                rendered[nan] = card

        if unique:
            return unique, rendered

        # Some REWE layouts render complete cards without the NAN wrapper.
        # Those cards are still usable and should not make the whole source fail.
        for index, card in enumerate(root.select(".cor-offer-renderer-tile"), start=1):
            category_node = card.find_parent(attrs={"data-category-id": True})
            category = ""
            if category_node is not None:
                category = clean_text(category_node.get("data-category-id")).replace("-", " ")
            nan = f"dom-{index}"
            unique[nan] = {"nan": nan, "wwident": market_id, "category": category}
            rendered[nan] = card
        return unique, rendered

    @staticmethod
    def _market_rank(item: tuple[str, str, str]) -> tuple[int, str, str]:
        _market_id, url, label = item
        folded_label = clean_text(label).casefold()
        folded_url = clean_text(url).casefold()
        identity = f"{folded_label} {folded_url}"
        if "rewe center" in identity or "rewe-center" in identity:
            kind = 0
        elif "rewe markt" in identity or "rewe-markt" in identity:
            kind = 1
        else:
            kind = 2
        return kind, folded_label, folded_url

    def _find_markets(self, postal_code: str) -> tuple[Any, list[tuple[str, str, str]]]:
        try:
            from bs4 import BeautifulSoup
        except Exception as exc:
            raise ToolError(f"REWE benötigt BeautifulSoup: {exc}") from exc

        locality = clean_text(self.locator.locality(postal_code))
        if not locality:
            raise ToolError(f"REWE konnte den Ort zu PLZ {postal_code} nicht bestimmen")
        slug = self._slug(locality)
        if not slug:
            raise ToolError(f"REWE konnte aus {locality!r} keinen Marktsuche-Pfad bilden")

        session = self._session()
        slugs = [slug]
        state_getter = getattr(self.locator, "state", None)
        state = clean_text(state_getter(postal_code)) if callable(state_getter) else ""
        state_slug = self._slug(state)
        if state_slug and state_slug not in slugs:
            slugs.append(state_slug)

        exact: list[tuple[str, str, str]] = []
        # The search page can expose more than one URL/slug for the same store.
        # Only the numeric market id represents an independently selectable market.
        seen_market_ids: set[str] = set()
        successful_pages = 0
        for page_slug in slugs:
            response = session.get(f"{self.BASE}/marktsuche/{page_slug}/", timeout=self.timeout_seconds)
            if response.status_code != 200:
                continue
            successful_pages += 1
            soup = BeautifulSoup(response.text, "html.parser")
            for link in soup.select('a[href*="/angebote/"]'):
                href = urljoin(self.BASE, clean_text(link.get("href")))
                match = re.search(r"/angebote/[^/]+/(\d+)/[^/?#]+/?", href)
                if not match:
                    continue
                market_id = match.group(1)
                if market_id in seen_market_ids:
                    continue

                node = link
                local_text = clean_text(link.get_text(" ", strip=True))
                for _ in range(8):
                    parent = getattr(node, "parent", None)
                    if parent is None:
                        break
                    node = parent
                    offer_links = node.select('a[href*="/angebote/"]') if hasattr(node, "select") else []
                    candidate_text = clean_text(node.get_text(" ", strip=True)) if hasattr(node, "get_text") else ""
                    if len(offer_links) == 1:
                        local_text = candidate_text
                        break
                if postal_code not in local_text:
                    continue
                seen_market_ids.add(market_id)
                exact.append((market_id, href, local_text))

        if not successful_pages:
            raise ToolError("REWE Marktsuche war nicht erreichbar")

        if not exact:
            raise ToolError(f"REWE fand in {locality} keinen Markt mit exakt PLZ {postal_code}")

        exact.sort(key=self._market_rank)
        return session, exact

    def markets(self, postal_code: str) -> list[dict[str, str]]:
        """Return every exact-postcode REWE market available for manual selection."""
        _session, exact = self._find_markets(postal_code)
        return [
            {"market_id": market_id, "market_url": market_url, "label": label}
            for market_id, market_url, label in exact
        ]

    def _find_market(self, postal_code: str, *, use_cache: bool = True, market_id: str = "") -> tuple[Any, str, str, str]:
        requested_market_id = clean_text(market_id)
        if use_cache and not requested_market_id:
            cached = self._cached_market(postal_code)
            if cached is not None:
                cached_id, market_url, label = cached
                return self._session(), cached_id, market_url, label

        session, exact = self._find_markets(postal_code)
        if requested_market_id:
            selected = next((item for item in exact if item[0] == requested_market_id), None)
            if selected is None:
                raise ToolError(f"Der gewählte REWE-Markt gehört nicht zur PLZ {postal_code}")
        else:
            selected = exact[0]

        # A postcode can contain several REWE stores. Keep the choice deterministic
        # instead of depending on the order of links in the market-search page.
        selected_id, market_url, label = selected
        if not requested_market_id:
            self._cache_market(postal_code, selected_id, market_url, label)
        self.last_discovery = "REWE Marktsuche"
        return session, selected_id, market_url, label

    @staticmethod
    def _offer_title(title_node: Any) -> str:
        """Return the visible product title without REWE footnote markers."""
        if title_node is None:
            return ""

        parts: list[str] = []
        for text_node in title_node.find_all(string=True):
            parent = getattr(text_node, "parent", None)
            skip = False
            node = parent
            while node is not None and node is not title_node.parent:
                name = clean_text(getattr(node, "name", "")).casefold()
                attrs = getattr(node, "attrs", {}) or {}
                classes = " ".join(str(value) for value in attrs.get("class", ())) if isinstance(attrs, dict) else ""
                marker = " ".join((
                    classes,
                    clean_text(attrs.get("id", "")) if isinstance(attrs, dict) else "",
                    clean_text(attrs.get("data-testid", "")) if isinstance(attrs, dict) else "",
                    clean_text(attrs.get("href", "")) if isinstance(attrs, dict) else "",
                )).casefold()
                if name == "sup" or "footnote" in marker:
                    skip = True
                    break
                if node is title_node:
                    break
                node = getattr(node, "parent", None)
            if not skip:
                parts.append(str(text_node))

        title = clean_text(" ".join(parts))
        return re.sub(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+$", "", title).strip()

    @classmethod
    def _bonus_amount(cls, card: Any, description: str = "") -> Optional[float]:
        """Return only an explicitly published Euro REWE Bonus amount.

        REWE currently renders the amount either in its loyalty badge or in an
        additional line such as ``MIT APP 0,10 € REWE BONUS``. Percentages,
        points and unspecified app benefits deliberately remain unpriced.
        """
        badge = cls._money(card.select_one(".cor-loyalty-badge") if card is not None else None)
        if badge is not None and badge > 0:
            return badge
        text = clean_text(description)
        for pattern in (
            r"(?:mit\s+app\s+)?(\d+[,.]\d{2})\s*€\s*rewe\s*bonus\b",
            r"\brewe\s*bonus\b[^\d]{0,24}(\d+[,.]\d{2})\s*€",
        ):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                amount = parse_number(match.group(1))
                if amount is not None and amount > 0:
                    return amount
        return None

    def _parse_card(self, card: Any, *, nan: str, category: str, market_id: str, market_url: str, reference_date: Optional[date] = None) -> tuple[Optional[Offer], bool]:
        title_node = card.select_one(".cor-offer-information__title") if card is not None else None
        title = self._offer_title(title_node)
        price = self._money(card.select_one(".cor-offer-price__tag-price") if card is not None else None)
        if not title:
            return None, False

        details = [
            clean_text(node.get_text(" ", strip=True))
            for node in card.select(".cor-offer-information__additional")
            if clean_text(node.get_text(" ", strip=True))
        ]
        description = " ".join(details)
        bonus = self._bonus_amount(card, description)
        if price is None or price <= 0:
            return None, bonus is not None and bonus > 0
        base_price, base_unit = parse_base_price_text(description)
        pack = normalize_pack(f"{title} {description}")
        image_url = self._product_image(card, market_url)
        offer_id = f"rewe:{market_id}:{nan}"
        reference = offer_reference_date(reference_date)
        valid_from = reference.fromordinal(reference.toordinal() - reference.weekday())
        valid_until = valid_from.fromordinal(valid_from.toordinal() + 6)
        product_url = ""
        for link in card.select("a[href]"):
            candidate = urljoin(self.BASE, clean_text(link.get("href")))
            try:
                parsed = urlsplit(candidate)
            except ValueError:
                continue
            if parsed.scheme == "https" and (parsed.hostname or "").casefold() in {"www.rewe.de", "shop.rewe.de"} and any(part in parsed.path.casefold() for part in ("/produkte/", "/produkt/", "/angebote/")):
                product_url = candidate
                break
        return Offer(
            offer_id=offer_id,
            retailer="REWE",
            category=clean_text(category) or "Weitere Angebote",
            name=title,
            brand="",
            description=description,
            price=price,
            base_price=base_price,
            base_unit=base_unit,
            pack_signature=pack,
            validity_label=self._week_label(reference_date),
            match_key=build_match_key("", title, pack, offer_id),
            source_url=market_url,
            product_url=product_url or market_url,
            retailer_url=market_url,
            image_url=image_url,
            deposit=parse_deposit_text(description),
            benefits=(LoyaltyBenefit("rewe_bonus", "cashback", float(bonus), "REWE Bonus"),)
            if bonus is not None and bonus > 0
            else (),
            valid_from=valid_from.isoformat(),
            valid_until=valid_until.isoformat(),
        ), False

    def load(self, postal_code: str, market_id: str = "", offer_week: str = "current") -> list[Offer]:
        try:
            from bs4 import BeautifulSoup
        except Exception as exc:
            raise ToolError(f"REWE benötigt BeautifulSoup: {exc}") from exc

        requested_market_id = clean_text(market_id)
        session, market_id, market_url, market_label = self._find_market(postal_code, market_id=requested_market_id)
        requested_week = normalize_offer_week(offer_week)
        reference_date = offer_week_reference(requested_week)
        target_week = "next" if requested_week == "next" else self._target_week()
        if requested_week == "next":
            separator = "&" if "?" in market_url else "?"
            request_url = f"{market_url}{separator}week=next"
        else:
            request_url = self._market_week_url(market_url)
        response = session.get(request_url, timeout=self.timeout_seconds)
        if response.status_code != 200 and self.last_discovery == "24h-Marktcache" and not requested_market_id:
            self._drop_cached_market(postal_code)
            session, market_id, market_url, market_label = self._find_market(postal_code, use_cache=False)
            if requested_week == "next":
                separator = "&" if "?" in market_url else "?"
                request_url = f"{market_url}{separator}week=next"
            else:
                request_url = self._market_week_url(market_url)
            response = session.get(request_url, timeout=self.timeout_seconds)
        if response.status_code != 200:
            raise ToolError(f"REWE Angebotsseite HTTP {response.status_code}")
        soup = BeautifulSoup(response.text, "html.parser")
        root = self._best_offer_root(soup, target_week, request_url)
        unique, rendered = self._collect_offer_cards(root, market_id) if root is not None else ({}, {})

        if not unique:
            rendered_page = self._render_market_page(request_url)
            soup = BeautifulSoup(rendered_page, "html.parser")
            root = self._best_offer_root(soup, target_week, request_url)
            unique, rendered = self._collect_offer_cards(root, market_id) if root is not None else ({}, {})

        if root is None:
            raise ToolError(f"REWE {target_week.upper()}-Bereich wurde nicht gefunden")
        if not unique:
            raise ToolError(f"REWE {target_week.upper()}-Bereich enthielt keine auswertbaren Angebotskarten")

        cards = dict(rendered)
        missing = [item for nan, item in unique.items() if nan not in cards]
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Rd-Client-Href": request_url,
            "Origin": self.BASE,
            "Referer": request_url,
        }
        for offset in range(0, len(missing), 25):
            chunk = missing[offset:offset + 25]
            payload = []
            id_to_nan: dict[str, str] = {}
            for item in chunk:
                request_id = str(uuid.uuid4())
                id_to_nan[request_id] = item["nan"]
                payload.append({
                    "id": request_id,
                    "namespace": "cor",
                    "name": "offer-tile-by-nan",
                    "params": {"nan": item["nan"]},
                    "query": {
                        "wwIdent": item["wwident"],
                        "showDuration": "auto",
                        "showFootnotes": "",
                        "enableDetailDeeplink": "true",
                        "enablePerformanceMark": "",
                        "heroStyles": "false",
                    },
                })
            result = session.post(self.INCLUDE_ENDPOINT, headers=headers, json=payload, timeout=self.timeout_seconds)
            if result.status_code != 200:
                raise ToolError(f"REWE frontend-includes HTTP {result.status_code}")
            try:
                body = result.json()
            except Exception as exc:
                raise ToolError(f"REWE frontend-includes lieferte kein JSON: {exc}") from exc
            if not isinstance(body, list):
                raise ToolError("REWE frontend-includes lieferte kein Array")
            for item in body:
                if not isinstance(item, dict):
                    continue
                nan = id_to_nan.get(clean_text(item.get("id")))
                content = item.get("content")
                if not nan or not isinstance(content, str) or not content.strip():
                    continue
                card_soup = BeautifulSoup(content, "html.parser")
                card = card_soup.select_one(".cor-offer-renderer-tile") or card_soup
                cards[nan] = card

        offers: list[Offer] = []
        bonus_only = 0
        unknown = 0
        for nan, meta in unique.items():
            card = cards.get(nan)
            if card is None:
                unknown += 1
                continue
            offer, is_bonus_only = self._parse_card(
                card,
                nan=nan,
                category=meta["category"],
                market_id=market_id,
                market_url=market_url,
                reference_date=reference_date,
            )
            if is_bonus_only:
                bonus_only += 1
            elif offer is None:
                unknown += 1
            else:
                offers.append(offer)

        self.last_market_id = market_id
        self.last_market_label = market_label
        self.last_market_url = market_url
        self.last_current_count = len(unique)
        self.last_bonus_only_count = bonus_only
        self.last_unknown_count = unknown
        if not offers:
            detail = f"; {unknown} Karten konnten nicht ausgewertet werden" if unknown else ""
            raise ToolError(f"REWE {postal_code}: keine auswertbaren aktuellen Angebote{detail}")
        return deduplicate_offers(offers)
