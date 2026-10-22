package de.lesecuritae.korbuino.data

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test

class OfferRefreshTest {
    @Test fun confirmedMarketAbsenceRemovesOnlyThatRetailersCacheIncludingPreviews() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(ApplicationProvider.getApplicationContext(), KorbuinoDatabase::class.java).build()
        try {
            val old = OfferEntity("old", "aldi-nord", "p", externalId = "old", priceCents = 129,
                sourceUrl = "https://www.aldi-nord.de/", cachedAt = 1)
            val future = old.copy(id = "future", externalId = "future", validFrom = "2099-01-01")
            val other = old.copy(id = "south", retailerId = "aldi-sued")
            val product = ProductEntity("p", "Butter", normalizedKey = "butter")
            db.productDao().upsertAll(listOf(product))
            db.offerDao().upsertAll(listOf(old, future, other))
            val item = ShoppingListItemEntity("list", "p", offerId = old.id)
            val favorite = FavoriteEntity("p", createdAt = 1)
            db.shoppingListDao().upsertAll(listOf(item))
            db.favoriteDao().upsert(favorite)
            // An ordinary empty response remains harmless to offline data.
            db.offerDao().storeRefresh(emptyList())
            assertEquals(3, db.offerDao().all().size)
            repeat(2) { db.offerDao().storeRefresh(emptyList(), listOf("aldi-nord")) }
            assertEquals(listOf(other), db.offerDao().all())
            assertEquals(listOf(product), db.productDao().all())
            assertEquals(listOf(item), db.shoppingListDao().allItems())
            assertEquals(listOf(favorite), db.favoriteDao().all())
        } finally { db.close() }
    }

    @Test fun successfulProviderRefreshReplacesOnlyThatProvidersOffers() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(), KorbuinoDatabase::class.java,
        ).build()
        try {
            val old = OfferEntity("old", "netto-marken", "phone", externalId = "old", priceCents = 276,
                sourceUrl = "https://www.netto-online.de/angebote/", cachedAt = 1)
            val other = old.copy(id = "rewe", retailerId = "rewe")
            db.offerDao().upsertAll(listOf(old, other))
            db.offerDao().storeRefresh(emptyList())
            assertEquals(2, db.offerDao().all().size)
            val fresh = old.copy(id = "new", externalId = "new", priceCents = 83900, cachedAt = 2)
            repeat(2) { db.offerDao().storeRefresh(listOf(fresh)) }
            assertEquals(setOf(other, fresh), db.offerDao().all().toSet())
        } finally { db.close() }
    }

    @Test fun currentAndFuturePartitionsSurviveEachOthersRefresh() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(ApplicationProvider.getApplicationContext(), KorbuinoDatabase::class.java).build()
        try {
            val monday = java.time.LocalDate.now(java.time.ZoneId.of("Europe/Berlin"))
                .with(java.time.temporal.TemporalAdjusters.previousOrSame(java.time.DayOfWeek.MONDAY))
            val current = OfferEntity("today","kaufland","p",externalId="today",priceCents=300,
                validFrom=monday.toString(),validUntil=monday.plusDays(6).toString(),sourceUrl="https://example.org",cachedAt=1)
            val future = current.copy(id="future",externalId="future",validFrom=monday.plusWeeks(1).toString(),validUntil=monday.plusDays(13).toString())
            db.offerDao().storeRefresh(listOf(current))
            db.offerDao().storeWeekRefresh("kaufland",future.validFrom!!,future.validUntil!!,listOf(future))
            assertEquals(setOf("today","future"),db.offerDao().all().map { it.id }.toSet())
            db.offerDao().storeRefresh(listOf(current.copy(priceCents=200)))
            assertEquals(setOf("today","future"),db.offerDao().all().map { it.id }.toSet())
            db.offerDao().storeWeekRefresh("kaufland",future.validFrom!!,future.validUntil!!,emptyList())
            assertEquals("today",db.offerDao().all().single().id)
        } finally { db.close() }
    }

    @Test fun productAndImageQueriesSupportLargeMultiRetailerImports() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(), KorbuinoDatabase::class.java,
        ).build()
        try {
            val products = (0 until 1_100).map {
                ProductEntity("product-$it", "Product $it", normalizedKey = "product-$it")
            }
            db.productDao().upsertAll(products)
            products.forEach {
                db.imageDao().upsert(
                    ProductImageEntity(
                        productId = it.id,
                        imageUrl = "https://example.invalid/${it.id}.jpg",
                        source = "test",
                        matchMethod = "exact",
                        confidence = 1.0,
                        verifiedAt = 1,
                        cachedAt = 1,
                    ),
                )
            }

            assertEquals(1_100, db.productDao().find(products.map { it.id }).size)
            assertEquals(1_100, db.imageDao().find(products.map { it.id }).size)
        } finally { db.close() }
    }
}
