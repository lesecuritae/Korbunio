from supermarkt.access import build_image_proxy_url
from supermarkt.service import SupermarketEngine
from test_mcp_completeness import _offer, _snapshot


def page(offers):
    return SupermarketEngine().page(_snapshot(offers), filter_text="", view="all", sort="price", include_image_urls=True, page_size=100)


def with_img(o, url):
    return {**o, "image_url": url}


def by(result):
    return {(o["retailer"], o["product"]): o for o in result["offers"]}


def test_same_article_other_retailer_lends_its_picture_with_label_and_donor_referer():
    result = by(page([
        _offer(1, "Netto Marken-Discount", "Monster Energy Drink 500 ml", 0.88),
        {**with_img(_offer(2, "REWE", "Monster Energy Energy Drink 500 ml", 0.99), "https://img.example/rewe.jpg"), "source_url": "https://www.rewe.de/angebote/"},
    ]))
    borrowed = result[("Netto Marken-Discount", "Monster Energy Drink 500 ml")]
    assert borrowed["image_url"] == "https://img.example/rewe.jpg"
    assert (borrowed["image_source"], borrowed["image_match"]) == ("same_article_other_retailer", "exact")
    assert "REWE" in borrowed["image_note"]
    own = result[("REWE", "Monster Energy Energy Drink 500 ml")]
    assert own["image_source"] == "own" and own["image_note"] == ""
    proxied = build_image_proxy_url(borrowed)
    assert "ref=https%3A%2F%2Fwww.rewe.de%2Fangebote%2F" in proxied  # donor's referer, not the recipient's


def test_other_pack_is_labelled_substitute_and_foreign_variants_get_no_picture():
    result = by(page([
        _offer(1, "Kaufland", "Red Bull Energy Drink 4 x 250 ml", 3.99),
        with_img(_offer(2, "Müller", "Red Bull Energy Drink 250 ml", 1.59), "https://img.example/mueller.jpg"),
        _offer(3, "Lidl", "Monster Energy Drink 500 ml", 0.89),
        with_img(_offer(4, "REWE", "Monster Energy Ultra Zero 500 ml", 0.99), "https://img.example/zero.jpg"),
        with_img(_offer(5, "PENNY", "Rockstar Energy Drink 500 ml", 0.89), "https://img.example/rockstar.jpg"),
    ]))
    kaufland = result[("Kaufland", "Red Bull Energy Drink 4 x 250 ml")]
    assert kaufland["image_match"] == "substitute" and "Packung abweichend" in kaufland["image_note"]
    lidl = result[("Lidl", "Monster Energy Drink 500 ml")]
    assert not lidl["image_url"] and lidl["image_source"] == ""


def test_not_applied_without_image_urls_requested():
    result = SupermarketEngine().page(_snapshot([_offer(1, "Lidl", "Cola 1 l", 0.9), with_img(_offer(2, "REWE", "Cola 1 l", 0.8), "https://img.example/c.jpg")]),
                                      include_image_urls=False, view="all")
    assert all("image_url" not in o and "image_source" not in o for o in result["offers"])
