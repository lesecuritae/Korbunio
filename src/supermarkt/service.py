from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime
from typing import Any

from .cache import PersistentSnapshotStore
from .categories import category_decision
from .common import clean_text, deduplicate_offers, filter_offers, filter_offers_by_keywords, normalize_aldi_region, normalize_keywords, normalize_offer_week, normalize_pack, normalize_view, offer_week_reference, parse_iso_date
from .compare import OfferComparator, OfferMapper
from .config import (
    CACHE_DB,
    CACHE_MAX_SNAPSHOTS,
    CACHE_TTL_MINUTES,
    CACHE_WEEKLY,
    KAUFLAND_CACHE_DIR,
    KAUFLAND_STORE_CACHE_TTL_SECONDS,
    REWE_CACHE_DIR,
    REWE_STORE_CACHE_TTL_SECONDS,
    MARKTGURU_PAGE_SIZE,
    MAX_WORKERS,
    RESULT_RETENTION_HOURS,
    TIMEOUT_SECONDS,
)
from .http import HttpClient, PostalCodeLocator
from .loyalty import available_programs, normalize_program_ids
from .offer_week import next_change_timestamp
from .models import AGGREGATOR_RETAILERS, RETAILER_SPECS, Offer, RetailerContext, ToolError, offer_from_dict, offer_to_dict
from .presentation import offer_for_response, offer_sort_key, resolve_retailer_name
from .region import AldiRegionResolver

LOGGER = logging.getLogger(__name__)
from .sources import KaufdaGlobusImageSource, MarktguruClient, NettoMarkenMarketResolver, OfficialAldiSource, OfficialDmSource, OfficialEdekaSource, OfficialGlobusSource, OfficialKauflandSource, OfficialMarktkaufSource, OfficialReweSource, OfficialHolabSource, OfficialNettoScottieSource, OfficialMuellerSource, OfficialRossmannSource
from .sources.aldi_chain import AldiOfferChain

class SourceLoader:
    def __init__(self) -> None:
        http = HttpClient(TIMEOUT_SECONDS)
        locator = PostalCodeLocator(http)
        self.locator = locator
        self.marktguru = MarktguruClient(http, MARKTGURU_PAGE_SIZE, MAX_WORKERS)
        self.aldi_region = AldiRegionResolver(http)
        self.official_aldi = OfficialAldiSource(http)
        self.aldi_offers = AldiOfferChain(CACHE_DB, (self.official_aldi,))
        self.official_rewe = OfficialReweSource(
            locator,
            TIMEOUT_SECONDS,
            cache_dir=REWE_CACHE_DIR,
            store_cache_ttl_seconds=REWE_STORE_CACHE_TTL_SECONDS,
        )
        self.official_edeka = OfficialEdekaSource(TIMEOUT_SECONDS)
        self.official_holab = OfficialHolabSource(http)
        self.official_globus = OfficialGlobusSource(http)
        self.kaufda_globus_images = KaufdaGlobusImageSource(http)
        self.official_netto_scottie = OfficialNettoScottieSource(http)
        self.netto_marken_markets = NettoMarkenMarketResolver(http)
        self.official_rossmann = OfficialRossmannSource(timeout_seconds=TIMEOUT_SECONDS)
        self.official_mueller = OfficialMuellerSource(http)
        self.official_dm = OfficialDmSource(http)
        self.official_marktkauf = OfficialMarktkaufSource(TIMEOUT_SECONDS)
        self.official_kaufland = OfficialKauflandSource(
            http,
            locator,
            TIMEOUT_SECONDS,
            cache_dir=KAUFLAND_CACHE_DIR,
            store_cache_ttl_seconds=KAUFLAND_STORE_CACHE_TTL_SECONDS,
        )
        self.mapper = OfferMapper()

    @staticmethod
    def _contexts() -> dict[str, RetailerContext]:
        return {
            spec.name: RetailerContext(
                name=spec.name,
                aliases=tuple(alias.casefold() for alias in spec.aliases),
                excluded_aliases=tuple(alias.casefold() for alias in spec.excluded_aliases),
                color=spec.color,
                market_label=spec.name,
                market_url=spec.fallback_url,
            )
            for spec in RETAILER_SPECS
        }

    @staticmethod
    def _context_with_market(context: RetailerContext, label: str, url: str) -> RetailerContext:
        return replace(
            context,
            market_label=clean_text(label) or context.market_label,
            market_url=clean_text(url) or context.market_url,
        )

    @staticmethod
    def _globus_image_name(value: str) -> tuple[str, set[str]]:
        folded = unicodedata.normalize("NFKD", clean_text(value).casefold())
        folded = "".join(char for char in folded if not unicodedata.combining(char))
        normalized = re.sub(r"[^a-z0-9]+", " ", folded).strip()
        ignored = {"globus", "verschiedene", "sorten", "oder", "und", "je"}
        return normalized, {token for token in normalized.split() if token not in ignored and len(token) > 1}

    @classmethod
    def _enrich_globus_images(cls, official: list[Offer], image_offers: list[Offer], provider: str = "Marktguru") -> tuple[list[Offer], int]:
        """Attach only uniquely matching images; catalogue and prices stay official."""
        candidates = [item for item in image_offers if item.retailer == "Globus" and item.image_url]
        enriched: list[Offer] = []
        count = 0
        for offer in official:
            if offer.image_url:
                enriched.append(offer)
                continue
            normalized_name, name_tokens = cls._globus_image_name(offer.name)
            matches: dict[str, Offer] = {}
            for candidate in candidates:
                if offer.price is None or candidate.price is None or abs(offer.price - candidate.price) > 0.005:
                    continue
                if offer.pack_signature and candidate.pack_signature and normalize_pack(offer.pack_signature) != normalize_pack(candidate.pack_signature):
                    continue
                if offer.valid_from and candidate.valid_from and offer.valid_from != candidate.valid_from:
                    continue
                if offer.valid_until and candidate.valid_until and offer.valid_until != candidate.valid_until:
                    continue
                candidate_name, candidate_tokens = cls._globus_image_name(candidate.name)
                overlap = name_tokens & candidate_tokens
                union = name_tokens | candidate_tokens
                strong_name = normalized_name == candidate_name or (len(overlap) >= 2 and len(overlap) / max(1, len(union)) >= 0.8)
                if strong_name:
                    matches[candidate.image_url] = candidate
            if len(matches) != 1:
                enriched.append(offer)
                continue
            image_url = next(iter(matches))
            note = f"Produktbild ergänzend von {provider}; Angebotsdaten offiziell von Globus"
            enriched.append(replace(offer, image_url=image_url, coverage_note=" · ".join(filter(None, (offer.coverage_note, note)))))
            count += 1
        return enriched, count

    def load(self, postal_code: str, aldi_region: str, progress=None, retailers: tuple[str, ...] = (), rewe_market_id: str = "", netto_market_id: str = "", offer_week: str = "current") -> dict[str, Any]:
        notify = progress or (lambda **_fields: None)
        notify(status="loading", progress=5, source="Standortdienst", retailer="Alle Händler", category="Region", step="Region und Filialen werden ermittelt")
        contexts = self._contexts()
        selected_retailers = set(retailers)
        if selected_retailers:
            contexts = {name: context for name, context in contexts.items() if name in selected_retailers}
        request_errors: list[str] = []
        store_warnings: list[str] = []
        requested_week = normalize_offer_week(offer_week)
        target_date = offer_week_reference(requested_week)

        requested_region = normalize_aldi_region(aldi_region)
        selected_aldi = [name for name in ("ALDI Nord", "ALDI Süd") if name in selected_retailers]
        resolved = requested_region
        if selected_retailers:
            resolved_regions = ["nord" if name == "ALDI Nord" else "sued" for name in selected_aldi]
        elif resolved == "auto":
            resolved = self.aldi_region.detect(postal_code)
            detected_regions = getattr(self.aldi_region, "last_regions", ())
            resolved_regions = list(detected_regions or ((resolved,) if resolved in {"nord", "sued"} else ()))
        elif not selected_retailers:
            resolved_regions = ["nord", "sued"] if requested_region == "both" else ([resolved] if resolved in {"nord", "sued"} else [])
        aldi_names = ["ALDI Nord" if item == "nord" else "ALDI Süd" for item in resolved_regions]
        if not aldi_names and not selected_retailers:
            detail = clean_text(self.aldi_region.last_error)
            warning = "ALDI-Region konnte geografisch nicht eindeutig bestimmt werden; ALDI wurde für diesen Abruf ausgelassen."
            store_warnings.append(warning + (f" ({detail})" if detail else ""))

        active_contexts = dict(contexts)
        for name in ("ALDI Nord", "ALDI Süd"):
            if name not in aldi_names:
                active_contexts.pop(name, None)

        if "Netto Marken-Discount" in active_contexts and hasattr(self, "netto_marken_markets"):
            try:
                selected_netto = self.netto_marken_markets.resolve(postal_code, netto_market_id)
                if selected_netto:
                    option = self.netto_marken_markets._option(selected_netto, "exact" if clean_text(selected_netto.get("post_code")) == postal_code else "nearby")
                    active_contexts["Netto Marken-Discount"] = self._context_with_market(active_contexts["Netto Marken-Discount"], option["label"], option["market_url"])
                    store_warnings.append("Netto Marken-Discount: Filiale ausgewählt; der aktuelle Angebotskatalog ist regional und nicht filialgenau.")
            except Exception as exc:
                if netto_market_id:
                    raise
                store_warnings.append(f"Netto Marken-Discount: Filialauflösung nicht verfügbar ({type(exc).__name__}: {exc}).")

        source_states = dict.fromkeys(active_contexts, "keine Treffer")
        final_by_retailer: dict[str, list[Offer]] = {}
        failed_primary: set[str] = set()

        # Retailers with maintained first-party adapters always prefer their
        # official source. A partial aggregator result must never suppress a
        # complete official catalogue or be mixed into it.
        def load_rewe() -> list[Offer]:
            if requested_week == "next":
                try:
                    return self.official_rewe.load(postal_code, rewe_market_id, "next")
                except Exception:
                    store_warnings.append("REWE: Noch keine Angebote der Folgewoche verfügbar; aktuelle Angebote werden angezeigt.")
            return self.official_rewe.load(postal_code, rewe_market_id) if rewe_market_id else self.official_rewe.load(postal_code)

        def load_with_week(source: Any, name: str) -> list[Offer]:
            if requested_week == "next":
                try:
                    return source.load(postal_code, "next")
                except Exception:
                    store_warnings.append(f"{name}: Noch keine Angebote der Folgewoche verfügbar; aktuelle Angebote werden angezeigt.")
            return source.load(postal_code)

        def load_kaufland() -> list[Offer]:
            if requested_week == "next":
                try:
                    return self.official_kaufland.load(postal_code, offer_week="next")
                except Exception:
                    store_warnings.append("Kaufland: Noch keine Angebote der Folgewoche verfügbar; aktuelle Angebote werden angezeigt.")
            return self.official_kaufland.load(postal_code)

        official_loaders: dict[str, Any] = {
            "REWE": load_rewe, "EDEKA": lambda: load_with_week(self.official_edeka, "EDEKA"),
            "Kaufland": load_kaufland, "Marktkauf": lambda: load_with_week(self.official_marktkauf, "Marktkauf"),
        }
        official_jobs = {name: loader for name, loader in official_loaders.items() if name in active_contexts}
        if hasattr(self, "official_globus") and "Globus" in active_contexts:
            official_jobs["Globus"] = lambda: self.official_globus.load(postal_code)
        if hasattr(self, "official_netto_scottie") and "Netto schwarz" in active_contexts:
            official_jobs["Netto schwarz"] = lambda: self.official_netto_scottie.load(postal_code)
        if hasattr(self, "official_rossmann") and "Rossmann" in active_contexts:
            official_jobs["Rossmann"] = lambda: self.official_rossmann.load(postal_code)
        if hasattr(self, "official_mueller") and "Müller" in active_contexts:
            official_jobs["Müller"] = lambda: self.official_mueller.load(postal_code)
        if hasattr(self, "official_dm") and "dm" in active_contexts:
            official_jobs["dm"] = lambda: self.official_dm.load(postal_code)
        if hasattr(self, "official_holab") and "HOL’AB!" in active_contexts:
            official_jobs["HOL’AB!"] = lambda: self.official_holab.load(postal_code)
        initial_aggregator = any(
            name in active_contexts and name != "Globus" for name in AGGREGATOR_RETAILERS
        )
        total_sources = len(official_jobs) + len(aldi_names) + (1 if initial_aggregator else 0)
        notify(total_sources=max(1, total_sources), processed_sources=0)
        completed_sources = 0
        processed_products = 0
        with ThreadPoolExecutor(max_workers=max(1, len(official_jobs))) as executor:
            futures = {executor.submit(loader): name for name, loader in official_jobs.items()}
            for future in as_completed(futures):
                name = futures[future]
                completed_sources += 1
                notify(status="processing", progress=10 + completed_sources * 9, source="Offizielle Webseite", retailer=name, category="Wochenangebote", step="Quelle wird ausgewertet", processed_sources=completed_sources, processed_products=processed_products)
                try:
                    offers = deduplicate_offers(list(future.result()))
                except Exception as exc:
                    failed_primary.add(name)
                    if name in {"Marktkauf", "HOL’AB!"}:
                        source_states[name] = "kein Markt"
                    else:
                        request_errors.append(f"{name} offiziell: {type(exc).__name__}: {exc}")
                    continue
                if not offers:
                    failed_primary.add(name)
                    if name in {"Marktkauf", "HOL’AB!"}:
                        source_states[name] = "kein Markt"
                    else:
                        request_errors.append(f"{name} offiziell: keine Angebote für die Zielwoche")
                    continue
                final_by_retailer[name] = offers
                source_states[name] = "offiziell"
                processed_products += len(offers)
                notify(status="processing", progress=10 + completed_sources * 9, source="Offizielle Webseite", retailer=name, category="Wochenangebote", step="Quelle verarbeitet", processed_sources=completed_sources, processed_products=processed_products)

        # ALDI is also first-party-first. Only the region determined for the
        # supplied postcode is loaded.
        if aldi_names:
            notify(status="loading", progress=50, source="Offizielle Webseite", retailer=" & ".join(aldi_names), category="Wochenangebote", step="Regionale Angebote werden getrennt geladen", processed_sources=completed_sources, processed_products=processed_products)
            with ThreadPoolExecutor(max_workers=len(aldi_names)) as executor:
                aldi_loader = getattr(self, "aldi_offers", self.official_aldi)
                def load_aldi(name: str):
                    if requested_week == "next":
                        try:
                            return self.official_aldi.load(name, "next")
                        except Exception:
                            store_warnings.append(f"{name}: Noch keine Angebote der Folgewoche verfügbar; aktuelle Angebote werden angezeigt.")
                    return aldi_loader.load(name)
                aldi_futures = {executor.submit(load_aldi, name): name for name in aldi_names}
                for future in as_completed(aldi_futures):
                    aldi_name = aldi_futures[future]
                    try:
                        aldi_result = future.result()
                        request_errors.extend(aldi_result.request_errors)
                        aldi_offers = deduplicate_offers(list(aldi_result.offers))
                    except Exception as exc:
                        aldi_offers = []
                        request_errors.append(f"{aldi_name} offiziell: {type(exc).__name__}: {exc}")
                    if aldi_offers:
                        final_by_retailer[aldi_name] = aldi_offers
                        source_states[aldi_name] = getattr(aldi_loader, "last_source", {}).get(aldi_name, "offiziell")
                        processed_products += len(aldi_offers)
                    else:
                        failed_primary.add(aldi_name)
                    completed_sources += 1
                    notify(status="processing", progress=55, source="Offizielle Webseite", retailer=aldi_name, category="Wochenangebote", step="Quelle verarbeitet", processed_sources=completed_sources, processed_products=processed_products)

        if source_states.get("Globus") == "offiziell" and hasattr(self, "kaufda_globus_images"):
            market = getattr(self.official_globus, "last_market", None)
            locality = clean_text(getattr(market, "name", ""))
            if locality and any(not offer.image_url for offer in final_by_retailer.get("Globus", ())):
                try:
                    kaufda_images = self.kaufda_globus_images.load(locality)
                    enriched, image_count = self._enrich_globus_images(
                        final_by_retailer["Globus"], kaufda_images, "KaufDA"
                    )
                    final_by_retailer["Globus"] = enriched
                    if image_count:
                        source_states["Globus"] = "offiziell + KaufDA-Bild"
                except Exception as exc:
                    LOGGER.warning("KaufDA-Globus-Bildabgleich fehlgeschlagen: %s: %s", type(exc).__name__, exc)

        # Retailers without an official adapter use Marktguru as their
        # catalogue source. The broad regional term search is supplemented by
        # retailer-name searches; those name queries are never treated as a
        # complete catalogue on their own. Failed first-party adapters may use
        # the same data only as a fallback.
        aggregator_names = {
            name for name in AGGREGATOR_RETAILERS
            if name in active_contexts and name != "Globus"
        }
        fallback_names = {
            name for name in failed_primary
            if name in active_contexts
        }
        globus_image_enrichment = {
            "Globus"
            if source_states.get("Globus", "").startswith("offiziell")
            and any(not offer.image_url for offer in final_by_retailer.get("Globus", ()))
            else ""
        } - {""}
        marketguru_candidates = aggregator_names | fallback_names | globus_image_enrichment
        marktguru_mapped: list[Offer] = []
        marktguru_current_mapped: list[Offer] = []
        if marketguru_candidates:
            # A failed first-party source can add the aggregator fallback only
            # after the initial plan was calculated. Grow the technical-source
            # total before incrementing progress, never after it.
            if not initial_aggregator:
                total_sources += 1
                notify(total_sources=max(1, total_sources), processed_sources=completed_sources)
            completed_sources += 1
            notify(status="loading", progress=62, source="Marktguru", retailer="Lidl, PENNY, Netto Marken-Discount, Combi, famila", category="Händlerkategorien", step="Regionale Angebote werden geladen", processed_sources=completed_sources, processed_products=processed_products)
            raw: list[dict[str, Any]] = []
            if aggregator_names or fallback_names:
                try:
                    broad_raw, errors = self.marktguru.load_offers(postal_code)
                    raw.extend(broad_raw)
                    request_errors.extend(errors)
                except Exception as exc:
                    request_errors.append(f"Marktguru: {type(exc).__name__}: {exc}")

            try:
                targeted_raw, errors = self.marktguru.load_retailer_queries(
                    postal_code,
                    sorted(marketguru_candidates, key=str.casefold),
                )
                raw.extend(targeted_raw)
                request_errors.extend(errors)
            except Exception as exc:
                request_errors.append(f"Marktguru Händlerergänzung: {type(exc).__name__}: {exc}")

            if raw:
                marktguru_mapped = deduplicate_offers(self.mapper.map_all(raw, active_contexts, target_date))
                if requested_week == "next":
                    marktguru_current_mapped = deduplicate_offers(
                        self.mapper.map_all(raw, active_contexts, offer_week_reference("current"))
                    )
                processed_products += len(marktguru_mapped)
            notify(status="processing", progress=88, source="Marktguru", retailer="Lidl, PENNY, Netto Marken-Discount, Combi, famila", category="Händlerkategorien", step="Angebote zugeordnet", processed_sources=completed_sources, processed_products=processed_products)

        for name in sorted(aggregator_names, key=str.casefold):
            offers = deduplicate_offers([
                offer for offer in marktguru_mapped
                if offer.retailer == name
            ])
            if not offers and requested_week == "next":
                offers = deduplicate_offers([
                    offer for offer in marktguru_current_mapped
                    if offer.retailer == name
                ])
                if offers:
                    store_warnings.append(
                        f"{name}: Noch keine Angebote der Folgewoche verfügbar; aktuelle Angebote werden angezeigt."
                    )
            if offers:
                final_by_retailer[name] = offers
                source_states[name] = "Marktguru"
            elif not next((spec.optional for spec in RETAILER_SPECS if spec.name == name), False):
                request_errors.append(f"{name}: Marktguru lieferte keine Angebote für die Zielwoche")

        for name in sorted(fallback_names, key=str.casefold):
            # Never mix a fallback with a first-party catalogue that succeeded.
            if name in final_by_retailer:
                continue
            offers = deduplicate_offers([
                offer for offer in marktguru_mapped
                if offer.retailer == name
            ])
            if not offers and requested_week == "next":
                offers = deduplicate_offers([
                    offer for offer in marktguru_current_mapped
                    if offer.retailer == name
                ])
            if not offers:
                continue
            final_by_retailer[name] = offers
            source_states[name] = "Marktguru-Fallback"
            store_warnings.append(
                f"{name}: offizielle Quelle war nicht verfügbar; Marktguru wurde als Fallback verwendet."
            )

        if "Globus" in globus_image_enrichment and "Globus" in final_by_retailer:
            enriched, image_count = self._enrich_globus_images(final_by_retailer["Globus"], marktguru_mapped)
            final_by_retailer["Globus"] = enriched
            if image_count:
                source_states["Globus"] = (
                    "offiziell + KaufDA-/Marktguru-Bild"
                    if "KaufDA" in source_states.get("Globus", "")
                    else "offiziell + Marktguru-Bild"
                )

        # Update labels only from first-party adapters that actually supplied
        # the catalogue displayed to the user.
        if source_states.get("REWE") == "offiziell" and self.official_rewe.last_market_url:
            active_contexts["REWE"] = self._context_with_market(
                active_contexts["REWE"], self.official_rewe.last_market_label, self.official_rewe.last_market_url
            )
        if source_states.get("EDEKA") == "offiziell" and self.official_edeka.last_market_url:
            active_contexts["EDEKA"] = self._context_with_market(
                active_contexts["EDEKA"], self.official_edeka.last_market_label, self.official_edeka.last_market_url
            )
        if source_states.get("Marktkauf") == "offiziell" and self.official_marktkauf.last_market_url:
            active_contexts["Marktkauf"] = self._context_with_market(
                active_contexts["Marktkauf"], self.official_marktkauf.last_market_label, self.official_marktkauf.last_market_url
            )
        if source_states.get("Globus", "").startswith("offiziell") and self.official_globus.last_market_url:
            active_contexts["Globus"] = self._context_with_market(
                active_contexts["Globus"], self.official_globus.last_market_label, self.official_globus.last_market_url
            )
        if source_states.get("Netto schwarz") == "offiziell" and self.official_netto_scottie.last_market_url:
            active_contexts["Netto schwarz"] = self._context_with_market(
                active_contexts["Netto schwarz"],
                self.official_netto_scottie.last_market_label,
                self.official_netto_scottie.last_market_url,
            )
        if source_states.get("Kaufland") == "offiziell" and self.official_kaufland.last_store_url:
            label = "Kaufland " + clean_text(self.official_kaufland.last_locality)
            active_contexts["Kaufland"] = self._context_with_market(
                active_contexts["Kaufland"], label, self.official_kaufland.last_store_url
            )

        if requested_week == "next":
            for name, retailer_offers in list(final_by_retailer.items()):
                preview = []
                for offer in retailer_offers:
                    start = parse_iso_date(offer.valid_from)
                    end = parse_iso_date(offer.valid_until)
                    if (start or end) and (start is None or start <= target_date) and (end is None or target_date <= end):
                        preview.append(offer)
                if preview:
                    final_by_retailer[name] = preview
                else:
                    store_warnings.append(f"{name}: Noch keine Angebote der Folgewoche verfügbar; aktuelle Angebote werden angezeigt.")

        offers = deduplicate_offers([
            offer
            for retailer_offers in final_by_retailer.values()
            for offer in retailer_offers
        ])
        normalized_offers = []
        for offer in offers:
            source_category = offer.source_category or offer.category
            decision = category_decision(
                source_category, offer.retailer, offer.name, offer.description, offer.brand
            )
            if decision.category_conflict:
                LOGGER.info(
                    "category_conflict retailer=%r product=%r source_category=%r detected_category=%r",
                    offer.retailer, offer.name, source_category, decision.detected_category,
                )
            normalized_offers.append(replace(
                offer,
                source_category=source_category,
                detected_category=decision.detected_category,
                category_conflict=decision.category_conflict,
                category=decision.category,
                retailer_url=offer.retailer_url or contexts.get(offer.retailer, RetailerContext("", (), (), "", "", "")).market_url,
            ))
        offers = normalized_offers
        if not offers:
            raise ToolError("Keine Supermarktangebote konnten geladen werden")

        notify(status="processing", progress=96, source="KorbKlar", retailer="Alle Händler", category="Alle Kategorien", step="Angebote werden zusammengeführt", processed_sources=completed_sources, processed_products=len(offers))

        return {
            "postal_code": postal_code,
            "resolved_aldi_region": resolved,
            "resolved_aldi_regions": resolved_regions,
            "offer_week": requested_week,
            "aldi_resolution": {"source": getattr(self.aldi_region, "last_provider", ""), "distance_km": getattr(self.aldi_region, "last_distance_km", None), "confidence": getattr(self.aldi_region, "last_confidence", "")},
            "offers": [offer_to_dict(offer) for offer in offers],
            "retailers": {name: asdict(context) for name, context in active_contexts.items()},
            "source_states": source_states,
            "request_errors": list(dict.fromkeys(clean_text(x) for x in request_errors if clean_text(x))),
            "store_warnings": list(dict.fromkeys(clean_text(x) for x in store_warnings if clean_text(x))),
        }

class SupermarketEngine:
    # v11 separates offer weeks and invalidates snapshots with old ALDI brand
    # and multipack-deposit semantics.
    SNAPSHOT_SCHEMA = 11
    def __init__(self) -> None:
        self.store = PersistentSnapshotStore(CACHE_DB, CACHE_TTL_MINUTES, RESULT_RETENTION_HOURS, CACHE_MAX_SNAPSHOTS)
        self.loader = SourceLoader()
        self.comparator = OfferComparator()
        self._refresh_lock = threading.Lock()

    @staticmethod
    def cache_key(postal_code: str, aldi_region: str, retailers: tuple[str, ...] = (), rewe_market_id: str = "", netto_market_id: str = "", offer_week: str = "current") -> str:
        selected = ",".join(sorted(retailers, key=str.casefold)) or "all"
        rewe = clean_text(rewe_market_id) or "auto"
        netto = clean_text(netto_market_id) or "auto"
        return f"v{SupermarketEngine.SNAPSHOT_SCHEMA}:{postal_code}:{normalize_aldi_region(aldi_region)}:{selected}:rewe-{rewe}:netto-{netto}:week-{normalize_offer_week(offer_week)}"

    def snapshot(self, postal_code: str, aldi_region: str, refresh: bool = False, progress=None, retailers: tuple[str, ...] = (), rewe_market_id: str = "", netto_market_id: str = "", offer_week: str = "current") -> tuple[dict[str, Any], bool]:
        key = self.cache_key(postal_code, aldi_region, retailers, rewe_market_id, netto_market_id, offer_week)
        if not refresh:
            cached = self.store.get_by_key(key)
            if cached is not None:
                if progress:
                    progress(status="processing", progress=90, source="Cache", retailer="Alle Händler", category="Alle Kategorien", step="Gespeicherter Vergleich wird geöffnet", processed_sources=1, total_sources=1, processed_products=len(cached.get("offers", [])))
                return cached, True
        with self._refresh_lock:
            if not refresh:
                cached = self.store.get_by_key(key)
                if cached is not None:
                    if progress:
                        progress(status="processing", progress=90, source="Cache", retailer="Alle Händler", category="Alle Kategorien", step="Gespeicherter Vergleich wird geöffnet", processed_sources=1, total_sources=1, processed_products=len(cached.get("offers", [])))
                    return cached, True
            fresh = self.loader.load(postal_code, aldi_region, progress=progress, retailers=retailers, rewe_market_id=rewe_market_id, netto_market_id=netto_market_id, offer_week=offer_week)
            return self.store.put(key, fresh, fresh_until=self.freshness_deadline(fresh, offer_week)), False

    @staticmethod
    def freshness_deadline(snapshot: dict[str, Any], offer_week: str = "current", now: datetime | None = None, weekly: bool = CACHE_WEEKLY) -> float | None:
        """How long a freshly loaded snapshot may be served from the cache.

        Offers change on Thursday and, as far as this server is concerned,
        on Sunday (see ``offer_reference_date``), so a complete snapshot of
        the current week is kept until the next of those two moments. ``None``
        falls back to the store's short TTL: for a disabled weekly cache, for
        next-week previews (retailers publish them piecemeal during the week)
        and for snapshots where at least one source failed, so a hiccup is
        retried after minutes rather than days.
        """
        if not weekly or normalize_offer_week(offer_week) != "current":
            return None
        if snapshot.get("request_errors"):
            return None
        return next_change_timestamp(now)

    def by_id(self, search_id: str) -> dict[str, Any]:
        snapshot = self.store.get_by_id(search_id)
        if snapshot is None:
            raise ToolError("Dieser Supermarktvergleich ist abgelaufen. Bitte die Suche neu starten.")
        return snapshot

    def page(
        self,
        snapshot: dict[str, Any],
        *,
        filter_text: str = "",
        keywords: tuple[str, ...] = (),
        retailer: str = "",
        retailer_filters: tuple[str, ...] = (),
        category: str = "",
        page: int = 1,
        page_size: int = 100,
        view: str = "best_only",
        loyalty_programs: tuple[str, ...] = (),
        sort: str = "price",
        include_image_urls: bool = False,
    ) -> dict[str, Any]:
        offers = [offer_from_dict(item) for item in snapshot.get("offers", []) if isinstance(item, dict)]
        selected_programs = normalize_program_ids(loyalty_programs)
        source_retailer_counts: dict[str, int] = {}
        for offer in offers:
            source_retailer_counts[offer.retailer] = source_retailer_counts.get(offer.retailer, 0) + 1

        normalized_view = normalize_view(view)
        all_comparison = self.comparator.compare(offers, selected_programs, "all")
        best_comparison = self.comparator.compare(offers, selected_programs, "best_only")

        retailers_raw = snapshot.get("retailers") or {}
        retailers = {
            name: RetailerContext(**value)
            for name, value in retailers_raw.items()
            if isinstance(name, str) and isinstance(value, dict)
        }
        selected_retailer = resolve_retailer_name(retailer, retailers)
        selected_retailers = tuple(dict.fromkeys(
            resolved for value in retailer_filters
            if (resolved := resolve_retailer_name(value, retailers))
        ))
        if selected_retailer and not selected_retailers:
            selected_retailers = (selected_retailer,)
        selected_retailer_keys = {name.casefold() for name in selected_retailers}
        selected_category = clean_text(category)

        def scope(items: list[Offer]) -> list[Offer]:
            scoped = filter_offers(items, filter_text)
            scoped = filter_offers_by_keywords(scoped, keywords)
            if selected_retailer_keys:
                scoped = [
                    offer
                    for offer in scoped
                    if offer.retailer.casefold() in selected_retailer_keys
                ]
            if selected_category:
                scoped = [offer for offer in scoped if offer.category.casefold() == selected_category.casefold()]
            return scoped

        all_scoped = scope(all_comparison.offers)
        best_scoped = scope(best_comparison.offers)
        hidden_count = max(0, len(all_scoped) - len(best_scoped))
        filtered = all_scoped if normalized_view == "all" else best_scoped

        # Chip counts intentionally reflect the current text filter and view,
        # but not the selected retailer chip itself, so switching retailers
        # remains possible without resetting the other filters.
        comparison_for_counts = all_comparison if normalized_view == "all" else best_comparison
        count_scope = filter_offers_by_keywords(filter_offers(comparison_for_counts.offers, filter_text), keywords)
        counts: dict[str, int] = {}
        for offer in count_scope:
            counts[offer.retailer] = counts.get(offer.retailer, 0) + 1
        category_scope = [offer for offer in count_scope if not selected_retailer_keys or offer.retailer.casefold() in selected_retailer_keys]
        category_counts: dict[str, int] = {}
        for offer in category_scope:
            category_counts[offer.category] = category_counts.get(offer.category, 0) + 1

        retailer_markets = [
            {
                "retailer": name,
                "label": context.market_label,
                "url": context.market_url,
            }
            for name, context in sorted(retailers.items())
            if source_retailer_counts.get(name, 0)
            and clean_text(context.market_label)
            and clean_text(context.market_label).casefold() != name.casefold()
        ]

        ordered = sorted(filtered, key=lambda offer: offer_sort_key(offer, sort))
        page_size = max(1, min(int(page_size), 100))
        page_count = max(1, (len(ordered) + page_size - 1) // page_size)
        page = max(1, min(int(page), page_count))
        start = (page - 1) * page_size
        selected = ordered[start:start + page_size]

        result = {
            "search_id": snapshot["search_id"],
            "postal_code": snapshot.get("postal_code", ""),
            "resolved_aldi_region": snapshot.get("resolved_aldi_region", "auto"),
            "offer_week": snapshot.get("offer_week", "current"),
            "cache_age_seconds": max(0, int(time.time() - float(snapshot.get("created_at", time.time())))),
            "source_offer_count": len(snapshot.get("offers", [])),
            "compared_offer_count": len(comparison_for_counts.offers),
            "filtered_offer_count": len(ordered),
            "hidden_count": hidden_count,
            "page": page,
            "page_size": page_size,
            "page_count": page_count,
            "has_next": page < page_count,
            "has_previous": page > 1,
            "retailer": selected_retailer,
            "retailers": list(selected_retailers),
            "view": normalized_view,
            "retailer_counts": counts,
            "retailer_markets": retailer_markets,
            "category": selected_category,
            "category_counts": category_counts,
            "keywords": list(normalize_keywords(keywords)),
            "selected_loyalty_programs": list(selected_programs),
            "available_loyalty_programs": available_programs(source_retailer_counts, offers),
            "loyalty_note": (
                "Es werden nur öffentlich ausgewiesene Direktpreise und Euro-Guthaben verrechnet. "
                "Personalisierte Coupons oder Punkte ohne konkreten Angebotswert werden nicht geschätzt."
            ),
            "source_states": snapshot.get("source_states", {}),
            "warnings": list(dict.fromkeys([
                *snapshot.get("request_errors", []),
                *snapshot.get("store_warnings", []),
            ]))[:12],
            "offers": [offer_for_response(offer, include_image_urls=include_image_urls) for offer in selected],
        }
        return result
