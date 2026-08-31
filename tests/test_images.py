import pytest
from supermarkt import images
from supermarkt.images import ImagePrefetcher, ImageService, ImageServiceError, _public_url, is_rejected_image_url, normalize_image_url


def test_image_url_normalization():
    assert normalize_image_url("//example.org/a.webp") == "https://example.org/a.webp"
    assert is_rejected_image_url("https://example.org/logo.svg")


def test_private_image_hosts_are_blocked():
    with pytest.raises(ImageServiceError):
        _public_url("http://127.0.0.1/a.png")


def test_corrupt_image_cache_entry_is_removed(tmp_path):
    service = ImageService(cache_dir=tmp_path)
    key = service.cache_key(source_url="https://example.org/product.png", product="Produkt", retailer="Markt")
    data_path, meta_path = service._paths(key)
    data_path.write_bytes(b"not-an-image")
    meta_path.write_text('{"content_type":"image/png"}', encoding="utf-8")

    assert service._read(key) is None
    assert not data_path.exists()
    assert not meta_path.exists()


def test_prefetch_tracking_discards_expired_entries(monkeypatch):
    class Service:
        @staticmethod
        def cache_key(*, source_url, product, retailer):
            return source_url

    class Pool:
        @staticmethod
        def submit(*_args):
            return None

    now = [1000.0]
    monkeypatch.setattr(images.time, "monotonic", lambda: now[0])
    prefetcher = ImagePrefetcher(Service(), workers=1, retry_seconds=60)
    prefetcher._pool.shutdown(wait=True)
    prefetcher._pool = Pool()
    prefetcher.queue(source_url="https://example.org/one.png", product="One", retailer="Market")
    now[0] += 61
    prefetcher.queue(source_url="https://example.org/two.png", product="Two", retailer="Market")

    assert set(prefetcher._queued) == {"https://example.org/two.png"}
