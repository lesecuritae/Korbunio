import pytest
from supermarkt.images import ImageServiceError, _public_url, is_rejected_image_url, normalize_image_url


def test_image_url_normalization():
    assert normalize_image_url("//example.org/a.webp") == "https://example.org/a.webp"
    assert is_rejected_image_url("https://example.org/logo.svg")


def test_private_image_hosts_are_blocked():
    with pytest.raises(ImageServiceError):
        _public_url("http://127.0.0.1/a.png")
