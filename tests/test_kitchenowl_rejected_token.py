import io
import urllib.error

import pytest

from supermarkt import kitchenowl


class _Opener:
    def __init__(self, code):
        self.code = code

    def open(self, request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, self.code, "x", {}, io.BytesIO(b""))


@pytest.mark.parametrize("code", [401, 403, 422])
def test_rejected_token_is_reported_as_rejected_token_on_reads(monkeypatch, code):
    monkeypatch.setattr(kitchenowl, "_OPENER", _Opener(code))
    with pytest.raises(kitchenowl.KitchenOwlError, match="Token abgelehnt"):
        kitchenowl.call("https://k.example.test", "t", "/api/household")


def test_422_on_a_write_stays_a_plain_http_error(monkeypatch):
    monkeypatch.setattr(kitchenowl, "_OPENER", _Opener(422))
    with pytest.raises(kitchenowl.KitchenOwlError, match="HTTP 422"):
        kitchenowl.call("https://k.example.test", "t", "/api/shoppinglist/1/add-item-by-name", {"name": "x"})
