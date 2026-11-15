package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class StockEnrichingProviderTest {
    private fun fixture(count: Int = 7): ProviderResult {
        val product = ProductEntity("p", "Fixture product", normalizedKey = "fixture")
        val offers = (0 until count).map { i -> OfferEntity("o$i", "dm", "p", externalId = "fixture$i",
            priceCents = 100 + i, sourceUrl = "https://www.dm.de/", cachedAt = 0) }
        return ProviderResult(listOf(product), offers, stockReferences = offers.associate { it.id to StockReference("dm", (1000000 + it.priceCents).toString()) })
    }
    private fun provider(value: ProviderResult) = object : RetailerProvider {
        override val id = "dm"; override val displayName = "dm"
        override suspend fun fetch(request: RetailerRequest) = value
    }

    @Test fun `automatic enrichment is bounded source identified and preserves offers`() = runTest {
        val original = fixture(); val calls = mutableListOf<List<String>>()
        val enriched = StockEnrichingProvider(provider(original), dm = { postal, dans ->
            assertEquals("12345", postal); calls += dans
            dans.map { StockProduct(it, listOf(StockStore("D1", "Teststadt", "Straße 1", postal, "VERFUEGBAR", 4, true, "VERFUEGBAR")), "2026-11-15T10:00:00Z") }
        }).fetch(RetailerRequest("12345"))
        assertEquals(original.offers, enriched.offers); assertEquals(original.products, enriched.products)
        assertEquals(1, calls.size); assertEquals(5, calls.single().size)
        assertTrue(enriched.stockSummaries.getValue("o0").contains("4 Stück"))
        assertTrue(enriched.stockSummaries.getValue("o6").contains("Abfragelimit"))
        val unresolved = StockEnrichingProvider(provider(original.copy(stockReferences = emptyMap())), dm = { _, _ -> error("must not guess") }).fetch(RetailerRequest("12345"))
        assertTrue(unresolved.stockSummaries.values.all { it.contains("nicht belegt") })
    }

    @Test fun `stock failure and own deadline cannot discard offers but cancellation propagates`() = runTest {
        val original = fixture(1)
        val failed = StockEnrichingProvider(provider(original), dm = { _, _ -> error("HTTP 503") }).fetch(RetailerRequest("12345"))
        assertEquals(original.offers, failed.offers); assertTrue(failed.stockSummaries.getValue("o0").contains("unbekannt"))
        val timeout = StockEnrichingProvider(provider(original), dm = { _, _ -> delay(21_000); emptyList() }).fetch(RetailerRequest("12345"))
        assertEquals(original.offers, timeout.offers); assertTrue(timeout.stockSummaries.getValue("o0").contains("Zeitlimit"))
        assertTrue(runCatching { StockEnrichingProvider(provider(original), dm = { _, _ -> throw CancellationException("user left") }).fetch(RetailerRequest("12345")) }.exceptionOrNull() is CancellationException)
    }
}
