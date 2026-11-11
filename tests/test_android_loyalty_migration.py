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


def test_description_migration_preserves_v7_offers_and_matches_room_v8():
    old = json.loads((SCHEMAS / "7.json").read_text())["database"]
    new = json.loads((SCHEMAS / "8.json").read_text())["database"]
    source = (ROOT / "android/app/src/main/java/de/lesecuritae/korbuino/data/KorbuinoDatabase.kt").read_text()
    block = source.split("object : Migration(7, 8)", 1)[1].split("val MIGRATION_6_7", 1)[0]
    statements = re.findall(r'database\.execSQL\("([^"]+)"\)', block)
    assert statements == ["ALTER TABLE offers ADD COLUMN description TEXT NOT NULL DEFAULT ''",
        "DROP INDEX IF EXISTS index_products_normalizedKey",
        "CREATE INDEX index_products_normalizedKey ON products (normalizedKey)",
        "UPDATE provider_cache SET lastSuccess = NULL"]
    with sqlite3.connect(":memory:") as upgraded, sqlite3.connect(":memory:") as fresh:
        for entity in old["entities"]:
            upgraded.execute(entity["createSql"].replace("${TABLE_NAME}", entity["tableName"]))
        upgraded.execute("INSERT INTO offers (id, retailerId, productId, externalId, priceCents, sourceUrl, cachedAt, packSize) VALUES ('o', 'marktguru-lidl', 'p', 'external', 399, 'https://example.org', 1, '400 g')")
        upgraded.execute("INSERT INTO favorites (productId, createdAt) VALUES ('p', 1)")
        upgraded.execute("INSERT INTO settings (key, value) VALUES ('postal_code', '04109')")
        upgraded.execute("INSERT INTO provider_cache (providerId,lastSuccess,offerCount,retailerReachable,sourceReachable,offersAvailable,imagesAvailable,parserOk) VALUES ('edeka',123,220,1,1,1,1,1)")
        for statement in statements:
            upgraded.execute(statement)
        assert upgraded.execute("SELECT lastSuccess,offerCount FROM provider_cache WHERE providerId='edeka'").fetchone() == (None,220)
        for entity in new["entities"]:
            table = entity["tableName"]
            fresh.execute(entity["createSql"].replace("${TABLE_NAME}", table))
            assert sorted(row[1:] for row in upgraded.execute(f"PRAGMA table_info('{table}')")) == sorted(row[1:] for row in fresh.execute(f"PRAGMA table_info('{table}')"))
        assert upgraded.execute("SELECT priceCents, packSize, description FROM offers").fetchone() == (399, "400 g", "")
        upgraded.execute("UPDATE offers SET description='Versch. Sorten. Je 400 g'")
        assert upgraded.execute("SELECT id FROM offers WHERE description LIKE '%Sorten%'").fetchone() == ('o',)
        assert upgraded.execute("SELECT productId FROM favorites").fetchone() == ('p',)
        assert upgraded.execute("SELECT value FROM settings").fetchone() == ('04109',)
        # Two source-proven GTINs may share the same display name. The old
        # UNIQUE name index silently replaced the first product and orphaned offers.
        for product_id, gtin in [("beans", "4000508059087"), ("ground", "8711000708651")]:
            upgraded.execute("INSERT OR REPLACE INTO products (id,name,brand,normalizedKey,gtin) VALUES (?,?,?,?,?)",
                (product_id, "Jacobs Krönung", "Jacobs", "jacobs-kroenung", gtin))
        assert upgraded.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2
        assert next(row for row in upgraded.execute("PRAGMA index_list('products')") if row[1] == "index_products_normalizedKey")[2] == 0
        assert next(e for e in new["entities"] if e["tableName"] == "products")["indices"][0]["unique"] is False
