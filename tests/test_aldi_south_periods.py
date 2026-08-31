from datetime import date
import json

from supermarkt.common import deduplicate_offers
from supermarkt.http import HttpClient
from supermarkt.models import Offer, ToolError
from supermarkt.sources.aldi import OfficialAldiSource


def source() -> OfficialAldiSource:
    return OfficialAldiSource(HttpClient(5))


def card(text: str, identifier: str = "000000000000123456", group: str = "") -> dict:
    return {
        "url": f"https://www.aldi-sued.de/produkt/test-artikel-{identifier}",
        "label": "Test Artikel 1 kg",
        "text_parts": [text, "1,29 €"],
        "group_label": group,
        "image_url": "",
    }


def test_multi_product_frame_keeps_every_independently_priced_product(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.aldi.offer_reference_date", lambda: date(2026, 8, 26))
    frame = {
        "url": "https://www.aldi-sued.de/produkt/cola-rahmen-000000000000999999",
        "label": "Pepsi oder Schwip Schwap",
        "text_parts": [
            "Pepsi oder Schwip Schwap",
            "Verschiedene Sorten, koffeinhaltig, je 1,25-l-Flasche",
            "0,99 €",
            "Coca-Cola Original, Zero oder Fanta Exotic",
            "Teilweise koffeinhaltig, 6 x 0,33-l-Flasche",
            "7,99 €",
        ],
        "group_label": "Angebote ab Montag 24.8.",
        "image_url": "https://example.invalid/cola-frame.jpg",
    }

    offers = source()._south_card_to_offers(frame, date(2026, 8, 24), date(2026, 8, 29), 1)

    assert [(offer.name, offer.price) for offer in offers] == [
        ("Pepsi oder Schwip Schwap", 0.99),
        ("Coca-Cola Original, Zero oder Fanta Exotic", 7.99),
    ]
    assert len({offer.offer_id for offer in offers}) == 2
    assert all(offer.valid_from == "2026-08-24" for offer in offers)
    assert all(offer.valid_until == "2026-08-29" for offer in offers)


def test_normal_week_card_uses_global_period(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.aldi.offer_reference_date", lambda: date(2026, 8, 26))
    offer = source()._south_card_to_offer(card("Test Artikel"), date(2026, 8, 24), date(2026, 8, 29), 1)
    assert offer is not None
    assert (offer.valid_from, offer.valid_until) == ("2026-08-24", "2026-08-29")
    assert offer.validity_label == "24.08. – 29.08.2026"


def test_friday_saturday_card_overrides_week(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.aldi.offer_reference_date", lambda: date(2026, 8, 26))
    offer = source()._south_card_to_offer(card("Nur Fr/Sa"), date(2026, 8, 24), date(2026, 8, 29), 1)
    assert offer is not None
    assert (offer.valid_from, offer.valid_until) == ("2026-08-28", "2026-08-29")
    assert offer.validity_label == "Nur Fr. 28.08., Sa. 29.08."


def test_individual_action_days_are_preserved(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.aldi.offer_reference_date", lambda: date(2026, 8, 26))
    offer = source()._south_card_to_offer(card("Mo, Do und Sa"), date(2026, 8, 24), date(2026, 8, 29), 1)
    assert offer is not None
    assert (offer.valid_from, offer.valid_until) == ("2026-08-24", "2026-08-29")
    assert offer.validity_label == "Nur Mo. 24.08., Do. 27.08., Sa. 29.08."


def test_group_period_is_used_before_week_fallback(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.aldi.offer_reference_date", lambda: date(2026, 8, 26))
    offer = source()._south_card_to_offer(
        card("Test Artikel", group="Angebote ab Donnerstag 27.8."),
        date(2026, 8, 24), date(2026, 8, 29), 1,
    )
    assert offer is not None
    assert (offer.valid_from, offer.valid_until) == ("2026-08-27", "2026-08-29")


def test_loose_produce_price_with_base_unit_is_not_dropped(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.aldi.offer_reference_date", lambda: date(2026, 8, 26))
    loose = card("Bio Hokkaido, lose")
    loose["text_parts"] = ["Bio Hokkaido, lose", "1,39 €", "/1 kg"]
    offer = source()._south_card_to_offer(
        loose,
        date(2026, 8, 24), date(2026, 8, 29), 1,
    )
    assert offer is not None
    assert offer.price == 1.39


def test_aldi_south_keeps_only_explicit_deposit(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.aldi.offer_reference_date", lambda: date(2026, 8, 26))
    explicit = card("Energy Drink 0,33 l zzgl. 0,25 € Pfand")
    offer = source()._south_card_to_offer(explicit, date(2026, 8, 24), date(2026, 8, 29), 1)
    assert offer is not None and offer.deposit == 0.25

    implicit = card("Energy Drink 0,33-l-Dose", identifier="000000000000123457")
    offer = source()._south_card_to_offer(implicit, date(2026, 8, 24), date(2026, 8, 29), 2)
    assert offer is not None and offer.deposit is None


def test_single_card_does_not_split_base_price_old_price_or_deposit_into_products(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.aldi.offer_reference_date", lambda: date(2026, 8, 26))
    rio = {
        "url": "https://www.aldi-sued.de/produkt/rio-d-oro-orangennektar-1-5-l-000000000297839001",
        "label": "",
        "text_parts": [
            "Vegan", "RIO D' ORO", "Orangennektar 1,5 l", "1,5 l",
            "(0,93 €/1 l)", "Spare 17 %", "1,39 €", "²", "1,69 €",
            "+ 0,25 € Pfand EINWEG",
        ],
        "group_label": "Angebote ab Montag 24.8.",
        "image_url": "https://example.invalid/orangennektar.jpg",
    }

    offers = source()._south_card_to_offers(rio, date(2026, 8, 24), date(2026, 8, 29), 1)

    assert len(offers) == 1
    assert offers[0].name == "RIO D ORO Orangennektar 1 5 L"
    assert offers[0].price == 1.39
    assert offers[0].deposit == 0.25
    assert offers[0].base_price == 0.93


def make_offer(label: str, start: str | None, end: str | None, *, price: float = 1.29, pack: str = "1kg") -> Offer:
    return Offer(
        offer_id="aldi-sued:123456", retailer="ALDI Süd", category="Weitere Angebote",
        name="Test Artikel", brand="", description="", price=price, base_price=None,
        base_unit="", pack_signature=pack, validity_label=label, match_key="test",
        source_url="https://www.aldi-sued.de/angebote", valid_from=start, valid_until=end,
    )


def test_duplicate_parser_find_prefers_precise_period():
    vague = make_offer("Aktuelle Woche", None, None)
    precise = make_offer("28.08. – 29.08.2026", "2026-08-28", "2026-08-29")
    result = deduplicate_offers([vague, precise])
    assert result == [precise]


def test_same_period_prefers_specific_day_label_over_generic_range():
    generic = make_offer("28.08. – 29.08.2026", "2026-08-28", "2026-08-29")
    specific = make_offer("Nur Fr. 28.08., Sa. 29.08.", "2026-08-28", "2026-08-29")
    assert deduplicate_offers([generic, specific]) == [specific]


def test_real_different_actions_prices_and_packs_remain():
    week = make_offer("24.08. – 29.08.2026", "2026-08-24", "2026-08-29")
    weekend = make_offer("28.08. – 29.08.2026", "2026-08-28", "2026-08-29")
    other_price = make_offer("28.08. – 29.08.2026", "2026-08-28", "2026-08-29", price=1.49)
    other_pack = make_offer("28.08. – 29.08.2026", "2026-08-28", "2026-08-29", pack="500g")
    assert deduplicate_offers([week, weekend, other_price, other_pack]) == [week, weekend, other_price, other_pack]


def test_dom_parser_attaches_nearest_offer_group(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.aldi.offer_reference_date", lambda: date(2026, 8, 26))
    page = """
      <h2>Wochenangebote Mo., 24.8. – Sa., 29.8.</h2>
      <a href="/produkt/test-artikel-000000000000123456">Test Artikel 1 kg 1,29 €</a>
      <h2>Angebote zum Wochenende ab 28.8.</h2>
      <a href="/produkt/test-zwei-000000000000654321">Test Zwei 500 g 0,99 €</a>
    """
    offers = source()._south_dom_offers(page, "https://www.aldi-sued.de/angebote")
    assert [(offer.valid_from, offer.valid_until) for offer in offers] == [
        ("2026-08-24", "2026-08-29"),
        ("2026-08-28", "2026-08-29"),
    ]


def test_offer_crawl_keeps_current_action_days_not_old_or_theme_pages(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.aldi.offer_reference_date", lambda: date(2026, 8, 26))
    page = """
      <a href="/angebote/2026-08-21">alt</a>
      <a href="/angebote/2026-08-24">Montag</a>
      <a href="/angebote/2026-08-27">Donnerstag</a>
      <a href="/angebote/2026-08-28?page=2">Freitag Seite 2</a>
      <a href="/angebote/2026-08-28?theme=Snacks">redundanter Themenfilter</a>
      <a href="/angebote/2026-08-31">nächste Woche</a>
      <a href="/produkte/wochenangebote/k/123">redundanter Parserweg</a>
    """
    assert source()._south_offer_urls(page) == [
        "https://www.aldi-sued.de/angebote/2026-08-24",
        "https://www.aldi-sued.de/angebote/2026-08-27",
        "https://www.aldi-sued.de/angebote/2026-08-28?page=2",
    ]


def test_aldi_south_discovers_only_official_brochure_links():
    page = """
      <a href="https://prospekt.aldi-sued.de/kw35-26-op-mp/page/2-3">Aktueller Prospekt</a>
      <a href="https://prospekt.aldi-sued.de/kw35-26-op-mp">Derselbe Prospekt</a>
      <a href="https://evil.example/kw35-26-op-mp">Fremde Quelle</a>
    """
    assert source()._south_brochure_urls(page) == [
        "https://prospekt.aldi-sued.de/kw35-26-op-mp"
    ]


def test_aldi_south_brochure_hotspots_add_missing_food_and_produce(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.aldi.offer_reference_date", lambda: date(2026, 8, 28))
    publication = {
        "id": 3305493,
        "numPages": 3,
        "cacheToken": "fixture",
        "config": {
            "canonicalUrl": "https://prospekt.aldi-sued.de/kw35-26-op-mp/",
            "websiteUrl": "https://www.aldi-sued.de/",
            "description": "Aktuelle Angebote für: Montag 24.08.2026 I Samstag 29.08.2026",
        },
    }
    page = f"<script>var data = {json.dumps(publication)}; Reader.start()</script>"
    spreads = [{"pages": [{"number": 2}, {"number": 3}]}]
    hotspots = [{
        "type": "product",
        "products": [
            {
                "id": 1, "title": "Balisto®", "description": "Versch. Sorten; je 8 x 18,5 g",
                "price": "3.49", "discountedPrice": "1.79", "productType": "Süßwaren",
                "customLabel1": "24.8.", "customLabel9": "kg-Preis 12.09",
                "photoSharingUrl": "https://aldi-assets.publitas.com/feed-images/balisto.png",
            },
            {
                "id": 2, "title": "Der Große Bauer", "description": "250-g-Becher",
                "price": "0.99", "discountedPrice": "0.39", "productType": "Molkerei",
                "customLabel1": "24.8.",
            },
            {
                "id": 3, "title": "Nektarinen", "description": "1-kg-Schale",
                "price": "1.49", "productType": "Obst - Steinobst", "customLabel1": "24.8.",
            },
        ],
    }]
    fixture = {
        "https://prospekt.aldi-sued.de/kw35-26-op-mp": page,
        "https://prospekt.aldi-sued.de/kw35-26-op-mp/spreads.json?version=fixture": spreads,
        "https://prospekt.aldi-sued.de/kw35-26-op-mp/page/2-3/hotspots_data.json?version=fixture": hotspots,
    }
    aldi = source()
    monkeypatch.setattr(aldi, "_south_get_html", lambda url: fixture[url])
    monkeypatch.setattr(aldi, "_south_get_json_value", lambda url: fixture[url])

    offers = aldi._south_brochure_offers("https://prospekt.aldi-sued.de/kw35-26-op-mp")

    assert [(offer.name, offer.price) for offer in offers] == [
        ("Balisto®", 1.79), ("Der Große Bauer", 0.39), ("Nektarinen", 1.49),
    ]
    assert offers[0].base_price == 12.09
    assert offers[0].image_url == "https://aldi-assets.publitas.com/feed-images/balisto.png"
    assert all(offer.valid_from == "2026-08-24" and offer.valid_until == "2026-08-29" for offer in offers)


def test_aldi_south_brochure_keeps_deposit_from_official_price_label():
    offer = source()._south_brochure_product_offer(
        {
            "id": 69973612, "title": "Pils", "description": "0,5-l-Dose",
            "discountedPrice": "0.65", "customLabel9": "l-Preis 1.30; zzgl. Pfand 0.25",
            "photoSharingUrl": "https://aldi-assets.publitas.com/feed-images/pils.png",
        },
        "https://prospekt.aldi-sued.de/kw35-26-op-mp",
        (date(2026, 8, 24), date(2026, 8, 29)),
    )

    assert offer is not None
    assert offer.price == 0.65
    assert offer.deposit == 0.25
    assert offer.base_price == 1.30
    assert offer.image_url == "https://aldi-assets.publitas.com/feed-images/pils.png"


def test_aldi_south_brochure_keeps_official_brand_and_product_image():
    offer = source()._south_brochure_product_offer(
        {
            "id": 69973898,
            "title": "PiCK UP!",
            "brand": "LEIBNIZ",
            "description": "Versch. Sorten; je 308-g-Packung",
            "price": "3.49",
            "photoUrls": [{
                "thumb": "/images?gId=7&height=200&src=pick-up.png&width=200&s=signed",
                "full": "/images?gId=7&src=pick-up.png&s=full",
            }],
            "photoSharingUrl": "https://aldi-assets.publitas.com/feed-images/leibniz-pick-up.png",
        },
        "https://prospekt.aldi-sued.de/current",
        (date(2026, 8, 24), date(2026, 8, 29)),
    )

    assert offer is not None
    assert offer.brand == "LEIBNIZ"
    assert offer.name == "LEIBNIZ PiCK UP!"
    assert offer.image_url == (
        "https://prospekt.aldi-sued.de/images?gId=7&height=200&src=pick-up.png&width=200&s=signed"
    )


def test_aldi_south_brochure_allows_missing_optional_brand_and_image():
    offer = source()._south_brochure_product_offer(
        {"id": 7, "title": "Nektarinen", "description": "1-kg-Schale", "price": "1.49"},
        "https://prospekt.aldi-sued.de/current",
        (date(2026, 8, 24), date(2026, 8, 29)),
    )

    assert offer is not None
    assert offer.brand == ""
    assert offer.image_url == ""


def test_aldi_south_brochure_multiplies_per_container_deposit_for_multipack():
    offer = source()._south_brochure_product_offer(
        {
            "id": 69973894, "title": "Coca-Cola oder Fanta",
            "description": "Je 18 x 0,33 l = 5,94-l-Packung", "price": "7.99",
            "customLabel9": "l-Preis 1.35; zzgl. Pfand 0.25",
            "photoSharingUrl": "https://aldi-assets.publitas.com/feed-images/cola.png",
        },
        "https://prospekt.aldi-sued.de/kw35-26-op-mp",
        (date(2026, 8, 24), date(2026, 8, 29)),
    )

    assert offer is not None
    assert offer.pack_signature.startswith("18x330ml")
    assert offer.deposit == 4.50


def test_aldi_south_rejects_future_brochure(monkeypatch):
    monkeypatch.setattr("supermarkt.sources.aldi.offer_reference_date", lambda: date(2026, 8, 28))
    publication = {
        "config": {
            "canonicalUrl": "https://prospekt.aldi-sued.de/kw36-26-op/",
            "websiteUrl": "https://www.aldi-sued.de/",
            "description": "Aktuelle Angebote für: Montag 31.08.2026 I Samstag 05.09.2026",
        }
    }
    aldi = source()
    monkeypatch.setattr(aldi, "_south_get_html", lambda _url: f"<script>var data = {json.dumps(publication)}; Reader.start()</script>")
    assert aldi._south_brochure_offers("https://prospekt.aldi-sued.de/kw36-26-op") == []


def test_aldi_south_explicit_next_week_accepts_future_brochure(monkeypatch):
    publication = {
        "cacheToken": "next-fixture",
        "config": {
            "canonicalUrl": "https://prospekt.aldi-sued.de/kw36-26-op/",
            "websiteUrl": "https://www.aldi-sued.de/",
            "description": "Aktuelle Angebote für: Montag 31.08.2026 I Samstag 05.09.2026",
        },
    }
    page = f"<script>var data = {json.dumps(publication)}; Reader.start()</script>"
    fixture = {
        "https://prospekt.aldi-sued.de/kw36-26-op": page,
        "https://prospekt.aldi-sued.de/kw36-26-op/spreads.json?version=next-fixture": [
            {"pages": [{"number": 2}]},
        ],
        "https://prospekt.aldi-sued.de/kw36-26-op/page/2/hotspots_data.json?version=next-fixture": [
            {
                "type": "product",
                "products": [
                    {
                        "id": 36,
                        "title": "Folgewochenprodukt",
                        "description": "500-g-Packung",
                        "price": "1.99",
                    },
                ],
            },
        ],
    }
    aldi = source()
    monkeypatch.setattr(aldi, "_south_get_html", lambda url: fixture[url])
    monkeypatch.setattr(aldi, "_south_get_json_value", lambda url: fixture[url])

    offers = aldi._south_brochure_offers(
        "https://prospekt.aldi-sued.de/kw36-26-op",
        reference_date=date(2026, 9, 1),
    )

    assert len(offers) == 1
    assert offers[0].name == "Folgewochenprodukt"
    assert (offers[0].valid_from, offers[0].valid_until) == (
        "2026-08-31",
        "2026-09-05",
    )


def test_aldi_south_uses_complete_current_brochure_without_mixing_web_cards(monkeypatch):
    aldi = source()
    web_offer = make_offer("24.08. – 29.08.2026", "2026-08-24", "2026-08-29")
    brochure_offer = Offer(
        **{
            **web_offer.__dict__,
            "offer_id": "aldi-sued:prospekt:balisto",
            "name": "Balisto®",
            "match_key": "balisto|148g",
            "source_url": "https://prospekt.aldi-sued.de/kw35-26-op-mp",
        }
    )
    index = '<a href="https://prospekt.aldi-sued.de/kw35-26-op-mp">Prospekt</a>'
    monkeypatch.setattr(aldi, "_south_get_html", lambda _url: index)
    monkeypatch.setattr(aldi, "_south_page_offers", lambda _page, _url: [web_offer])
    monkeypatch.setattr(aldi, "_south_brochure_offers", lambda _url: [brochure_offer])

    assert aldi._load_south() == [brochure_offer]


def test_aldi_south_does_not_report_unconfigured_future_brochure(monkeypatch):
    aldi = source()
    current = make_offer("24.08. – 29.08.2026", "2026-08-24", "2026-08-29")
    index = """
      <a href="https://prospekt.aldi-sued.de/kw35-26-op-mp">Aktuell</a>
      <a href="https://prospekt.aldi-sued.de/kw36-26-op-mp">Nächste Woche</a>
    """
    monkeypatch.setattr(aldi, "_south_get_html", lambda _url: index)
    monkeypatch.setattr(aldi, "_south_page_offers", lambda _page, _url: [])

    def brochure(url):
        if "kw35" in url:
            return [current]
        raise ToolError("ALDI Süd Prospektkonfiguration fehlt")

    monkeypatch.setattr(aldi, "_south_brochure_offers", brochure)
    assert aldi._load_south() == [current]
    assert not any("Prospektkonfiguration fehlt" in error for error in aldi.last_south_errors)


def test_aldi_south_keeps_web_cards_when_brochure_is_unavailable(monkeypatch):
    aldi = source()
    web_offer = make_offer("24.08. – 29.08.2026", "2026-08-24", "2026-08-29")
    index = '<a href="https://prospekt.aldi-sued.de/kw35-26-op-mp">Prospekt</a>'
    monkeypatch.setattr(aldi, "_south_get_html", lambda _url: index)
    monkeypatch.setattr(aldi, "_south_page_offers", lambda _page, _url: [web_offer])
    monkeypatch.setattr(aldi, "_south_brochure_offers", lambda _url: [])

    assert aldi._load_south() == [web_offer]


def test_aldi_north_keeps_product_group_periods(monkeypatch):
    payload = {
        "props": {"pageProps": {"apiData": [["OFFER_GET", {"res": {
            "algoliaDataMap": {
                "one": {"name": "Wochenmilch 1 l", "promotionPrices": [{"priceValue": 1.29}]},
                "two": {"name": "Wochenendbutter 250 g", "promotionPrices": [{"priceValue": 1.49}]},
            },
            "categories": [
                {"startDate": "2026-08-24", "endDate": "2026-08-29", "content": [{"title": "Woche", "productIds": ["one"]}]},
                {"startDate": "2026-08-28", "endDate": "2026-08-29", "content": [{"title": "Wochenende", "productIds": ["two"]}]},
            ],
        }}]]}},
    }
    page = f'<script id="__NEXT_DATA__">{json.dumps(payload)}</script>'.encode()
    aldi = source()
    monkeypatch.setattr(aldi.http, "get_bytes", lambda _url: page)
    monkeypatch.setattr("supermarkt.sources.aldi.date_is_current", lambda _start, _end: True)
    offers = aldi._load_north()
    assert [(offer.name, offer.validity_label) for offer in offers] == [
        ("Wochenmilch 1 l", "24.08. – 29.08.2026"),
        ("Wochenendbutter 250 g", "28.08. – 29.08.2026"),
    ]


def test_aldi_north_keeps_official_price_deposit_and_product_image(monkeypatch):
    payload = {
        "props": {"pageProps": {"apiData": [["OFFER_GET", {"res": {
            "algoliaDataMap": {"3932": {
                "name": "Energydrink", "brandName": "MONSTER",
                "shortDescription": "Koffein- und taurinhaltig", "salesUnit": "0,5-L-Dose",
                "isDepositProduct": True, "depositValue": 0.25,
                "promotionPrices": [{
                    "priceValue": 0.79, "validFromLocalDate": "2026-08-24",
                    "validUntilLocalDate": "2026-08-29",
                    "basePrice": [{"basePriceValue": 1.58, "basePriceScale": "Liter"}],
                }],
                "assets": [
                    {"type": "primary", "url": "https://s7g10.scene7.com/is/image/aldinord/3932_product"},
                    {"type": "gallery", "url": "https://s7g10.scene7.com/is/image/aldinord/3932_variant"},
                ],
            }},
            "categories": [{
                "startDate": "2026-08-24", "endDate": "2026-08-29",
                "content": [{"title": "Getränke", "productIds": ["3932"]}],
            }],
        }}]]}},
    }
    page = f'<script id="__NEXT_DATA__">{json.dumps(payload)}</script>'.encode()
    aldi = source()
    monkeypatch.setattr(aldi.http, "get_bytes", lambda _url: page)
    monkeypatch.setattr("supermarkt.sources.aldi.date_is_current", lambda _start, _end: True)

    offers = aldi._load_north()

    assert len(offers) == 1
    assert offers[0].price == 0.79
    assert offers[0].deposit == 0.25
    assert offers[0].base_price == 1.58
    assert offers[0].image_url == "https://s7g10.scene7.com/is/image/aldinord/3932_product"
    assert (offers[0].valid_from, offers[0].valid_until) == ("2026-08-24", "2026-08-29")
