from __future__ import annotations

import json
from math import asin, cos, radians, sin, sqrt
from typing import Any, Optional
from urllib.parse import urlencode

from .common import clean_text, validate_postal_code
from .http import HttpClient


class AldiRegionResolver:
    """Resolve ALDI Nord/Süd from nearby store metadata.

    The resolver intentionally uses one bounded provider path instead of a
    multi-provider retry chain. Explicit user selection always bypasses it.
    """

    def __init__(self, http: HttpClient, timeout_seconds: int = 10) -> None:
        self.http = HttpClient(min(http.timeout_seconds, max(3, timeout_seconds)))
        self._cache: dict[str, str] = {}
        self.last_provider = ""
        self.last_distance_km: Optional[float] = None
        self.last_error = ""
        self.last_regions: tuple[str, ...] = ()
        self.last_confidence = ""

    # Versioned, deliberately postcode-exact evidence from the retailers'
    # official store pages. Ranges below are expanded into exact postcodes;
    # this is not a 52xxx/prefix heuristic. Unknown codes still use bounded
    # geocoding, while genuinely split cities remain explicit border cases.
    SCHEMA_VERSION = 4
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

    def _postal_coordinates(self, postal_code: str) -> Optional[tuple[float, float]]:
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
                point = (float(payload[0].get("lat")), float(payload[0].get("lon")))
                if -90 <= point[0] <= 90 and -180 <= point[1] <= 180:
                    return point
        except Exception as exc:
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
        except Exception as exc:
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

    def detect(self, postal_code: str) -> str:
        code = validate_postal_code(postal_code)
        if not code:
            return "auto"
        evidence = self.OFFICIAL_EVIDENCE.get(code)
        if evidence:
            self.last_regions = evidence
            self.last_provider = "Offizielle ALDI-Filialseiten (versionierter Nachweis)"
            self.last_distance_km = None
            self.last_confidence = "hoch"
            return evidence[0] if len(evidence) == 1 else "auto"
        cached = self._cache.get(code)
        if cached in {"nord", "sued"}:
            return cached

        self.last_provider = ""
        self.last_distance_km = None
        self.last_error = ""
        self.last_regions = ()
        self.last_confidence = ""
        origin = self._postal_coordinates(code)
        if origin is None:
            return "auto"

        candidates = sorted(self._nearby(origin, code), key=lambda item: (not bool(item.get("exact_postcode")), float(item["distance_km"])))
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
