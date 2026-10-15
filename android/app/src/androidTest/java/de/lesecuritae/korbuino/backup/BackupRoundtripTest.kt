package de.lesecuritae.korbuino.backup

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import de.lesecuritae.korbuino.data.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream

class BackupRoundtripTest {
    @Test fun exportImportPreservesDuplicateNamesRetailersQuantitiesAndFavoritesWithoutSecrets() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val name="issue58-backup-test.db"
        context.deleteDatabase(name)
        fun database() = Room.databaseBuilder(context,KorbuinoDatabase::class.java,name).build()
        val items=listOf(ShoppingListItemEntity("default","a",3,true,"note","first","rewe","one"),
            ShoppingListItemEntity("default","b",6,false,"second note","second","kaufland","two"))
        var db=database()
        val favorite=FavoriteEntity("favorite",5,"Coca-Cola","[\"rewe\"]",129,true,true,true,"12345")
        try {
            db.productDao().upsertAll(listOf(ProductEntity("a","Coca-Cola",normalizedKey="source-a"),ProductEntity("b","Coca-Cola",normalizedKey="source-b")))
            db.shoppingListDao().upsertAll(items)
            db.favoriteDao().upsert(favorite)
            db.settingsDao().put(SettingEntity("ntfy_topic_url","https://private.invalid/topic"))
            db.settingsDao().put(SettingEntity("ntfy_token","SENSITIVE-FIXTURE"))
        } finally { db.close() }
        val output=ByteArrayOutputStream()
        BackupService(context,::database).export(output)
        val payload=output.toByteArray()
        assertFalse(payload.toString(Charsets.UTF_8).contains("SENSITIVE-FIXTURE"))
        assertFalse(payload.toString(Charsets.UTF_8).contains("private.invalid"))
        context.deleteDatabase(name)
        try {
            BackupService(context,::database).import(ByteArrayInputStream(payload))
            db=database()
            assertEquals(items.toSet(),db.shoppingListDao().allItems().toSet())
            assertEquals(setOf("a","b"),db.productDao().all().map { it.id }.toSet())
            assertEquals(favorite,db.favoriteDao().all().single())
            assertNull(db.settingsDao().get("ntfy_token"))
        } finally { db.close(); context.deleteDatabase(name) }
    }
}
