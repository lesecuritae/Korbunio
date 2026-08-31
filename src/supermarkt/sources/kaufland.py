from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from html.parser import HTMLParser
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..common import build_match_key, clean_text, normalize_pack, offer_week_reference, parse_base_price_text, parse_number, strip_html, today_berlin
from ..http import HttpClient, PostalCodeLocator
from ..images import is_rejected_image_url, normalize_image_url
from ..models import LoyaltyBenefit, Offer, ToolError
from .browser import chromium_command

class KauflandOfficialAnchorParser(HTMLParser):
    IMAGE_ATTRS = (
        "data-src",
        "data-lazy-src",
        "data-original",
        "data-srcset",
        "srcset",
        "src",
    )

    def __init__(self, source_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source_url = source_url
        self.cards: list[dict[str, Any]] = []
        self.page_text_parts: list[str] = []
        self._depth = 0
        self._current: Optional[dict[str, Any]] = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, Optional[str]]],
    ) -> None:
        tag = tag.casefold()
        attributes = {
            key.casefold(): clean_text(value)
            for key, value in attrs
            if key
        }
        if tag == "a":
            if self._depth == 0:
                self._current = {
                    "href": clean_text(attributes.get("href", "")),
                    "image_url": "",
                    "text_parts": [],
                }
            self._depth += 1
        if self._current is None or tag not in {"img", "source"}:
            return
        for field in self.IMAGE_ATTRS:
            raw = clean_text(attributes.get(field))
            if not raw:
                continue
            if "srcset" in field:
                raw = raw.split(",", 1)[0].strip().split(" ", 1)[0]
            candidate = normalize_image_url(raw, base_url=self.source_url)
            if candidate and not is_rejected_image_url(candidate):
                self._current["image_url"] = candidate
                break

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._depth <= 0:
            return
        self._depth -= 1
        if self._depth == 0 and self._current is not None:
            self.cards.append(self._current)
            self._current = None

    def handle_data(self, data: str) -> None:
        value = clean_text(data)
        if not value:
            return
        if len(self.page_text_parts) < 20000:
            self.page_text_parts.append(value)
        if self._current is not None:
            parts = self._current["text_parts"]
            if len(parts) < 160 and sum(len(part) for part in parts) < 12000:
                parts.append(value)

    def finish(self) -> None:
        if self._current is not None:
            self.cards.append(self._current)
            self._current = None
            self._depth = 0

    @property
    def page_text(self) -> str:
        return clean_text(" ".join(self.page_text_parts))

class OfficialKauflandSource:
    STORE_HOST = "filiale.kaufland.de"
    SITEMAP_URLS = (
        "https://filiale.kaufland.de/.sitemap.xml",
        "https://filiale.kaufland.de/sitemap.xml",
    )
    CURRENT_OVERVIEW_URL = "https://filiale.kaufland.de/angebote/uebersicht.html?kloffer-week=current"
    NEXT_OVERVIEW_URL = "https://filiale.kaufland.de/angebote/naechste-woche.html"

    def __init__(
        self,
        http: HttpClient,
        locator: PostalCodeLocator,
        timeout_seconds: int = 45,
        *,
        cache_dir: Optional[Path] = None,
        store_cache_ttl_seconds: int = 86400,
    ) -> None:
        self.http = http
        self.locator = locator
        self.timeout_seconds = max(10, min(int(timeout_seconds), 90))
        self.last_store_url = ""
        self.last_store_postal_code = ""
        self.last_locality = ""
        self.last_discovery = ""
        self._store_urls_cache: Optional[list[str]] = None
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else None
        self.store_cache_ttl_seconds = max(300, min(int(store_cache_ttl_seconds), 7 * 86400))
        self._cache_lock = threading.RLock()
        self._profile_locks: dict[str, threading.RLock] = {}
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_html(
        self,
        url: str,
        *,
        required_any: tuple[str, ...] = (),
        profile_dir: str = "",
    ) -> str:
        errors: list[str] = []
        required = tuple(item.casefold() for item in required_any if item)
        if not profile_dir:
            try:
                payload = self.http.get_bytes(url, headers={"Accept": "text/html,application/xhtml+xml"})
                if len(payload) <= 5_000_000:
                    page = payload.decode("utf-8", errors="replace")
                    folded = page.casefold()
                    if "<html" in folded and (not required or any(marker in folded for marker in required)):
                        return page
                errors.append("HttpClient: unvollständige HTML-Antwort")
            except Exception as exc:
                errors.append(f"HttpClient: {type(exc).__name__}: {exc}")
        base = [
            chromium_command(),
            "--disable-crashpad-for-testing",
            "--single-process",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--disable-dev-shm-usage",
            "--lang=de-DE",
            "--window-size=1365,900",
            "--virtual-time-budget=12000",
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "--dump-dom",
            url,
        ]
        profile_arg = f"--user-data-dir={profile_dir}" if profile_dir else ""
        for headless in ("--headless=new", "--headless"):
            command = [base[0], headless]
            if profile_arg:
                command.append(profile_arg)
            command.extend(base[1:])
            try:
                completed = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                errors.append(f"{headless}: {type(exc).__name__}: {exc}")
                continue
            page = completed.stdout or ""
            folded = page.casefold()
            valid = "<html" in folded
            if valid and required:
                valid = any(marker in folded for marker in required)
            if valid:
                return page
            detail = clean_text((completed.stderr or "")[-800:])
            errors.append(f"{headless}: rc={completed.returncode}" + (f" {detail}" if detail else ""))
        raise ToolError("Offizielle Kaufland-Seite konnte nicht geladen werden: " + " | ".join(errors[-2:]))

    def _fetch_text(self, url: str) -> str:
        errors: list[str] = []
        try:
            data = self.http.get_bytes(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                    "Accept": "application/xml,text/xml,text/plain,*/*;q=0.8",
                },
            )
            text = data.decode("utf-8", errors="replace")
            if "<loc" in text.casefold():
                return text
            errors.append("HttpClient: XML ohne <loc>")
        except Exception as exc:
            errors.append(f"HttpClient: {type(exc).__name__}: {exc}")
        try:
            completed = subprocess.run(
                [
                    "curl", "-fsSL", "--max-time", str(self.timeout_seconds),
                    "-A", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
                    "-H", "Accept: application/xml,text/xml,text/plain,*/*;q=0.8", url,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds + 5,
                check=False,
            )
            text = completed.stdout or ""
            if completed.returncode == 0 and "<loc" in text.casefold():
                return text
            errors.append(f"curl: rc={completed.returncode} " + clean_text((completed.stderr or "")[-500:]))
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"curl: {type(exc).__name__}: {exc}")
        raise ToolError(f"Kaufland-Sitemap nicht abrufbar ({url}): " + " | ".join(errors[-2:]))

    @staticmethod
    def _flatten_context(value: Any) -> list[str]:
        result: list[str] = []
        seen: set[int] = set()
        def walk(item: Any, depth: int = 0) -> None:
            if item is None or depth > 4:
                return
            if isinstance(item, (str, int, float)):
                cleaned = clean_text(item)
                if cleaned:
                    result.append(cleaned)
                return
            marker = id(item)
            if marker in seen:
                return
            seen.add(marker)
            if isinstance(item, dict):
                for key, child in item.items():
                    if clean_text(key):
                        result.append(clean_text(key))
                    walk(child, depth + 1)
                return
            if isinstance(item, (list, tuple, set)):
                for child in item:
                    walk(child, depth + 1)
                return
            if hasattr(item, "model_dump"):
                try:
                    walk(item.model_dump(), depth + 1)
                    return
                except Exception:
                    pass
            if hasattr(item, "__dict__"):
                try:
                    walk(vars(item), depth + 1)
                    return
                except Exception:
                    pass
            rendered = clean_text(str(item))
            if rendered:
                result.append(rendered)
        walk(value)
        return list(dict.fromkeys(result))

    @staticmethod
    def _slug_words(value: str) -> list[str]:
        folded = clean_text(value).casefold()
        folded = folded.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        return [
            token for token in re.findall(r"[a-z0-9]+", folded)
            if len(token) >= 3 and token not in {"der", "die", "das", "und", "kaufland", "filiale", "service", "html"}
        ]

    @staticmethod
    def _postal_prefix_score(requested: str, candidate: str) -> int:
        if not re.fullmatch(r"\d{5}", requested or "") or not re.fullmatch(r"\d{5}", candidate or ""):
            return 0
        common = 0
        for left, right in zip(requested, candidate, strict=True):
            if left != right:
                break
            common += 1
        base = {5: 10000, 4: 3500, 3: 1400, 2: 350, 1: 50}.get(common, 0)
        if common >= 2:
            base += max(0, 250 - abs(int(requested) - int(candidate)))
        return base

    @staticmethod
    def _store_postal_code(page_text: str) -> str:
        head = page_text.split("Diese Filiale gehört", 1)[0]
        matches = re.findall(r"\b\d{5}\b", head)
        return matches[0] if matches else ""

    @staticmethod
    def _candidate_url(raw_url: str) -> str:
        try:
            parsed = urlsplit(clean_text(raw_url))
        except ValueError:
            return ""
        host = (parsed.hostname or "").casefold()
        path = parsed.path or "/"
        folded = path.casefold()
        if host != OfficialKauflandSource.STORE_HOST:
            return ""
        if not folded.startswith(("/service/filiale/", "/service/filiale.storename%3d")):
            return ""
        if folded.rstrip("/") in {"/service/filiale", "/service/filiale/"}:
            return ""
        return urlunsplit(("https", OfficialKauflandSource.STORE_HOST, path, "", ""))

    def _sitemap_store_urls(self) -> list[str]:
        if self._store_urls_cache is not None:
            return list(self._store_urls_cache)
        queue = list(self.SITEMAP_URLS)
        seen_docs: set[str] = set()
        stores: list[str] = []
        errors: list[str] = []
        while queue and len(seen_docs) < 16:
            current = queue.pop(0)
            if current in seen_docs:
                continue
            seen_docs.add(current)
            try:
                xml_text = self._fetch_text(current)
            except Exception as exc:
                errors.append(f"{current}: {type(exc).__name__}: {exc}")
                continue
            for raw in re.findall(r"<loc[^>]*>\s*(.*?)\s*</loc>", xml_text, flags=re.IGNORECASE | re.DOTALL):
                loc = clean_text(html.unescape(raw))
                if not loc:
                    continue
                candidate = self._candidate_url(loc)
                if candidate:
                    stores.append(candidate)
                    continue
                try:
                    parsed = urlsplit(loc)
                except ValueError:
                    continue
                host = (parsed.hostname or "").casefold()
                if host == self.STORE_HOST and (parsed.path or "").casefold().endswith(".xml"):
                    if loc not in seen_docs and loc not in queue:
                        queue.append(loc)
        stores = list(dict.fromkeys(stores))
        if stores:
            self._store_urls_cache = stores
            self.last_discovery = f"offizielle Sitemap ({len(stores)} Filialseiten)"
            return list(stores)
        detail = " | ".join(errors[:4]) if errors else "keine Filial-URLs in der Sitemap"
        raise ToolError("Kaufland-Sitemap lieferte keine Filialseiten: " + detail)


    def _search_store_candidates(self, postal_code: str, retailer_context: Any = None) -> tuple[str, list[tuple[int, str]]]:
        locality = clean_text(self.locator.locality(postal_code))
        if not locality:
            raise ToolError("Kaufland konnte den Ort zur Postleitzahl nicht bestimmen")
        context_values = self._flatten_context(retailer_context)
        context_text = " ".join(context_values)
        locality_words = self._slug_words(locality)
        context_words = [word for word in self._slug_words(context_text) if word not in locality_words][:12]
        scored: dict[str, int] = {}
        order: dict[str, int] = {}
        result_index = 0
        for value in context_values:
            candidate = self._candidate_url(value)
            if candidate:
                scored[candidate] = max(scored.get(candidate, 0), 25000)
                order.setdefault(candidate, result_index)
                result_index += 1
        try:
            sitemap_urls = self._sitemap_store_urls()
        except Exception:
            sitemap_urls = []
        for url in sitemap_urls:
            path_words = set(self._slug_words(urlsplit(url).path))
            locality_hits = sum(1 for word in locality_words if word in path_words)
            score = 6000 if locality_words and locality_hits == len(set(locality_words)) else locality_hits * 1200
            score += sum(250 for word in context_words if word in path_words)
            if score <= 0:
                continue
            score += max(0, 100 - result_index)
            if url not in scored or score > scored[url]:
                scored[url] = score
                order[url] = result_index
            result_index += 1
        if not scored:
            raise ToolError(f"Kaufland fand für {postal_code} {locality} keine offizielle Filialseite")
        candidates = sorted(((score, url) for url, score in scored.items()), key=lambda item: (-item[0], order.get(item[1], 999999), item[1]))
        return locality, candidates[:24]

    @property
    def _store_cache_path(self) -> Optional[Path]:
        return self.cache_dir / "store-map.json" if self.cache_dir is not None else None

    def _profile_dir(self, selector: str) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", clean_text(selector))
        return self.cache_dir / "profiles" / safe

    @staticmethod
    def _profile_marker(profile_dir: Path) -> Path:
        return profile_dir / ".supermarkt-store-selection.json"

    def _profile_lock(self, selector: str) -> threading.RLock:
        key = clean_text(selector).casefold()
        with self._cache_lock:
            lock = self._profile_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._profile_locks[key] = lock
            return lock

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
            expired_selectors: set[str] = set()
            for postal, item in list(mapping.items()):
                try:
                    expires_at = float(item.get("expires_at", 0))
                except (TypeError, ValueError):
                    expires_at = 0
                if expires_at > current:
                    continue
                selector = clean_text(item.get("selector", ""))
                if selector:
                    expired_selectors.add(selector)
                mapping.pop(postal, None)
                changed = True
            active_selectors = {
                clean_text(item.get("selector", ""))
                for item in mapping.values()
                if isinstance(item, dict) and clean_text(item.get("selector", ""))
            }
            for selector in expired_selectors - active_selectors:
                profile_dir = self._profile_dir(selector)
                if profile_dir is not None:
                    shutil.rmtree(profile_dir, ignore_errors=True)
            if changed:
                self._write_store_map(mapping)
            return mapping

    def _cached_store(self, postal_code: str) -> Optional[tuple[str, str, str]]:
        code = clean_text(postal_code)
        mapping = self._cleanup_store_cache()
        item = mapping.get(code)
        if not isinstance(item, dict):
            return None
        store_url = self._candidate_url(clean_text(item.get("store_url", "")))
        locality = clean_text(item.get("locality", ""))
        store_postal = clean_text(item.get("store_postal", ""))
        selector = clean_text(item.get("selector", ""))
        if not store_url or not locality or not selector or selector != self._store_selector(store_url):
            self._drop_cached_store(code)
            return None
        self.last_discovery = "24h-Filialcache"
        return store_url, locality, store_postal

    def _cache_store(self, postal_code: str, store_url: str, locality: str, store_postal: str) -> None:
        if self.cache_dir is None:
            return
        code = clean_text(postal_code)
        selector = self._store_selector(store_url)
        if not code or not selector:
            return
        now = time.time()
        with self._cache_lock:
            mapping = self._cleanup_store_cache(now)
            mapping[code] = {
                "store_url": store_url,
                "locality": clean_text(locality),
                "store_postal": clean_text(store_postal),
                "selector": selector,
                "created_at": now,
                "expires_at": now + self.store_cache_ttl_seconds,
            }
            self._write_store_map(mapping)

    def _drop_cached_store(self, postal_code: str) -> None:
        if self.cache_dir is None:
            return
        code = clean_text(postal_code)
        with self._cache_lock:
            mapping = self._read_store_map()
            item = mapping.pop(code, None)
            if item is not None:
                self._write_store_map(mapping)
                selector = clean_text(item.get("selector", "")) if isinstance(item, dict) else ""
                still_used = any(
                    isinstance(other, dict) and clean_text(other.get("selector", "")) == selector
                    for other in mapping.values()
                )
                profile_dir = self._profile_dir(selector) if selector and not still_used else None
                if profile_dir is not None:
                    shutil.rmtree(profile_dir, ignore_errors=True)

    def _profile_is_fresh(self, profile_dir: Path, selector: str) -> bool:
        marker = self._profile_marker(profile_dir)
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            selected_at = float(value.get("selected_at", 0))
        except (OSError, ValueError, TypeError, AttributeError):
            return False
        return (
            clean_text(value.get("selector", "")) == clean_text(selector)
            and selected_at + self.store_cache_ttl_seconds > time.time()
        )

    def _mark_profile_selected(self, profile_dir: Path, selector: str) -> None:
        marker = self._profile_marker(profile_dir)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps({"selector": clean_text(selector), "selected_at": time.time()}, separators=(",", ":")),
            encoding="utf-8",
        )

    def _resolve_store_page(self, postal_code: str, retailer_context: Any = None) -> tuple[str, str, str, str]:
        cached = self._cached_store(postal_code)
        if cached is not None:
            store_url, locality, store_postal = cached
            return store_url, "", locality, store_postal
        locality, candidates = self._search_store_candidates(postal_code, retailer_context)
        context_values = self._flatten_context(retailer_context)
        context_text = " ".join(context_values)
        context_words = [word for word in self._slug_words(context_text) if word not in self._slug_words(locality)][:12]
        context_postals = list(dict.fromkeys(re.findall(r"\b\d{5}\b", context_text)))
        best: Optional[tuple[int, str, str, str]] = None
        errors: list[str] = []
        for search_score, url in candidates[:20]:
            try:
                page = self._get_html(url, required_any=("aktuelle angebote und prospekte deiner filiale", "unsere knüller der woche"))
            except Exception as exc:
                errors.append(f"{urlsplit(url).path}: {type(exc).__name__}: {exc}")
                continue
            page_text = strip_html(page)
            folded = page_text.casefold()
            if "kaufland" not in folded or "filiale" not in folded:
                continue
            store_postal = self._store_postal_code(page_text)
            score = search_score + self._postal_prefix_score(postal_code, store_postal)
            for context_postal in context_postals:
                score += 20000 if context_postal == store_postal else 2 * self._postal_prefix_score(context_postal, store_postal)
            if locality.casefold() in folded:
                score += 700
            if "aktuelle angebote und prospekte deiner filiale" in folded:
                score += 400
            if "gültig vom" in folded:
                score += 150
            folded_words = set(self._slug_words(folded))
            for word in context_words:
                if word in folded_words:
                    score += 350
            candidate = (score, url, page, store_postal)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            detail = " | ".join(errors[:6]) if errors else "keine Kandidatenseite war nutzbar"
            raise ToolError(f"Kaufland konnte für {postal_code} {locality} keine Filialseite bestätigen: {detail}")
        _score, url, page, store_postal = best
        self._cache_store(postal_code, url, locality, store_postal)
        return url, page, locality, store_postal


    @staticmethod
    def _store_selector(store_url: str) -> str:
        try:
            path = urlsplit(store_url).path
        except ValueError:
            return ""
        match = re.search(r"-(\d+)\.html$", path)
        return f"DE{match.group(1)}" if match else ""

    @classmethod
    def _overview_url(cls, day: Optional[date] = None) -> str:
        # Kaufland's weekly cycle is Thursday through Wednesday. On Sunday the
        # application's Monday reference date still belongs to the current
        # Kaufland week, so jumping to the preview page would skip Mon-Wed.
        _ = day
        return cls.CURRENT_OVERVIEW_URL

    @staticmethod
    def _anchor_week(anchor: Any) -> str:
        href = clean_text(anchor.get("href", "")) if hasattr(anchor, "get") else ""
        if not href:
            return ""
        try:
            values = parse_qs(urlsplit(href).query).get("kloffer-week", [])
        except ValueError:
            return ""
        return clean_text(values[0]).casefold() if values else ""

    @staticmethod
    def _article_id(href: str) -> str:
        try:
            values = parse_qs(urlsplit(clean_text(href)).query).get("kloffer-articleID", [])
        except ValueError:
            return ""
        return clean_text(values[0]) if values else ""

    @classmethod
    def _offer_section_html(cls, page: str, *, week: str = "current") -> str:
        """Return only the selected week's primary offer block.

        Kaufland keeps additional offer material in the rendered DOM. That can
        include XTRA sections and, depending on the client-side render state,
        offer links for another week. ``chromium --dump-dom`` serializes hidden
        DOM as well, so parsing every priced anchor can otherwise count both
        weeks. Explicit ``kloffer-week`` links are therefore filtered to the
        requested week before cards are parsed.
        """
        target_week = clean_text(week).casefold() or "current"
        soup = BeautifulSoup(page, "html.parser")
        heading = None
        for candidate in soup.find_all(("h1", "h2")):
            label = clean_text(candidate.get_text(" ", strip=True)).casefold()
            if label == "aktuelle angebote":
                heading = candidate
                break
        if heading is None:
            raise ToolError("Kaufland-Angebotsübersicht enthält keinen Bereich 'Aktuelle Angebote'")

        anchors: list[str] = []
        stop_headings = (
            "aktuelle angebote im prospekt",
            "aktuelle kaufland card xtra angebote",
            "kaufland card xtra angebote",
            "weitere prospekte",
        )
        for node in heading.find_all_next(("h1", "h2", "a")):
            if node.name in {"h1", "h2"}:
                label = clean_text(node.get_text(" ", strip=True)).casefold()
                if any(label.startswith(prefix) for prefix in stop_headings):
                    break
                # Category headings inside the weekly grid are not section
                # boundaries and must not truncate the catalogue.
                continue
            if node.name != "a":
                continue
            anchor_week = cls._anchor_week(node)
            if anchor_week and anchor_week != target_week:
                continue
            anchors.append(str(node))
        if not anchors:
            raise ToolError("Kaufland-Bereich 'Aktuelle Angebote' enthält keine Angebotskarten")
        return "<html><body>" + "".join(anchors) + "</body></html>"

    def _load_full_overview(self, store_url: str, locality: str) -> tuple[str, str]:
        selector = self._store_selector(store_url)
        if not selector:
            raise ToolError(f"Kaufland-Filialkennung fehlt in {store_url}")

        persistent_profile = self._profile_dir(selector)
        temporary_profile = persistent_profile is None
        if temporary_profile:
            profile_dir = Path(tempfile.mkdtemp(prefix="kaufland-profile-"))
        else:
            profile_dir = persistent_profile
            profile_dir.parent.mkdir(parents=True, exist_ok=True)

        selector_url = (
            "https://filiale.kaufland.de/service/"
            f"filiale.storeName%3D{quote(selector)}.html"
        )
        overview_url = self._overview_url()

        def select_store() -> None:
            if profile_dir.exists():
                shutil.rmtree(profile_dir, ignore_errors=True)
            profile_dir.mkdir(parents=True, exist_ok=True)
            self._get_html(
                selector_url,
                required_any=(locality, selector, "Deine Filiale"),
                profile_dir=str(profile_dir),
            )
            if not temporary_profile:
                self._mark_profile_selected(profile_dir, selector)

        lock = self._profile_lock(selector)
        try:
            with lock:
                if temporary_profile or not self._profile_is_fresh(profile_dir, selector):
                    select_store()
                try:
                    page = self._get_html(
                        overview_url,
                        required_any=("Aktuelle Angebote", "Topartikel", "Weitere Angebote anzeigen"),
                        profile_dir=str(profile_dir),
                    )
                except ToolError:
                    # A cached Chromium profile can become unusable before the
                    # 24h TTL (cookie/session invalidated, interrupted browser
                    # write, etc.). Re-select the store once and retry.
                    if temporary_profile:
                        raise
                    select_store()
                    page = self._get_html(
                        overview_url,
                        required_any=("Aktuelle Angebote", "Topartikel", "Weitere Angebote anzeigen"),
                        profile_dir=str(profile_dir),
                    )
                if "aktuelle angebote" not in page.casefold():
                    raise ToolError("Kaufland-Angebotsübersicht enthält keinen aktuellen Angebotsblock")
                return page, overview_url
        finally:
            if temporary_profile:
                shutil.rmtree(profile_dir, ignore_errors=True)

    @staticmethod
    def _price_marker(segment: str):
        matches = list(re.finditer(r"(?:\bnur\s*|-\s*\d{1,2}\s*%\s*)(\d{1,4}[,.]\d{2})\b", segment, flags=re.IGNORECASE))
        return matches[-1] if matches else None

    @staticmethod
    def _validity_label(page_text: str) -> str:
        match = re.search(r"Gültig\s+vom\s+(\d{1,2})\.(\d{1,2})\.\s+bis\s+(\d{1,2})\.(\d{1,2})\.", page_text, flags=re.IGNORECASE)
        if not match:
            return f"Kaufland, Abruf {today_berlin():%d.%m.%Y}"
        day1, month1, day2, month2 = (int(value) for value in match.groups())
        year = today_berlin().year
        return f"Kaufland, gültig {day1:02d}.{month1:02d}.{year} bis {day2:02d}.{month2:02d}.{year}"

    def _card_to_offer(self, card: dict[str, Any], index: int, validity_label: str, source_url: str) -> Optional[Offer]:
        text = clean_text(" ".join(clean_text(part) for part in card.get("text_parts", []) if clean_text(part)))
        if not text or len(text) > 1200:
            return None
        xtra_split = re.search(r"\bMit\s+Kaufland\s+Card\s+XTRA\b", text, flags=re.IGNORECASE)
        if xtra_split:
            regular_text = text[:xtra_split.start()]
            xtra_text = text[xtra_split.end():]
        else:
            regular_text = text
            xtra_text = ""
        price_match = self._price_marker(regular_text)
        if price_match is None:
            return None
        price = parse_number(price_match.group(1))
        if price is None or price <= 0:
            return None
        xtra_price = None
        if xtra_text:
            xtra_match = self._price_marker(xtra_text)
            if xtra_match is not None:
                xtra_price = parse_number(xtra_match.group(1))
                if xtra_price is not None and xtra_price <= 0:
                    xtra_price = None
        left = clean_text(regular_text[:price_match.start()])
        left = re.sub(r"^(?:KNÜLLER|AKTION)\s+", "", left, flags=re.IGNORECASE)
        name_match = re.search(r"\s+je\s+", left, flags=re.IGNORECASE)
        if name_match:
            name = clean_text(left[:name_match.start()])
            description = clean_text(left[name_match.end():])
        else:
            name = left
            description = ""
        name = re.sub(r"^[*•\s]+|[*•\s]+$", "", name)
        if not name or len(name) < 2 or len(name) > 240:
            return None
        if name.casefold() in {"weitere angebote anzeigen", "aktuelle angebote", "topartikel", "zeige alle angebote"}:
            return None
        base_price, base_unit = parse_base_price_text(text)
        pack = normalize_pack(f"{name} {description}")
        image_url = normalize_image_url(card.get("image_url", ""), base_url=source_url)
        if is_rejected_image_url(image_url):
            image_url = ""
        identifier = f"kaufland-official:{name.casefold()}:{price}:{xtra_price if xtra_price is not None else ''}"
        return Offer(
            offer_id=f"kaufland-official:{index}:{name}:{price}", retailer="Kaufland", category="Kaufland Filialangebote",
            name=name, brand="", description=description, price=price, base_price=base_price,
            base_unit=base_unit, pack_signature=pack, validity_label=validity_label,
            match_key=build_match_key("", name, pack, identifier), source_url=source_url, image_url=image_url,
            benefits=(LoyaltyBenefit("kaufland_xtra", "direct_price", float(xtra_price), "Kaufland Card XTRA"),)
            if xtra_price is not None else (),
        )

    def _parse_page(self, page: str, source_url: str) -> list[Offer]:
        section_html = self._offer_section_html(page, week="current")
        parser = KauflandOfficialAnchorParser(source_url)
        parser.feed(section_html)
        parser.close()
        parser.finish()
        validity_label = self._validity_label(strip_html(page))
        offers: list[Offer] = []
        seen_article_ids: set[str] = set()
        seen_fallback: set[tuple[object, ...]] = set()
        for index, card in enumerate(parser.cards, start=1):
            offer = self._card_to_offer(card, index, validity_label, source_url)
            if offer is None:
                continue
            article_id = self._article_id(clean_text(card.get("href", "")))
            if article_id:
                if article_id in seen_article_ids:
                    continue
                seen_article_ids.add(article_id)
            else:
                key = (
                    offer.name.casefold(),
                    float(offer.price),
                    tuple((b.program_id, b.kind, b.value) for b in offer.benefits),
                    offer.pack_signature,
                )
                if key in seen_fallback:
                    continue
                seen_fallback.add(key)
            offers.append(offer)
        return offers

    def _load_structured_offers(self, store_url: str, offer_week: str = "current") -> list[Offer]:
        selector = self._store_selector(store_url)
        if not selector:
            raise ToolError(f"Kaufland-Filialkennung fehlt in {store_url}")
        availability_url = f"https://filiale.kaufland.de/.kloffers.storeName={selector}.json"
        try:
            availability = json.loads(
                self.http.get_bytes(availability_url, {"Accept": "application/json"}).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolError("Kaufland-Verfügbarkeitsdaten sind ungültig") from exc
        if not isinstance(availability, list):
            raise ToolError("Kaufland-Verfügbarkeitsdaten haben ein unerwartetes Format")

        reference = offer_week_reference(offer_week).isoformat()
        available_ids = {
            clean_text(item.get("klNr"))
            for item in availability
            if isinstance(item, dict)
            and clean_text(item.get("klNr"))
            and clean_text(item.get("dateFrom")) <= reference <= clean_text(item.get("dateTo"))
        }
        overview_url = self._overview_url()
        page = self.http.get_bytes(overview_url, {"Accept": "text/html,application/xhtml+xml"}).decode(
            "utf-8", errors="replace"
        )
        marker = '{"component":"OfferTemplate"'
        start = page.find(marker)
        if start < 0:
            raise ToolError("Kaufland-Angebotsseite enthält keine strukturierten Angebotsdaten")
        try:
            payload, _end = json.JSONDecoder().raw_decode(page[start:])
            cycles = payload["props"]["offerData"]["cycles"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ToolError("Kaufland-Angebotsdaten haben ein unerwartetes Format") from exc

        result: list[Offer] = []
        seen: set[str] = set()
        # The later cycle contains Card-XTRA variants of otherwise identical
        # offer IDs. Process it first so the conditional member price survives
        # deduplication while the regular shelf price remains ``price``.
        for cycle in reversed(cycles) if isinstance(cycles, list) else []:
            for category in cycle.get("categories", []) if isinstance(cycle, dict) else []:
                if not isinstance(category, dict):
                    continue
                category_name = clean_text(category.get("displayName")) or "Kaufland Filialangebote"
                for raw in category.get("offers", []):
                    if not isinstance(raw, dict) or clean_text(raw.get("klNr")) not in available_ids:
                        continue
                    valid_from = clean_text(raw.get("dateFrom"))
                    valid_until = clean_text(raw.get("dateTo"))
                    if not valid_from or not valid_until or not (valid_from <= reference <= valid_until):
                        continue
                    offer_id = clean_text(raw.get("offerId"))
                    if not offer_id or offer_id in seen:
                        continue
                    seen.add(offer_id)
                    title = clean_text(raw.get("title"))
                    subtitle = clean_text(raw.get("subtitle"))
                    name = clean_text(f"{title} {subtitle}")
                    price = parse_number(raw.get("formattedPrice") or raw.get("price"))
                    if not name or price is None or price <= 0:
                        continue
                    unit = clean_text(raw.get("unit"))
                    description = clean_text(raw.get("detailDescription"))
                    base_text = clean_text(raw.get("formattedBasePrice") or raw.get("basePrice"))
                    base_price, base_unit = parse_base_price_text(base_text)
                    pack = normalize_pack(f"{name} {unit}")
                    image_url = normalize_image_url(raw.get("listImage", ""), base_url=overview_url)
                    if is_rejected_image_url(image_url):
                        image_url = ""
                    loyalty_text = re.sub(r"[^\d,.-]", "", clean_text(raw.get("loyaltyFormattedPrice")))
                    loyalty_price = parse_number(loyalty_text)
                    benefits = ()
                    if loyalty_price is not None and 0 < loyalty_price < price:
                        benefits = (LoyaltyBenefit("kaufland_xtra", "direct_price", loyalty_price, "Kaufland Card XTRA"),)
                    result.append(Offer(
                        offer_id=f"kaufland-official:{offer_id}", retailer="Kaufland", category=category_name,
                        name=name, brand=title if subtitle else "", description=description, price=price,
                        base_price=base_price, base_unit=base_unit, pack_signature=pack,
                        validity_label=f"Kaufland, gültig {valid_from} bis {valid_until}",
                        match_key=build_match_key(title if subtitle else "", name, pack, offer_id),
                        source_url=overview_url, image_url=image_url, retailer_url=store_url,
                        coverage_note=f"Offizielle Filialangebote für {selector}", benefits=benefits,
                        valid_from=valid_from, valid_until=valid_until,
                    ))
        if len(result) < 100:
            raise ToolError(f"Kaufland-Strukturdaten für {selector} lieferten nur {len(result)} Angebote")
        return result

    def load(self, postal_code: str, retailer_context: Any = None, offer_week: str = "current") -> list[Offer]:
        store_url, _store_page, locality, store_postal = self._resolve_store_page(postal_code, retailer_context)
        used_cached_store = self.last_discovery == "24h-Filialcache"
        try:
            offers = self._load_structured_offers(store_url, offer_week)
        except ToolError:
            try:
                overview_page, overview_url = self._load_full_overview(store_url, locality)
                offers = self._parse_page(overview_page, overview_url)
            except ToolError:
                if not used_cached_store:
                    raise
                self._drop_cached_store(postal_code)
                store_url, _store_page, locality, store_postal = self._resolve_store_page(postal_code, retailer_context)
                offers = self._load_structured_offers(store_url, offer_week)
        if len(offers) < 100:
            raise ToolError(
                f"Kaufland-Angebotsübersicht für {store_url} lieferte nur "
                f"{len(offers)} sicher parsebare Angebote"
            )
        self.last_store_url = store_url
        self.last_store_postal_code = store_postal
        self.last_locality = locality
        return offers
