package de.lesecuritae.korbuino.notifications

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import de.lesecuritae.korbuino.data.*
import de.lesecuritae.korbuino.providers.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.time.*
import java.time.temporal.TemporalAdjusters

class NativePreviewIntegrationTest {
    @Test fun genuinePreviewPreservesCurrentProductReferenceAndEmptyPreviewRemovesOnlyFuture() = runBlocking {
        val db=Room.inMemoryDatabaseBuilder(ApplicationProvider.getApplicationContext(),KorbuinoDatabase::class.java).build()
        val monday=LocalDate.now(ZoneId.of("Europe/Berlin")).with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
        val current=OfferEntity("current","rewe","saved-product",externalId="current",priceCents=129,
            validFrom=monday.toString(),validUntil=monday.plusDays(6).toString(),sourceUrl="https://example.org",cachedAt=1)
        var response=ProviderResult(listOf(ProductEntity("incoming-product","Coca-Cola",normalizedKey="coca-cola")),listOf(
            current.copy(id="preview",externalId="preview",productId="incoming-product",validFrom=monday.plusWeeks(1).toString(),validUntil=monday.plusDays(13).toString())))
        val requests=mutableListOf<RetailerRequest>()
        val provider=object:RetailerProvider {
            override val id="rewe"
            override val displayName="REWE"
            override suspend fun fetch(request:RetailerRequest):ProviderResult { requests+=request;return response }
        }
        try {
            db.productDao().upsertAll(listOf(ProductEntity("saved-product","Coca-Cola",normalizedKey="coca-cola")))
            db.offerDao().storeRefresh(listOf(current))
            db.favoriteDao().upsert(FavoriteEntity("watch",1,"Coca Cola",includeNextWeek=true,postalCode="12345"))
            NativeWatchSync.refreshUpcoming(db,listOf(provider),"12345",null)
            assertEquals(OfferWeek.NEXT,requests.single().week)
            assertEquals("12345",requests.single().postalCode)
            assertEquals(2,db.offerDao().all().size)
            // The current row keeps its product. An equal display name alone is
            // no product identity, so the preview keeps its own source product.
            assertEquals("saved-product",db.offerDao().all().single { it.validFrom==monday.toString() }.productId)
            assertEquals("incoming-product",db.offerDao().all().single { it.validFrom!=monday.toString() }.productId)
            assertEquals(setOf("saved-product","incoming-product"),db.productDao().all().map { it.id }.toSet())
            response=ProviderResult(emptyList(),emptyList())
            NativeWatchSync.refreshUpcoming(db,listOf(provider),"12345",null)
            assertEquals(listOf(current),db.offerDao().all())
            // Ignoring NEXT at an upstream provider cannot make its current rows a preview.
            response=ProviderResult(emptyList(),listOf(current))
            NativeWatchSync.refreshUpcoming(db,listOf(provider),"12345",null)
            assertEquals(listOf(current),db.offerDao().all())
        } finally { db.close() }
    }
}
