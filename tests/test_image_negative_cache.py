import time

import pytest

from supermarkt.images import ImageService, ImageServiceError


def service(tmp_path):
    return ImageService(cache_dir=tmp_path / "img")


def test_dead_link_is_not_requested_again_until_ttl(tmp_path, monkeypatch):
    svc = service(tmp_path)
    calls = []

    def dead(url, *, referer=""):
        calls.append(url)
        raise ImageServiceError("HTTP 404", 502, permanent=True)

    monkeypatch.setattr(svc, "_download", dead)
    for _ in range(3):
        with pytest.raises(ImageServiceError):
            svc.get(source_url="https://img.example.com/a.jpg", product="X", retailer="R")
    assert len(calls) == 1
    # another retailer/product using the SAME dead URL is covered as well
    with pytest.raises(ImageServiceError):
        svc.get(source_url="https://img.example.com/a.jpg", product="Y", retailer="Other")
    assert len(calls) == 1


def test_transient_failures_expire_quickly_and_permanent_ones_later(tmp_path, monkeypatch):
    svc = service(tmp_path)
    attempts = []

    def flaky(url, *, referer=""):
        attempts.append(url)
        raise ImageServiceError("timeout", 502, permanent=False)

    monkeypatch.setattr(svc, "_download", flaky)
    with pytest.raises(ImageServiceError):
        svc.get(source_url="https://img.example.com/t.jpg", product="X", retailer="R")
    expires = svc._negative["https://img.example.com/t.jpg"][0]
    assert 0 < expires - time.monotonic() <= svc.NEGATIVE_TRANSIENT_SECONDS
    svc._negative["https://img.example.com/t.jpg"] = (time.monotonic() - 1, svc._negative["https://img.example.com/t.jpg"][1])
    with pytest.raises(ImageServiceError):
        svc.get(source_url="https://img.example.com/t.jpg", product="X", retailer="R")
    assert len(attempts) == 2


def test_success_clears_failure_and_unsupported_content_is_permanent(tmp_path, monkeypatch):
    svc = service(tmp_path)
    svc._remember_failure("https://img.example.com/ok.png", ImageServiceError("alt", 502))
    svc._negative["https://img.example.com/ok.png"] = (0.0, svc._negative["https://img.example.com/ok.png"][1])
    monkeypatch.setattr(svc, "_download", lambda url, *, referer="": (b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png"))
    assert svc.get(source_url="https://img.example.com/ok.png", product="X", retailer="R").content_type == "image/png"
    assert "https://img.example.com/ok.png" not in svc._negative


def test_negative_cache_is_bounded(tmp_path):
    svc = service(tmp_path)
    for i in range(svc.NEGATIVE_MAX_ENTRIES + 50):
        svc._remember_failure(f"https://img.example.com/{i}.jpg", ImageServiceError("x", 502, permanent=True))
    assert len(svc._negative) <= svc.NEGATIVE_MAX_ENTRIES
