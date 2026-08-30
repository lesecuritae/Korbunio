from supermarkt.models import Offer
from supermarkt.presentation import offer_for_response


def _offer(
    *,
    name="BLACK CAT Energy Drink",
    description="4 x 0,25 Liter",
    pack="4x250ml",
    deposit=1.0,
    container_deposit=None,
    packaging_deposit=None,
):
    return Offer(
        offer_id="black-cat", retailer="Netto Marken-Discount", category="Getränke",
        name=name, brand="BLACK CAT", description=description, price=1.99,
        base_price=None, base_unit="", pack_signature=pack, validity_label="Aktuell",
        match_key="black-cat|4x250ml", source_url="https://example.invalid/", deposit=deposit,
        container_deposit=container_deposit, packaging_deposit=packaging_deposit,
    )


def test_black_cat_four_pack_shows_deposit_per_can_and_pack_total():
    result = offer_for_response(_offer(container_deposit=0.25), include_image_urls=False)
    assert result["deposit"] == 1.0
    assert result["deposit_text"] == "1,00 €"
    assert result["deposit_note"] == "Pfand: 0,25 € je Dose × 4 = 1,00 € gesamt"


def test_single_container_keeps_simple_deposit_note():
    result = offer_for_response(_offer(pack="500ml", deposit=0.25), include_image_urls=False)
    assert result["deposit_note"] == "zzgl. 0,25 € Pfand"


def test_crate_shows_bottle_and_packaging_deposit_components():
    result = offer_for_response(
        _offer(
            name="Bierkasten",
            description="24 Flaschen im Kasten",
            pack="24x500ml",
            deposit=3.42,
            container_deposit=0.08,
            packaging_deposit=1.50,
        ),
        include_image_urls=False,
    )
    assert result["deposit_note"] == (
        "Pfand: 0,08 € je Flasche × 24 + 1,50 € Kasten = 3,42 € gesamt"
    )


def test_published_multipack_total_is_not_inferred_as_per_container_deposit():
    result = offer_for_response(
        _offer(name="Getränkekiste", pack="20x500ml", deposit=3.10),
        include_image_urls=False,
    )
    assert result["deposit_note"] == "zzgl. 3,10 € Pfand"
