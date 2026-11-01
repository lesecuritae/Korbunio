import asyncio
import types

import pytest
from mcp.client import Client

from supermarkt import mcp_server, runtime
from supermarkt.images import ImageServiceError
from supermarkt.service import SupermarketEngine
from test_mcp_completeness import _install, _offer


class Images:
    """Serves bytes for ok.* URLs; everything else fails like a dead link / 404 / placeholder rejection."""

    def __init__(self):
        self.calls = []

    def get(self, *, source_url="", product="", retailer="", **_):
        self.calls.append(source_url)
        if "ok" not in source_url:
            raise ImageServiceError("tot", 404)
        return types.SimpleNamespace(data=b"\x89PNGx", content_type="image/png", origin="test")


@pytest.fixture(autouse=True)
def runtime_fakes(monkeypatch, tmp_path):
    from supermarkt import config
    monkeypatch.setattr(config, "HISTORY_DB", tmp_path / "h.sqlite3")
    monkeypatch.setattr(runtime, "get_engine", lambda: SupermarketEngine())
    images = Images()
    monkeypatch.setattr(runtime, "get_image_service", lambda: images)
    monkeypatch.setenv("SUPERMARKT_MCP_WARMUP", "0")
    for store in (mcp_server._inflight, mcp_server._load_failures, mcp_server._last_used):
        store.clear()
    mcp_server._new_postal_codes.clear()
    return images


def run(arguments):
    async def go():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool("find_offers", {"postal_code": "01067", "limit": 25, **arguments})
    return asyncio.run(go())


def img(o, url):
    return {**o, "image_url": url}


def test_missing_own_image_borrows_same_article_from_other_retailer_and_says_so(runtime_fakes, monkeypatch):
    _install(monkeypatch, [
        _offer(1, "Netto Marken-Discount", "Monster Energy Drink 500 ml", 0.88),
        img(_offer(2, "REWE", "Monster Energy Energy Drink 500 ml", 0.99), "https://img.example/ok-rewe.jpg"),
    ])
    result = run({"product": "Monster", "max_images": 1})
    first = result.structured_content["offers"][0]
    assert first["retailer"] == "Netto Marken-Discount" and first["image_url"] is None
    assert (first["image_source"], first["image_match"]) == ("same_article_other_retailer", "exact")
    assert first["image_fallback_url"].endswith("ok-rewe.jpg")
    labels = [c.text for c in result.content if c.type == "text" and c.text.startswith("Bild:")]
    assert labels and "REWE" in labels[0] and "gleicher Artikel" in labels[0]


def test_different_flavour_or_zero_variant_is_not_borrowed(runtime_fakes, monkeypatch):
    _install(monkeypatch, [
        _offer(1, "Netto Marken-Discount", "Monster Energy Drink 500 ml", 0.88),
        img(_offer(2, "REWE", "Monster Energy Ultra Zero 500 ml", 0.99), "https://img.example/ok-zero.jpg"),
        img(_offer(3, "Lidl", "Rockstar Energy Drink 500 ml", 0.89), "https://img.example/ok-rockstar.jpg"),
    ])
    result = run({"product": "Energy", "max_images": 1})
    by_retailer = {o["retailer"]: o for o in result.structured_content["offers"]}
    assert by_retailer["Netto Marken-Discount"]["image_source"] == "" and by_retailer["Netto Marken-Discount"]["image_fallback_url"] is None
    # the offers that do have working own images are shown instead; nothing is falsely labelled
    assert by_retailer["Lidl"]["image_source"] == "own" or by_retailer["REWE"]["image_source"] == "own"


def test_dead_own_link_falls_back_to_donor_and_different_pack_is_labelled_substitute(runtime_fakes, monkeypatch):
    _install(monkeypatch, [
        img(_offer(1, "Kaufland", "RED BULL Energy Drink 4 x 250 ml", 3.99), "https://img.example/dead.jpg"),
        img(_offer(2, "Müller", "RED BULL Energy Drink 250 ml", 1.59), "https://img.example/ok-mueller.jpg"),
    ])
    result = run({"product": "Red Bull", "max_images": 2})
    kaufland = next(o for o in result.structured_content["offers"] if o["retailer"] == "Kaufland")
    assert (kaufland["image_source"], kaufland["image_match"]) == ("same_article_other_retailer", "substitute")
    assert "Packung abweichend" in kaufland["image_note"] and kaufland["image_url"].endswith("dead.jpg")


def test_nothing_suitable_says_so_instead_of_staying_silent_and_download_attempts_stay_bounded(runtime_fakes, monkeypatch):
    offers = [img(_offer(i, f"Händler{i}", f"Produkt {i} Energy", 1 + i / 10), f"https://img.example/dead{i}.jpg") for i in range(10)]
    _install(monkeypatch, offers)
    result = run({"product": "Energy", "max_images": 3})
    assert "Kein passendes Produktbild" in result.content[0].text
    assert len(runtime_fakes.calls) <= 6  # 6 offers tried, no donor matches -> no extra downloads
