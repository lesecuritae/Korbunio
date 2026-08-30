from __future__ import annotations

import json
import subprocess
from pathlib import Path

from supermarkt.common import filter_offers_by_keywords, normalize_keywords
from supermarkt.models import Offer


ROOT = Path(__file__).resolve().parents[1]
CORE = (ROOT / "src/supermarkt/static/keyword-filters.mjs").as_uri()


def js(expression: str):
    source = f"import * as m from {json.dumps(CORE)}; console.log(JSON.stringify({expression}))"
    result = subprocess.run(["node", "--input-type=module", "-e", source], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def offer(name: str) -> Offer:
    return Offer(
        offer_id=name, retailer="Test", category="Test", name=name, brand="", description="",
        price=1.0, base_price=None, base_unit="", pack_signature="", validity_label="Aktuell",
        match_key=name, source_url="https://example.invalid",
    )


def test_keyword_filter_uses_product_name_or_semantics():
    values = filter_offers_by_keywords(
        [offer("Milka Alpenmilch"), offer("Deutsche Markenbutter"), offer("Kaffee Gold")],
        ("Milka", "Butter"),
    )
    assert [item.name for item in values] == ["Milka Alpenmilch", "Deutsche Markenbutter"]


def test_keywords_remove_empty_and_case_insensitive_duplicates():
    assert normalize_keywords((" Milka ", "", "milka", " Butter ")) == ("Milka", "Butter")
    assert js("m.normalizeKeywords([' Milka ','', 'milka', 'Butter'])") == ["Milka", "Butter"]


def test_keyword_json_roundtrip_and_invalid_documents():
    assert js("m.parseKeywordDocument(JSON.stringify(m.keywordDocument(['Milka','Butter'])))") == ["Milka", "Butter"]
    message = js("(()=>{try{m.parseKeywordDocument('{broken');return ''}catch(error){return error.message}})()")
    assert message == "Die Datei enthält kein gültiges JSON."
    version = js("(()=>{try{m.parseKeywordDocument('{\"version\":2,\"keywords\":[]}');return ''}catch(error){return error.message}})()")
    assert "Nicht unterstützte" in version


def test_keyword_ui_persists_and_supports_edit_delete_import_export():
    page = (ROOT / "src/supermarkt/static/results.html").read_text(encoding="utf-8")
    script = (ROOT / "src/supermarkt/static/results-v2.js").read_text(encoding="utf-8")
    assert 'id="keywordForm"' in page and 'id="keywordImport"' in page and 'id="keywordExport"' in page
    assert 'id="keywordEnabled"' in page and 'id="keywordDialog"' in page
    assert "localStorage.getItem(KEYWORD_STORAGE_KEY)" in script
    assert "localStorage.setItem(KEYWORD_STORAGE_KEY" in script
    assert "parseKeywordDocument" in script and "downloadKeywords" in script
    assert "KEYWORD_ENABLED_KEY" in script and "keywordEnabled" in script
    assert "FILTER_STORAGE_KEY" in script and 'params.append("retailers",retailer)' in script
