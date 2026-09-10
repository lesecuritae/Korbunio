package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

class FallbackRetailerProviderTest {
    @Test fun `maps regional fallback to official retailer identity`() = runTest {
        val primary = fake("kaufland", "Kaufland", error = IllegalStateException("HTTP 403"))
        val fallback = fake("marktguru-kaufland", "Kaufland regional")

        val result = FallbackRetailerProvider(primary, fallback).fetch(RetailerRequest("26122"))

        assertEquals("kaufland", result.offers.single().retailerId)
        assertEquals("kaufland:offer-1", result.offers.single().id)
        assertEquals("https://cdn.example/product.webp", result.offers.single().imageUrl)
    }

    @Test fun `retains successful official result`() = runTest {
        val primary = fake("rossmann", "Rossmann")
        val fallback = fake("marktguru-rossmann", "Rossmann regional")

        val result = FallbackRetailerProvider(primary, fallback).fetch(RetailerRequest("26122"))

        assertEquals("rossmann", result.offers.single().retailerId)
        assertEquals("rossmann:offer-1", result.offers.single().id)
    }

    private fun fake(id: String, name: String, error: Throwable? = null) = object : RetailerProvider {
        override val id = id
        override val displayName = name
        override suspend fun fetch(request: RetailerRequest): ProviderResult {
            error?.let { throw it }
            return ProviderResult(
                listOf(ProductEntity("product-1", "Produkt", normalizedKey = "produkt")),
                listOf(
                    OfferEntity(
                        "$id:offer-1", id, "product-1", externalId = "offer-1",
                        priceCents = 99, sourceUrl = "https://example.test",
                        imageUrl = "https://cdn.example/product.webp", cachedAt = 1,
                    ),
                ),
            )
        }
    }
}
