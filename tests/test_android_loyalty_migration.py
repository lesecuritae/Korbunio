"""Exercise the shipped Room SQL against existing user data and exported schema."""

import json
import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "android/app/schemas/de.lesecuritae.korbuino.data.KorbuinoDatabase"


def test_loyalty_migration_preserves_v5_data_and_matches_room_v6():
    old = json.loads((SCHEMAS / "5.json").read_text())["database"]
    new = json.loads((SCHEMAS / "6.json").read_text())["database"]
    source = (ROOT / "android/app/src/main/java/de/lesecuritae/korbuino/data/KorbuinoDatabase.kt").read_text()
    block = source.split("object : Migration(5, 6)", 1)[1].split("private val", 1)[0]
    statements = re.findall(r'database\.execSQL\("([^"]+)"\)', block)
    assert statements
    with sqlite3.connect(":memory:") as upgraded, sqlite3.connect(":memory:") as fresh:
        for entity in old["entities"]:
            upgraded.execute(entity["createSql"].replace("${TABLE_NAME}", entity["tableName"]))
        upgraded.execute("INSERT INTO offers (id, retailerId, productId, externalId, priceCents, sourceUrl, loyaltyProgram, loyaltyPriceCents, cachedAt) VALUES ('offer', 'kaufland', 'product', 'external', 229, 'https://example.org', 'kaufland_xtra', 179, 1)")
        upgraded.execute("INSERT INTO settings (key, value) VALUES ('postal_code', '78467')")
        for statement in statements:
            upgraded.execute(statement)
        for entity in new["entities"]:
            fresh.execute(entity["createSql"].replace("${TABLE_NAME}", entity["tableName"]))
            table = entity["tableName"]
            assert sorted(row[1:] for row in upgraded.execute(f"PRAGMA table_info('{table}')")) == sorted(row[1:] for row in fresh.execute(f"PRAGMA table_info('{table}')"))
        assert upgraded.execute("SELECT priceCents, loyaltyProgram, loyaltyPriceCents, loyaltyBenefitsJson FROM offers").fetchone() == (229, "kaufland_xtra", 179, "[]")
        assert upgraded.execute("SELECT value FROM settings WHERE key='postal_code'").fetchone() == ("78467",)
