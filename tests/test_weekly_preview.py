"""A Thursday flyer offer must be visible in the current week's catalogue."""
from datetime import date

import pytest

from supermarkt.common import offer_validity
from supermarkt.compare import OfferMapper
from supermarkt.service import SourceLoader


def cola_offer(start='2026-10-21T22:00:00Z', end='2026-10-24T21:59:00Z'):
    return {
        'id': 25301467, 'advertisers': [{'name': 'Lidl'}],
        'brand': {'name': 'Coca-Cola'}, 'product': {'name': 'Cola'},
        'description': '6x0.33l 1.98l +1.50 Pfand, Standardpackung 0.33l',
        'price': 3.99, 'referencePrice': 2.02, 'unit': {'shortName': 'l'},
        'validityDates': [{'from': start, 'to': end}],
    }


@pytest.mark.parametrize('day,expected', [
    (date(2026, 10, 19), True), (date(2026, 10, 20), True),
    (date(2026, 10, 22), True), (date(2026, 10, 24), True),
    (date(2026, 10, 25), False), (date(2026, 10, 26), False),
])
def test_thursday_flyer_is_visible_during_remaining_week(day, expected):
    selected, label = offer_validity(cola_offer(), day)
    assert selected is expected
    assert label == '22.10.–24.10.2026'


@pytest.mark.parametrize('start,end', [
    ('2026-10-12', '2026-10-17'),  # expired last week
    ('2026-10-19', '2026-10-19'),  # expired yesterday
    ('2026-10-25T23:00:00Z', '2026-10-31T22:59:00Z'),  # Monday after DST switch
])
def test_expired_and_next_week_offers_stay_excluded(start, end):
    assert offer_validity(cola_offer(start, end), date(2026, 10, 20))[0] is False


def test_mapper_keeps_real_lidl_pack_price_and_validity():
    offer = OfferMapper().map_one(cola_offer(), SourceLoader._contexts(), date(2026, 10, 19))
    assert offer is not None
    assert offer.retailer == 'Lidl' and offer.name == 'Coca-Cola Cola'
    assert offer.valid_from == '2026-10-22' and offer.valid_until == '2026-10-24'
    assert offer.price == 3.99
    assert offer.pack_signature.startswith('6x330ml')
    assert offer.deposit == 1.50
    assert offer.validity_label == '22.10.–24.10.2026'
