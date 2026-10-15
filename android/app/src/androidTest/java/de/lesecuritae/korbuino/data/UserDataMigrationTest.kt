package de.lesecuritae.korbuino.data

import androidx.room.Room
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class UserDataMigrationTest {
    @Test fun versionSixMigrationPreservesListStateFavoritesAndUnrelatedData() {
        val helper = FrameworkSQLiteOpenHelperFactory().create(SupportSQLiteOpenHelper.Configuration.builder(
            ApplicationProvider.getApplicationContext()).callback(object : SupportSQLiteOpenHelper.Callback(6) {
            override fun onCreate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE products (id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL)")
                db.execSQL("INSERT INTO products VALUES ('milk', 'Frische Milch')")
                db.execSQL("CREATE TABLE favorites (productId TEXT PRIMARY KEY NOT NULL, createdAt INTEGER NOT NULL)")
                db.execSQL("INSERT INTO favorites VALUES ('milk', 123)")
                db.execSQL("INSERT INTO favorites VALUES ('missing', 456)")
                db.execSQL("CREATE TABLE shopping_list_items (listId TEXT NOT NULL, productId TEXT NOT NULL, quantity INTEGER NOT NULL, checked INTEGER NOT NULL, note TEXT NOT NULL, PRIMARY KEY(listId,productId))")
                db.execSQL("INSERT INTO shopping_list_items VALUES ('default', 'milk', 4, 1, 'keep note')")
                db.execSQL("INSERT INTO shopping_list_items VALUES ('holiday', 'milk', 2, 0, 'other list')")
                db.execSQL("CREATE TABLE offers (id TEXT PRIMARY KEY NOT NULL, priceCents INTEGER NOT NULL)")
                db.execSQL("INSERT INTO offers VALUES ('old',99)")
                db.execSQL("CREATE TABLE settings (`key` TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)")
                db.execSQL("INSERT INTO settings VALUES ('postal_code','78462')")
            }
            override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
        }).build())
        try {
            val db = helper.writableDatabase
            KorbuinoDatabase.MIGRATION_6_7.migrate(db)
            db.query("SELECT itemId, quantity, checked, note FROM shopping_list_items WHERE listId='default'").use {
                assertTrue(it.moveToFirst()); assertEquals("milk", it.getString(0)); assertEquals(4, it.getInt(1))
                assertEquals(1, it.getInt(2)); assertEquals("keep note", it.getString(3))
            }
            db.query("SELECT query, createdAt, preferredRetailerIdsJson, notificationsEnabled FROM favorites ORDER BY createdAt").use {
                assertTrue(it.moveToFirst()); assertEquals("Frische Milch", it.getString(0)); assertEquals(123L, it.getLong(1))
                assertEquals("[]", it.getString(2)); assertEquals(0, it.getInt(3))
                assertTrue(it.moveToNext()); assertEquals("missing", it.getString(0))
            }
            for ((table, count) in listOf("products" to 1, "offers" to 1, "settings" to 1, "shopping_list_items" to 2)) {
                db.query("SELECT count(*) FROM $table").use { assertTrue(it.moveToFirst()); assertEquals(count, it.getInt(0)) }
            }
            db.execSQL("INSERT INTO shopping_list_items VALUES ('default','milk',3,0,'second retailer','milk:aldi','aldi',NULL)")
            db.query("SELECT count(*) FROM shopping_list_items WHERE productId='milk'").use {
                assertTrue(it.moveToFirst()); assertEquals(3, it.getInt(0))
            }
        } finally { helper.close() }
    }

    @Test fun exportedSchemaSixUpgradesAndRoomValidatesSchemaSeven() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val name = "issue58-real-schema-migration.db"
        context.deleteDatabase(name)
        val schema = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().context.assets
            .open("de.lesecuritae.korbuino.data.KorbuinoDatabase/6.json").bufferedReader().use {
                org.json.JSONObject(it.readText()).getJSONObject("database")
            }
        val helper = FrameworkSQLiteOpenHelperFactory().create(SupportSQLiteOpenHelper.Configuration.builder(context)
            .name(name).callback(object : SupportSQLiteOpenHelper.Callback(6) {
                override fun onCreate(db: SupportSQLiteDatabase) {
                    val entities = schema.getJSONArray("entities")
                    for (index in 0 until entities.length()) {
                        val entity = entities.getJSONObject(index)
                        val table = entity.getString("tableName")
                        db.execSQL(entity.getString("createSql").replace("\${TABLE_NAME}", table))
                        // Older exported tables omit this optional field when no indexes exist.
                        val indices = entity.optJSONArray("indices") ?: org.json.JSONArray()
                        for (i in 0 until indices.length()) db.execSQL(indices.getJSONObject(i).getString("createSql").replace("\${TABLE_NAME}", table))
                    }
                    db.execSQL("INSERT INTO products(id,name,brand,normalizedKey,gtin) VALUES('saved','Coca-Cola','','saved',NULL)")
                    db.execSQL("INSERT INTO favorites(productId,createdAt) VALUES('saved',42)")
                    db.execSQL("INSERT INTO shopping_list_items VALUES('default','saved',6,1,'preserve')")
                }
                override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
            }).build())
        helper.writableDatabase
        helper.close()
        val db = Room.databaseBuilder(context,KorbuinoDatabase::class.java,name).addMigrations(KorbuinoDatabase.MIGRATION_6_7).build()
        try {
            assertEquals(7, db.openHelper.writableDatabase.version)
            val row = db.shoppingListDao().allItems().single()
            assertEquals(6,row.quantity); assertTrue(row.checked); assertEquals("preserve",row.note)
            assertEquals("Coca-Cola",db.favoriteDao().all().single().query)
        } finally { db.close(); context.deleteDatabase(name) }
    }

    @Test fun favoriteWishesPersistWithoutProductsOrOffersAndRowsHaveIndependentIdentity() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(ApplicationProvider.getApplicationContext(), KorbuinoDatabase::class.java).build()
        try {
            val favorite = FavoriteEntity("wish", 1, "Em Eukal", "[\"kaufland\"]", 100,
                includeCurrentWeek = true, includeNextWeek = false, notificationsEnabled = true, postalCode = "78462")
            db.favoriteDao().upsert(favorite)
            assertEquals(listOf(favorite), db.favoriteDao().all())
            assertEquals(listOf(favorite), db.favoriteDao().observeAll().first())
            db.shoppingListDao().upsertAll(listOf(
                ShoppingListItemEntity("default", "missing-product", 2, true, "first", "a", "rewe", "offer1"),
                ShoppingListItemEntity("default", "missing-product", 3, false, "second", "b", "aldi", "offer2")))
            val rows = db.shoppingListDao().observeDefault().first()
            assertEquals(setOf("a", "b"), rows.map { it.itemId }.toSet())
            db.shoppingListDao().remove("a")
            assertEquals("b", db.shoppingListDao().allItems().single().itemId)
            db.favoriteDao().remove("wish")
            assertTrue(db.favoriteDao().all().isEmpty())
        } finally { db.close() }
    }
}
