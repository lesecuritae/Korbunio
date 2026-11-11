"""Dated retailer brochures, distinct from a general online Sale catalogue."""
from datetime import date

from ..common import today_berlin
from ..http import HttpClient, PostalCodeLocator
from ..models import Offer
from .kaufda import KaufdaRetailerSource


class MuellerBrochureSource:
    source_label = "KaufDA-Händlerprospekt"
    scope_note = "Müller: datierter Händlerprospekt; Filialgeltung und lokaler Bestand nicht bestätigt."
    last_market_url = "https://www.mueller.de/storefinder/"
    last_market_label = "Müller (Händlerprospekt, Filialgeltung prüfen)"

    def __init__(self, http: HttpClient, locator: PostalCodeLocator) -> None:
        self.locator = locator
        self.brochure = KaufdaRetailerSource(http, "Müller", "Müller", "Mueller", use_viewer=True)

    def load(self, postal_code: str) -> list[Offer]:
        return self.load_week(postal_code, today_berlin())

    def load_week(self, postal_code: str, target: date) -> list[Offer]:
        return self.brochure.load_publisher_brochure(target, self.locator.coordinates(postal_code))
