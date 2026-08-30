import pytest
from pydantic import ValidationError
from supermarkt.web import SupermarketRequest


def test_postal_code_has_no_default():
    with pytest.raises(ValidationError):
        SupermarketRequest()


def test_explicit_postal_code():
    request = SupermarketRequest(postal_code="01067")
    assert request.postal_code == "01067"
    assert request.aldi_region == "auto"


def test_manual_aldi_regions_include_border_choice():
    for value in ("nord", "sued", "both"):
        assert SupermarketRequest(postal_code="51643", aldi_region=value).aldi_region == value
