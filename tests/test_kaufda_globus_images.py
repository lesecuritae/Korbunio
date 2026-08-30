import json

from supermarkt.sources.kaufda import KaufdaGlobusImageSource


def page(items):
    payload = {"props": {"pageProps": {"pageInformation": {
        "publisher": {"name": "GLOBUS"},
        "offers": {"main": {"items": items}},
    }}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'


def item(**overrides):
    value = {
        "type": "OFFER", "id": "offer-1", "publisherName": "GLOBUS",
        "title": "Kinder Riegel", "description": "210 g 10er-Pack", "brand": "Ferrero",
        "validFrom": "2026-08-23T22:00:00.000+0000",
        "validUntil": "2026-08-29T21:00:00.000+0000",
        "prices": {"mainPrice": 1.99},
        "offerImages": {"url": {
            "normal": "https://content-media.bonial.biz/offer-1/main.jpg?impolicy=SEO-offer-normal",
        }},
    }
    value.update(overrides)
    return value


def test_parser_maps_only_globus_single_offer_images_and_local_dates():
    offers = KaufdaGlobusImageSource.parse(page([item()]), "https://www.kaufda.de/Neutraubling/Globus/p-r37")
    assert len(offers) == 1
    assert offers[0].name == "Ferrero Kinder Riegel"
    assert offers[0].price == 1.99
    assert offers[0].pack_signature == "210g"
    assert (offers[0].valid_from, offers[0].valid_until) == ("2026-08-24", "2026-08-29")
    assert offers[0].image_url.endswith("main.jpg?impolicy=SEO-offer-normal")


def test_parser_rejects_brochure_pages_wrong_publishers_and_priceless_promotions():
    brochure = item(offerImages={"url": {
        "normal": "https://content-media.bonial.biz/flyer/preview.jpg?impolicy=SEO-brochure-normal",
    }})
    wrong = item(id="wrong", publisherName="EDEKA")
    priceless = item(id="free", prices={"mainPrice": 0})
    assert KaufdaGlobusImageSource.parse(page([brochure, wrong, priceless]), "https://www.kaufda.de/x") == []
