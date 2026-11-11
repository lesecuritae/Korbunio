from __future__ import annotations

import json
import time
import ssl
import threading
from functools import lru_cache
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, urlencode, urlsplit
from urllib.request import Request, urlopen

import certifi

from .common import clean_text
from .config import USER_AGENT
from .models import ToolError


@lru_cache(maxsize=1)
def trusted_ssl_context() -> ssl.SSLContext:
    """Verify certificates against certifi plus whatever the host trusts.

    Python on Windows frequently cannot reach the system certificate store,
    which makes every HTTPS source fail with CERTIFICATE_VERIFY_FAILED. certifi
    already ships with curl-cffi and gives every platform the same roots. The
    system store is loaded on top so company or antivirus roots keep working.
    Verification itself stays fully enabled.
    """
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        context.load_default_certs()
    except OSError:
        pass
    return context


RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


def _retry_delay(error: HTTPError) -> float:
    try:
        wanted = float(error.headers.get("Retry-After", "") or 1)
    except (TypeError, ValueError, AttributeError):
        wanted = 1.0
    return max(0.0, min(wanted, 5.0))


class HttpClient:
    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = max(3, timeout_seconds)

    def get_bytes(self, url: str, headers: Optional[dict[str, str]] = None) -> bytes:
        self._validate_https_url(url)
        request_headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        }
        request_headers.update(headers or {})
        request = Request(url, headers=request_headers)
        for attempt in (1, 2):
            try:
                with urlopen(request, timeout=self.timeout_seconds, context=trusted_ssl_context()) as response:  # nosec B310
                    self._validate_https_url(response.geturl())
                    data = response.read(10 * 1024 * 1024 + 1)
                    if len(data) > 10 * 1024 * 1024:
                        raise ToolError("Quellantwort überschreitet das Größenlimit")
                    return data
            except HTTPError as exc:
                if attempt == 1 and exc.code in RETRYABLE_STATUS:
                    # One bounded retry for throttling / transient gateway errors; Retry-After is honoured up to 5 s.
                    delay = _retry_delay(exc)
                    exc.close()
                    time.sleep(delay)
                    continue
                raise ToolError(f"HTTP {exc.code} bei {urlsplit(url).netloc}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                raise ToolError(f"Abruf von {urlsplit(url).netloc} fehlgeschlagen: {exc}") from exc
        raise ToolError(f"Abruf von {urlsplit(url).netloc} fehlgeschlagen")  # pragma: no cover - loop always returns or raises

    def get_json(self, url: str, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
        try:
            payload = json.loads(self.get_bytes(url, headers).decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise ToolError(f"Ungültige JSON-Antwort von {urlsplit(url).netloc}") from exc
        if not isinstance(payload, dict):
            raise ToolError(f"Unerwartete JSON-Antwort von {urlsplit(url).netloc}")
        return payload

    def post_form_json(self, url: str, fields: dict[str, str]) -> dict[str, Any]:
        parsed = self._validate_https_url(url)
        request = Request(
            url,
            data=urlencode(fields).encode("ascii"),
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds, context=trusted_ssl_context()) as response:  # nosec B310
                self._validate_https_url(response.geturl())
                data = response.read(10 * 1024 * 1024 + 1)
            if len(data) > 10 * 1024 * 1024:
                raise ToolError("Quellantwort überschreitet das Größenlimit")
            payload = json.loads(data.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise ToolError(f"Ungültige JSON-Antwort von {parsed.netloc}") from exc
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ToolError(f"Abruf von {parsed.netloc} fehlgeschlagen: {exc}") from exc
        if not isinstance(payload, dict):
            raise ToolError(f"Unerwartete JSON-Antwort von {parsed.netloc}")
        return payload

    @staticmethod
    def _validate_https_url(url: str) -> SplitResult:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ToolError("Nur HTTPS-Quellen sind erlaubt")
        return parsed

class PostalCodeLocator:
    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self._cache: dict[str, str] = {}
        self._address_cache: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    def locality(self, postal_code: str) -> str:
        with self._lock:
            cached = self._cache.get(postal_code)
        if cached is not None:
            return cached
        address = self._address(postal_code)
        locality = next(
            (address[field] for field in ("city", "town", "municipality", "village", "county") if address.get(field)),
            "",
        )
        if address:
            with self._lock:
                self._cache[postal_code] = locality
        return locality

    def coordinates(self, postal_code: str) -> tuple[float, float] | None:
        address = self._address(postal_code)
        try:
            lat, lon = float(address["_latitude"]), float(address["_longitude"])
            return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None
        except (KeyError, ValueError, TypeError):
            return None

    def state(self, postal_code: str) -> str:
        """Return the federal state for source pages that group stores by state."""
        with self._lock:
            cached = self._address_cache.get(postal_code)
        if cached is not None:
            return cached.get("state", "")

        return self._address(postal_code).get("state", "")

    def _address(self, postal_code: str) -> dict[str, str]:
        with self._lock:
            cached = self._address_cache.get(postal_code)
        if cached is not None:
            return cached

        query = urlencode({
            "postalcode": postal_code,
            "country": "Germany",
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 1,
        })
        try:
            payload = json.loads(self.http.get_bytes(
                f"https://nominatim.openstreetmap.org/search?{query}", {"Accept": "application/json"}
            ).decode("utf-8", errors="replace"))
            if isinstance(payload, list) and payload and isinstance(payload[0], dict):
                raw = payload[0].get("address")
                if isinstance(raw, dict):
                    address = {str(key): clean_text(value) for key, value in raw.items()}
                    address.update(_latitude=clean_text(payload[0].get("lat")), _longitude=clean_text(payload[0].get("lon")))
                    with self._lock:
                        self._address_cache[postal_code] = address
                    return address
        except Exception:
            pass
        return {}
