import json

import pytest

from supermarkt import http
from supermarkt.http import HttpClient, PostalCodeLocator
from supermarkt.models import ToolError


class FakeResponse:
    def __init__(self, body: bytes, final_url: str) -> None:
        self.body = body
        self.final_url = final_url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self) -> str:
        return self.final_url

    def read(self, _limit: int) -> bytes:
        return self.body


def test_http_client_rejects_https_redirect_to_http(monkeypatch):
    monkeypatch.setattr(
        http,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(b"ok", "http://example.org/result"),
    )

    with pytest.raises(ToolError, match="Nur HTTPS"):
        HttpClient(5).get_bytes("https://example.org/start")


def test_post_client_rejects_https_redirect_to_http(monkeypatch):
    monkeypatch.setattr(
        http,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(b"{}", "http://example.org/result"),
    )

    with pytest.raises(ToolError, match="Nur HTTPS"):
        HttpClient(5).post_form_json("https://example.org/start", {"key": "value"})


def test_postal_locator_retries_after_temporary_failure():
    class FlakyHttp:
        calls = 0

        def get_bytes(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ToolError("temporarily unavailable")
            return json.dumps([{"address": {"city": "Dresden", "state": "Sachsen"}}]).encode()

    source = FlakyHttp()
    locator = PostalCodeLocator(source)

    assert locator.locality("01067") == ""
    assert locator.locality("01067") == "Dresden"
    assert locator.state("01067") == "Sachsen"
    assert source.calls == 2
