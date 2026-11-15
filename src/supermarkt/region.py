from __future__ import annotations

import json
import math
import threading
import time
import unicodedata
from math import asin, cos, radians, sin, sqrt
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from .common import clean_text, validate_postal_code
from .http import HttpClient
from .models import RETAILER_SPECS, ToolError


class _RequestState:
    """Diagnostics of the latest detect() on the *calling thread*.

    One resolver serves all concurrent loads, and each load calls detect() and
    then reads last_* on the same worker thread, so per-thread storage keeps
    overlapping postal codes from overwriting each other's region/error state
    without serialising any network I/O.
    """

    def __init__(self, default: Any) -> None:
        self.default = default

    def __set_name__(self, owner: type, name: str) -> None:
        self.slot = "_state_" + name

    def __get__(self, obj: Any, owner: Any = None) -> Any:
        if obj is None:
            return self
        return getattr(obj._local, self.slot, self.default)

    def __set__(self, obj: Any, value: Any) -> None:
        setattr(obj._local, self.slot, value)


class AldiRegionResolver:
    """Resolve ALDI Nord/Süd from nearby store metadata.

    Official chain catalogues establish presence and absence independently.
    Sparse OSM store metadata is only a bounded positive-evidence fallback.
    """

    def __init__(self, http: HttpClient, timeout_seconds: int = 10) -> None:
        self.http = HttpClient(min(http.timeout_seconds, max(3, timeout_seconds)))
        self._cache: dict[str, str] = {}
        self._local = threading.local()
        self._catalogues: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._catalogue_lock = threading.Lock()
        self._region_locks = {'nord': threading.Lock(), 'sued': threading.Lock()}

    last_provider = _RequestState("")
    last_distance_km = _RequestState(None)
    last_error = _RequestState("")
    last_regions = _RequestState(())
    last_absent_regions = _RequestState(())
    last_confidence = _RequestState("")

    # Same public first-party sources used by the native Android providers.
    # The Süd widget identifier is public, not an account credential.
    STORE_URLS = {
        "nord": "https://www.aldi-nord.de/filialen-und-oeffnungszeiten.html",
        "sued": "https://uberall.com/api/storefinders/gqNws2nRfBBlQJS9UrA8zV9txngvET/locations/all?v=20260101&language=de",
    }
    MAX_DISTANCE_KM = 15.0

    def _official_stores(self, region: str) -> list[dict[str, Any]]:
        # The global lock only guards the dict. Network I/O runs under a per-region lock, so a slow Nord catalogue
        # neither blocks Süd nor fresh cache hits, while concurrent callers of one region still share a single fetch.
        # A failed refresh raises (fail-closed): an old catalogue is never silently reused as confirmed evidence.
        def fresh() -> list[dict[str, Any]] | None:
            with self._catalogue_lock:
                cached = self._catalogues.get(region)
            return cached[1] if cached and time.monotonic() - cached[0] < 3600 else None

        if (hit := fresh()) is not None:
            return hit
        with self._region_locks[region]:
            if (hit := fresh()) is not None:
                return hit
            stores = self._load_official_stores(region)
            with self._catalogue_lock:
                self._catalogues[region] = (time.monotonic(), stores)
            return stores

    def _load_official_stores(self, region: str) -> list[dict[str, Any]]:
        raw = self.http.get_bytes(self.STORE_URLS[region])
        if len(raw) > 4_000_000:
            raise ToolError("ALDI-Filialliste überschreitet das Größenlimit")
        payload = self._parse_official_payload(raw, region)
        rows = self._official_store_rows(payload)
        stores = self._filter_official_store_rows(rows, region)
        if not stores:
            raise ToolError("ALDI lieferte keine gültigen Filialdaten")
        return stores

    @staticmethod
    def _parse_official_payload(raw: bytes, region: str) -> Any:
        if region == "nord":
            script = BeautifulSoup(raw, "html.parser").select_one("script#__NEXT_DATA__")
            if script is None:
                raise ToolError("ALDI Nord Filialdaten fehlen")
            api = json.loads(script.get_text())["props"]["pageProps"]["apiData"]
            api = json.loads(api) if isinstance(api, str) else api
            return next(item[1]["res"] for item in api
                        if isinstance(item, list) and len(item) == 2
                        and item[0] == "STORE_UBERALL_LOCATIONS_GET")
        return json.loads(raw)

    @staticmethod
    def _official_store_rows(payload: dict[str, Any]) -> list[Any]:
        if payload.get("status") != "SUCCESS":
            raise ToolError("ALDI-Filialdienst meldet keinen Erfolg")
        rows = payload["response"]["locations"]
        if not isinstance(rows, list):
            raise ToolError("ALDI-Filialformat unbekannt")
        return rows

    @staticmethod
    def _filter_official_store_rows(rows: list[Any], region: str) -> list[dict[str, Any]]:
        stores = []
        prefix = "aldi " + ("süd" if region == "sued" else "nord")
        for row in rows:
            if not isinstance(row, dict) or row.get("country") != "DE" or not str(row.get("name", "")).casefold().startswith(prefix):
                continue
            code = str(row.get("zip", ""))
            if len(code) != 5 or not code.isascii() or not code.isdigit():
                continue
            try:
                lat, lon = float(row["lat"]), float(row["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            stores.append({"postcode": code, "point": (lat, lon)})
        return stores

    def _official_regions(self, code: str) -> str | None:
        catalogues = {}
        errors = []
        for region in ("nord", "sued"):
            try:
                catalogues[region] = self._official_stores(region)
            except Exception as exc:  # defends against any network/HTML/JSON failure from the external ALDI catalogue
                errors.append(f"ALDI {region} Filialdienst: {type(exc).__name__}: {exc}")
        if not catalogues:
            self.last_error = " | ".join(errors)
            return None
        exact = [store["point"] for stores in catalogues.values() for store in stores if store["postcode"] == code]
        origin = (sum(point[0] for point in exact) / len(exact), sum(point[1] for point in exact) / len(exact)) if exact else self._postal_coordinates(code)
        self.last_provider = "Offizielle ALDI-Filiallisten"
        self.last_error = " | ".join(filter(None, [*errors, self.last_error]))
        if origin is None:
            self.last_error = self.last_error or "PLZ für ALDI-Marktsuche nicht bestätigt"
            return "auto"
        distances = {region: min(self._distance_km(origin, store["point"]) for store in stores)
                     for region, stores in catalogues.items()}
        self.last_regions = tuple(region for region, distance in distances.items() if distance <= self.MAX_DISTANCE_KM)
        self.last_absent_regions = tuple(region for region, distance in distances.items() if distance > self.MAX_DISTANCE_KM)
        self.last_distance_km = min(distances.values())
        self.last_confidence = "hoch" if len(catalogues) == 2 else "unvollständig"
        return self.last_regions[0] if len(self.last_regions) == 1 else "auto"

    # Versioned, deliberately postcode-exact evidence from the retailers'
    # official store pages. Ranges below are expanded into exact postcodes;
    # this is not a 52xxx/prefix heuristic. Unknown codes still use bounded
    # geocoding, while genuinely split cities remain explicit border cases.
    SCHEMA_VERSION = 5
    OFFICIAL_EVIDENCE: dict[str, tuple[str, ...]] = {
        "01067": ("nord",),
        "28195": ("nord",),
        **{str(code): ("sued",) for code in range(52062, 52081)},
        "52134": ("sued",), "52146": ("sued",), "52152": ("sued",),
        "52156": ("sued",), "52159": ("sued",), "52222": ("sued",),
        "52249": ("sued",),
        **{str(code): ("sued",) for code in range(52349, 52356)},
        "52372": ("sued",), "52379": ("sued",), "52382": ("sued",),
        "52385": ("sued",), "52388": ("sued",), "52391": ("sued",),
        "52393": ("sued",), "52396": ("sued",), "52399": ("sued",),
        "52428": ("sued",), "52441": ("sued",), "52445": ("sued",),
        "52457": ("sued",), "52459": ("sued",), "52477": ("sued",),
        "52499": ("sued",), "52511": ("sued",), "52525": ("sued",),
        "52531": ("sued",), "52538": ("sued",),
        **{str(code): ("sued",) for code in range(45468, 45482)},
        "47179": ("sued",), "46282": ("nord",), "80331": ("sued",),
        # Leverkusen: ALDI Süd führt 14 Filialen im Stadtgebiet, ALDI Nord keine.
        # Nachbarschaft ohne verwertbare OSM-Merkmale, daher PLZ-genau belegt.
        "51371": ("sued",), "51373": ("sued",), "51375": ("sued",),
        "51377": ("sued",), "51379": ("sued",), "51381": ("sued",),
        "51643": ("nord", "sued"), "57072": ("nord", "sued"),
    }

    @staticmethod
    def _region_from_tags(tags: dict[str, Any]) -> str:
        wikidata = clean_text(tags.get("brand:wikidata")).upper()
        if wikidata == "Q41171373":
            return "nord"
        if wikidata == "Q41171672":
            return "sued"
        websites = " ".join(
            clean_text(tags.get(key))
            for key in ("website", "contact:website", "url")
            if clean_text(tags.get(key))
        ).casefold()
        if "aldi-nord.de" in websites:
            return "nord"
        if "aldi-sued.de" in websites or "aldi-süd.de" in websites:
            return "sued"

        identity = " ".join(
            clean_text(tags.get(key))
            for key in ("brand", "operator", "network", "brand:wikipedia")
            if clean_text(tags.get(key))
        ).casefold()
        if "aldi nord" in identity:
            return "nord"
        if "aldi süd" in identity or "aldi sued" in identity or "aldi sud" in identity:
            return "sued"
        name = clean_text(tags.get("name")).casefold()
        if "aldi nord" in name:
            return "nord"
        if "aldi süd" in name or "aldi sued" in name or "aldi sud" in name:
            return "sued"
        return ""

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

    def _json(self, url: str) -> Any:
        return json.loads(
            self.http.get_bytes(url, headers={"Accept": "application/json"}).decode(
                "utf-8", errors="replace"
            )
        )

    def postal_coordinates(self, postal_code: str) -> tuple[float, float] | None:
        """Resolve an exact German postal area for other regional features."""
        if not validate_postal_code(postal_code):
            raise ToolError("Ungültige Postleitzahl")
        return self._postal_coordinates(postal_code)

    def _postal_coordinates(self, postal_code: str) -> tuple[float, float] | None:
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
            payload = self._json("https://nominatim.openstreetmap.org/search?" + query)
            if isinstance(payload, list) and payload and isinstance(payload[0], dict):
                address = payload[0].get("address") or {}
                if address.get("country_code") != "de" or address.get("postcode") != postal_code:
                    self.last_error = "PLZ-Geocoding: Land oder genaue PLZ nicht bestätigt"
                    return None
                point = (float(payload[0].get("lat")), float(payload[0].get("lon")))
                if -90 <= point[0] <= 90 and -180 <= point[1] <= 180:
                    return point
        except Exception as exc:  # defends against any network/JSON failure from the external Nominatim geocoder
            self.last_error = f"PLZ-Geocoding: {type(exc).__name__}: {exc}"
        return None

    def _nearby(self, origin: tuple[float, float], postal_code: str = "") -> list[dict[str, Any]]:
        lat, lon = origin
        query = urlencode(
            {
                "q": "ALDI",
                "format": "jsonv2",
                "countrycodes": "de",
                "bounded": 1,
                "viewbox": f"{lon - 1.35:.7f},{lat + 0.80:.7f},{lon + 1.35:.7f},{lat - 0.80:.7f}",
                "addressdetails": 1,
                "namedetails": 1,
                "extratags": 1,
                "limit": 30,
            }
        )
        try:
            payload = self._json("https://nominatim.openstreetmap.org/search?" + query)
        except Exception as exc:  # defends against any network/JSON failure from the external Nominatim search
            self.last_error = f"ALDI-Standortsuche: {type(exc).__name__}: {exc}"
            return []
        if not isinstance(payload, list):
            return []

        candidates: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            address = item.get("address") if isinstance(item.get("address"), dict) else {}
            names = item.get("namedetails") if isinstance(item.get("namedetails"), dict) else {}
            extras = item.get("extratags") if isinstance(item.get("extratags"), dict) else {}
            display = clean_text(item.get("display_name"))
            tags = {
                "name": clean_text(names.get("name")) or display.split(",", 1)[0],
                "brand": clean_text(extras.get("brand")),
                "operator": clean_text(extras.get("operator")),
                "network": clean_text(extras.get("network")),
                "brand:wikidata": clean_text(extras.get("brand:wikidata")),
                "brand:wikipedia": clean_text(extras.get("brand:wikipedia")),
                "website": clean_text(extras.get("website")),
                "contact:website": clean_text(extras.get("contact:website")),
                "addr:postcode": clean_text(address.get("postcode")),
            }
            region = self._region_from_tags(tags)
            if region not in {"nord", "sued"}:
                continue
            try:
                point = (float(item.get("lat")), float(item.get("lon")))
            except (TypeError, ValueError):
                continue
            candidates.append(
                {
                    "region": region,
                    "distance_km": self._distance_km(origin, point),
                    "provider": "Nominatim",
                    "exact_postcode": clean_text(address.get("postcode")) == postal_code,
                    "name": clean_text(tags.get("name")) or ("ALDI Nord" if region == "nord" else "ALDI Süd"),
                    "address": display,
                    "postal_code": clean_text(address.get("postcode")),
                    "latitude": point[0],
                    "longitude": point[1],
                    "url": clean_text(tags.get("website")) or clean_text(tags.get("contact:website")),
                }
            )
        return candidates

    def markets(self, postal_code: str) -> list[dict[str, Any]]:
        code = validate_postal_code(postal_code)
        if not code:
            return []
        origin = self._postal_coordinates(code)
        if origin is None:
            return []
        candidates = sorted(self._nearby(origin, code), key=lambda item: (not bool(item.get("exact_postcode")), float(item["distance_km"])))
        exact = [item for item in candidates if item.get("exact_postcode")]
        return exact or [item for item in candidates if float(item.get("distance_km") or 999) <= 15]

    @staticmethod
    def _market_identity(value: Any) -> str:
        text = unicodedata.normalize("NFKD", clean_text(value).casefold())
        return " ".join("".join(char for char in text if not unicodedata.combining(char) and char.isalnum() or char == " ").split())

    def _nominatim_search(self, search_name: str, lat: float, lon: float) -> list[Any]:
        query = urlencode({
            "q": search_name, "format": "jsonv2", "countrycodes": "de", "bounded": 1,
            "viewbox": f"{lon - 0.35:.7f},{lat + 0.25:.7f},{lon + 0.35:.7f},{lat - 0.25:.7f}",
            "addressdetails": 1, "namedetails": 1, "extratags": 1, "limit": 30,
        })
        try:
            payload = self._json("https://nominatim.openstreetmap.org/search?" + query)
        except Exception:  # defends against any network/JSON failure from the external Nominatim search
            return []
        return payload if isinstance(payload, list) else []

    def _market_from_nominatim_item(
        self, item: Any, retailer: str, spec: Any, origin: tuple[float, float], seen: set[tuple[str, str]]
    ) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        address = item.get("address") if isinstance(item.get("address"), dict) else {}
        names = item.get("namedetails") if isinstance(item.get("namedetails"), dict) else {}
        tags = item.get("extratags") if isinstance(item.get("extratags"), dict) else {}
        identity = self._market_identity(" ".join(clean_text(value) for value in (
            names.get("name"), address.get("shop"), tags.get("brand"), tags.get("operator"), item.get("display_name"),
        )))
        aliases = ("aldi",) if retailer.startswith("ALDI ") else tuple(
            self._market_identity(value) for value in (spec.name, *spec.aliases)
        )
        excluded = tuple(self._market_identity(value) for value in spec.excluded_aliases)
        if not any(alias and alias in identity for alias in aliases) or any(alias and alias in identity for alias in excluded):
            return None
        if retailer.startswith("ALDI "):
            region = self._region_from_tags({**tags, "name": names.get("name") or address.get("shop")})
            if not region or retailer != ("ALDI Nord" if region == "nord" else "ALDI Süd"):
                return None
        try:
            point = (float(item["lat"]), float(item["lon"]))
        except (KeyError, TypeError, ValueError):
            return None
        if self._distance_km(origin, point) > 15:
            return None
        market_id = clean_text(item.get("osm_id") or item.get("place_id"))
        key = (retailer, market_id or f"{point[0]:.6f}:{point[1]:.6f}")
        if key in seen:
            return None
        seen.add(key)
        return {
            "market_id": key[1], "retailer": retailer,
            "name": clean_text(names.get("name") or address.get("shop")) or retailer,
            "address": clean_text(item.get("display_name")), "postal_code": clean_text(address.get("postcode")),
            "latitude": point[0], "longitude": point[1],
            "url": clean_text(tags.get("website") or tags.get("contact:website")) or spec.fallback_url,
            "distance_km": self._distance_km(origin, point), "provider": "OpenStreetMap/Nominatim",
        }

    def retailer_markets(self, postal_code: str, retailers: tuple[str, ...]) -> list[dict[str, Any]]:
        code = validate_postal_code(postal_code)
        origin = self._postal_coordinates(code) if code else None
        if origin is None:
            return []
        lat, lon = origin
        specs = {spec.name: spec for spec in RETAILER_SPECS}
        markets: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for retailer in dict.fromkeys(retailers):
            spec = specs.get(retailer)
            if spec is None:
                continue
            search_name = "ALDI" if retailer.startswith("ALDI ") else spec.name
            for item in self._nominatim_search(search_name, lat, lon):
                market = self._market_from_nominatim_item(item, retailer, spec, origin, seen)
                if market is not None:
                    markets.append(market)
        return sorted(markets, key=lambda item: (float(item["distance_km"]), item["retailer"].casefold(), item["name"].casefold()))

    def detect(self, postal_code: str) -> str:
        self.last_regions = self.last_absent_regions = ()
        self.last_error = self.last_provider = self.last_confidence = ""
        self.last_distance_km = None
        code = validate_postal_code(postal_code)
        if not code:
            return "auto"
        evidence = self.OFFICIAL_EVIDENCE.get(code)
        if evidence:
            self.last_regions = evidence
            self.last_absent_regions = tuple(region for region in ("nord", "sued") if region not in evidence)
            self.last_provider = "Offizielle ALDI-Filialseiten (versionierter Nachweis)"
            self.last_distance_km = None
            self.last_confidence = "hoch"
            return evidence[0] if len(evidence) == 1 else "auto"
        official = self._official_regions(code)
        if official is not None:
            return official
        cached = self._cache.get(code)
        if cached in {"nord", "sued"}:
            # Other postal-code lookups can overwrite these mutable diagnostics.
            self.last_regions = (cached,)
            self.last_provider = "Nominatim (Cache)"
            self.last_distance_km = None
            self.last_confidence = "mittel"
            return cached

        self.last_provider = ""
        self.last_distance_km = None
        # Keep official-provider diagnostics while trying sparse OSM positives.
        self.last_regions = ()
        self.last_confidence = ""
        origin = self._postal_coordinates(code)
        if origin is None:
            return "auto"

        candidates = sorted((item for item in self._nearby(origin, code)
                             if float(item["distance_km"]) <= self.MAX_DISTANCE_KM),
                            key=lambda item: (not bool(item.get("exact_postcode")), float(item["distance_km"])))
        if not candidates:
            return "auto"

        nearest = candidates[0]
        region = str(nearest["region"])
        self.last_provider = str(nearest["provider"])
        self.last_distance_km = float(nearest["distance_km"])
        second_region = next((item for item in candidates if item["region"] != region), None)
        if second_region and float(second_region["distance_km"]) <= float(nearest["distance_km"]) + 5.0:
            self.last_regions = tuple(dict.fromkeys((region, str(second_region["region"]))))
            self.last_confidence = "mehrdeutig"
            return "auto"
        self.last_regions = (region,)
        self.last_confidence = "mittel"
        self._cache[code] = region
        return region
