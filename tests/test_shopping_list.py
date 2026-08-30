from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = (ROOT / "src/supermarkt/static/shopping-core.mjs").as_uri()


def js(expression: str):
    source = f"import * as m from {json.dumps(CORE)}; console.log(JSON.stringify({expression}))"
    result = subprocess.run(
        ["node", "--input-type=module", "-e", source],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_integer_cent_totals_and_required_fixture():
    items = [
        {"name": "Milch", "quantity": 2, "retailer": "ALDI Nord", "price_cents": 129},
        {"name": "Butter", "quantity": 1, "retailer": "ALDI Nord", "price_cents": 149},
        {"name": "Kaffee", "quantity": 1, "retailer": "REWE", "price_cents": 499},
        {"name": "Energy", "quantity": 4, "retailer": "REWE", "price_cents": 79, "deposit_cents": 25},
        {"name": "Bad Pyrmonter", "quantity": 2, "retailer": "HOL’AB!", "price_cents": 555, "deposit_cents": 330},
    ]
    result = js(f"m.totals({json.dumps(items)})")
    assert result["goods_cents"] == 2332
    assert result["deposit_cents"] == 760
    assert result["total_cents"] == 3092
    assert result["unit_count"] == 10


def test_cent_regression_unknown_price_and_checked_stays_in_total():
    result = js("m.totals([{name:'A',quantity:1,price_cents:10,checked:true},{name:'B',quantity:1,price_cents:20},{name:'Brot',quantity:1,price_cents:null}])")
    assert result["goods_cents"] == 30
    assert result["unknown_price_count"] == 1


def test_offer_identity_increments_only_strict_identity():
    result = js("m.mergeItems([{name:'Milch',quantity:1,retailer:'REWE',offer_id:'one'}],[{name:'Milch',quantity:1,retailer:'REWE',offer_id:'one'},{name:'Milch Bio',quantity:1,retailer:'REWE',offer_id:'two'}])")
    assert len(result) == 2
    assert result[0]["quantity"] == 2


def test_buenting_offers_use_the_existing_canonical_shopping_model():
    result = js("""(()=>{
      const combi=m.offerToItem({offer_id:'combi-1',product:'Milch',retailer:'Combi',category:'Molkereiprodukte & Eier',pack:'1 l',regular_price:0.99});
      const famila=m.offerToItem({offer_id:'famila-1',product:'Brot',retailer:'famila Nordwest',category:'Backwaren',regular_price:null});
      const items=m.mergeItems([combi],[combi,famila]);
      return {items,totals:m.totals(items),text:m.exportText(items,new Date('2026-08-26T00:00:00Z'))};
    })()""")
    assert [(item["retailer"], item["quantity"]) for item in result["items"]] == [
        ("Combi", 2),
        ("famila Nordwest", 1),
    ]
    assert result["totals"]["goods_cents"] == 198
    assert result["totals"]["unknown_price_count"] == 1
    assert "Combi" in result["text"] and "famila Nordwest" in result["text"]


def test_text_parser_checkbox_quantity_prices_crlf_and_plain_text():
    sample = "ALDI Nord\r\n☐ 2× Milch 1 l | 1,29 € je\r\n[x] 4x Energy 0,5 l | 0,79 € je | +0,25 € Pfand je\r\n\r\nBrot"
    result = js(f"m.parseText({json.dumps(sample)})")
    assert len(result["valid"]) == 3
    assert result["valid"][0]["quantity"] == 2
    assert result["valid"][0]["price_cents"] == 129
    assert result["valid"][1]["checked"] is True
    assert result["valid"][1]["deposit_cents"] == 25
    assert result["valid"][2]["price_cents"] is None


def test_copy_and_share_text_is_complete_readable_and_html_free():
    items = [
        {"name": "Milch", "quantity": 2, "retailer": "ALDI Nord", "price_cents": 129},
        {"name": "Energy Drink", "quantity": 4, "retailer": "REWE", "price_cents": 79, "deposit_cents": 25},
        {"name": "Brot", "quantity": 1, "price_cents": None},
    ]
    text = js(f"m.exportText({json.dumps(items)},new Date('2026-08-26T00:00:00Z'))")
    readable = text.replace("\xa0", " ")
    assert "☐ 2× Milch | 1,29 € je" in readable
    assert "☐ 4× Energy Drink | 0,79 € je | +0,25 € Pfand je" in readable
    assert "☐ 1× Brot | Preis nicht bekannt" in readable
    assert "Waren: 5,74 €" in readable
    assert "Pfand: 1,00 €" in readable
    assert "Bekannte Gesamtsumme: 6,74 €" in readable
    assert "1 Artikel ohne Preis" in readable
    assert "<" not in readable and ">" not in readable
    assert "\n" in readable and "\ufffd" not in readable


def test_json_roundtrip_schema_and_separate_ids():
    result = js("m.validateDocument(m.exportDocument([{name:'Milch',quantity:2,unit:'Stück',pack:'1 l',offer_id:'offer-1',source_product_id:'source-2',ean:null,external_ids:{grocy:null}}]))[0]")
    assert result["local_item_id"] != result["offer_id"]
    assert result["offer_id"] == "offer-1"
    assert result["source_product_id"] == "source-2"
    assert result["ean"] is None


def test_kitchenowl_adapter_matches_installed_add_item_schema():
    result = js("""(()=>{
      const item=m.offerToItem({product:'Pom-Bär',brand:'FUNNY-FRISCH',pack:'75 g',ean:'4001234567890',category:'Snacks',retailer:'ALDI Nord',regular_price:0.99,valid_from:'2026-08-24',valid_until:'2026-08-29'});
      return m.kitchenOwlItem(item);
    })()""")
    assert set(result) == {"name", "description"}
    assert result["name"] == "FUNNY-FRISCH Pom-Bär"
    assert "Menge: 1" in result["description"]
    assert "Packung: 75 g" in result["description"]
    assert "Kategorie: Snacks" in result["description"]
    assert "Händler: ALDI Nord" in result["description"]
    assert "Angebot: 0,99" in result["description"]
    assert "Zeitraum: 2026-08-24 bis 2026-08-29" in result["description"]
    assert "EAN: 4001234567890" in result["description"]


def test_offer_image_uses_only_the_local_proxy_and_survives_json_roundtrip():
    result = js("""(()=>{
      const item=m.offerToItem({offer_id:'energy-1',product:'Energy',retailer:'REWE',regular_price:0.79,deposit:0.25,image_url:'/image?src=https%3A%2F%2Fexample.invalid%2Fenergy.jpg&sig=signed'});
      const restored=m.validateDocument(m.exportDocument([item]))[0];
      return {item,restored,resolved:m.resolvedImageUrl(restored.image_url,'https://korbklar.example')};
    })()""")
    assert result["item"]["image_url"].startswith("/image?")
    assert result["restored"]["image_url"] == result["item"]["image_url"]
    assert result["resolved"].startswith("https://korbklar.example/image?")


def test_shopping_image_rejects_external_and_script_urls():
    assert js("m.canonicalItem({name:'A',image_url:'javascript:alert(1)'}).image_url") is None
    assert js("m.resolvedImageUrl('https://tracker.invalid/image?x=1','https://korbklar.example')") is None


def test_import_limits_and_future_schema_are_rejected():
    assert js("(()=>{try{m.parseText('x'.repeat(m.MAX_IMPORT_BYTES+1));return false}catch{return true}})()") is True
    assert js("(()=>{try{m.validateDocument({schema_version:99,items:[]});return false}catch{return true}})()") is True


def test_shopping_frontend_is_local_only():
    shopping = (ROOT / "src/supermarkt/static/shopping.js").read_text(encoding="utf-8")
    assert "indexedDB.open" in shopping
    assert "fetch(" not in shopping
    assert "XMLHttpRequest" not in shopping
    assert "localStorage" not in shopping
    assert "document.cookie" not in shopping
    assert "navigator.share" in shopping


def test_shopping_product_images_are_bounded_without_inline_layout():
    shopping = (ROOT / "src/supermarkt/static/shopping.js").read_text(encoding="utf-8")
    styles = (ROOT / "src/supermarkt/static/shopping.css").read_text(encoding="utf-8")
    assert 'el("div","shoppingImage")' in shopping
    assert "imageBox.style.cssText" not in shopping and "image.style.cssText" not in shopping
    assert ".shoppingImage{" in styles and "flex:0 0 72px" in styles and "overflow:hidden" in styles
    assert ".shoppingImage img{" in styles and "height:100%" in styles and "object-fit:contain" in styles
