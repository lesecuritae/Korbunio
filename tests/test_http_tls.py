import ssl

import certifi

from supermarkt import http
from supermarkt.http import HttpClient, trusted_ssl_context


def test_context_trusts_certifi_and_keeps_verification_on():
    """Windows-Python erreicht den Systemspeicher oft nicht.

    Der Kontext bringt deshalb certifi mit, darf die Prüfung aber unter keinen
    Umständen abschwächen.
    """
    context = trusted_ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.get_ca_certs(), "keine Wurzelzertifikate geladen"
    assert certifi.where()


def test_requests_are_sent_with_that_context(monkeypatch):
    seen = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return b"ok"

    def fake_urlopen(request, timeout=None, context=None):
        seen["context"] = context
        return FakeResponse()

    monkeypatch.setattr(http, "urlopen", fake_urlopen)
    assert HttpClient(10).get_bytes("https://www.marktguru.de/") == b"ok"
    assert seen["context"] is trusted_ssl_context()
