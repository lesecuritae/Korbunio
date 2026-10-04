"""aktiv & irma weekly offers from the retailer's own HTML page (issue #48)."""

from supermarkt.compare import MARKTGURU_RETAILER_SLUGS
from supermarkt.diagnostics import OPTIONAL_RETAILERS
from supermarkt.models import AGGREGATOR_RETAILERS, SPEC_BY_NAME
from supermarkt.sources.aktiv_irma import OfficialAktivIrmaSource

# A faithful slice of https://www.aktiv-irma.de/angebote/: category tabs
# (li.js-tabs-content) each carrying their own "… gültig vom … bis zum …"
# label, with product cards whose price box sits inside the description
# container (the real page bleeds the prices into that text).
FIXTURE = """
<ul class="uk-list js-tabs-switcher">
  <li class="js-tabs-content fr-active">
    <h3>Tiefk&uuml;hlkost: Aktiv &amp; Irma g&uuml;ltig vom 05.10.2026 bis zum 10.10.2026</h3>
    <div class="uk-grid">
      <div class="fr-product">
        <div class="uk-card uk-card-primary fr-product-card">
          <div class="fr-product-card-media">
            <img src="/media/bild_produkt/frosta.psd" data-srcset="/media/bild_produkt/frosta.psd">
          </div>
          <div class="fr-product-card-body">
            <h3 class="uk-card-title">Frosta Kleine Mahlzeit Fertiggerichte</h3>
            <div class="product-description-container">
              <p>versch. Sorten</p>
              <p class="uk-text-small">500g (1kg=3,98)</p>
              <div class="fr-price-box">
                <span class="fr-price-statt">statt 2,99</span>
                <span class="fr-price-angebot">1,99</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </li>
  <li class="js-tabs-content">
    <h3>Fleisch: Kramerhof g&uuml;ltig vom 05.10.2026 bis zum 07.10.2026</h3>
    <div class="uk-grid">
      <div class="fr-product">
        <div class="uk-card uk-card-primary fr-product-card">
          <div class="fr-product-card-body">
            <h3 class="uk-card-title">Schweinenacken</h3>
            <div class="product-description-container">
              <p>frisch aus der Region</p>
              <p class="uk-text-small">(1kg=6,99)</p>
              <div class="fr-price-box">
                <span class="fr-price-statt">statt 8,99</span>
                <span class="fr-price-angebot">6,99</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </li>
</ul>
"""


def test_aktiv_irma_is_registered_as_an_optional_first_party_retailer():
    spec = SPEC_BY_NAME["aktiv & irma"]
    assert spec.optional is True
    assert spec.name in OPTIONAL_RETAILERS
    # It is a first-party HTML source, NOT a Marktguru aggregator retailer.
    assert spec.name not in AGGREGATOR_RETAILERS
    assert spec.name not in MARKTGURU_RETAILER_SLUGS


def _offers():
    return OfficialAktivIrmaSource(http=None).parse(FIXTURE)


def test_parses_offer_with_price_category_and_validity():
    offers = _offers()
    assert len(offers) == 2
    frosta = offers[0]
    assert frosta.retailer == "aktiv & irma"
    assert frosta.name == "Frosta Kleine Mahlzeit Fertiggerichte"
    assert frosta.price == 1.99
    assert frosta.category == "Tiefkühlkost"
    assert frosta.base_price == 3.98
    assert frosta.base_unit == "kg"
    assert frosta.valid_from == "2026-10-05"
    assert frosta.valid_until == "2026-10-10"
    assert frosta.offer_condition == "statt 2,99"


def test_description_does_not_contain_the_price_tokens():
    frosta = _offers()[0]
    assert "statt" not in frosta.description.lower()
    assert "1,99" not in frosta.description
    assert "versch. Sorten" in frosta.description


def test_partner_supplier_is_kept_in_the_coverage_note():
    schwein = _offers()[1]
    assert schwein.category == "Fleisch"
    assert "Kramerhof" in schwein.coverage_note


def test_own_brand_offer_has_no_partner_supplier_note():
    assert _offers()[0].coverage_note == "Wochenprospekt aktiv & irma"
