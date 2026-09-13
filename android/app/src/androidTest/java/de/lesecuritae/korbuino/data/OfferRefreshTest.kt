package de.lesecuritae.korbuino.data

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test

class OfferRefreshTest {
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
