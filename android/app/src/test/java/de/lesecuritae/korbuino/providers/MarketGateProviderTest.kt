package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MarketGateProviderTest {
    private class Counting(override val id: String = "holab") : RetailerProvider {
        override val displayName = "HOL'AB!"
        var calls = 0
        override suspend fun fetch(request: RetailerRequest): ProviderResult { calls++; return ProviderResult(emptyList(), emptyList()) }
    }

    @Test
    fun skipsTheRetailerWhenThereIsNoMarket() = runBlocking {
        val inner = Counting()
        val result = MarketGateProvider(inner) { false }.fetch(RetailerRequest("45127"))
        assertEquals(0, inner.calls)
        assertTrue(result.noLocalMarket)
    }

    @Test
    fun lookupFailureDoesNotBecomeConfirmedMarketAbsence() = runBlocking {
        val inner = Counting()
        val result = runCatching { MarketGateProvider(inner) { error("lookup failed") }.fetch(RetailerRequest("80331")) }
        assertTrue(result.isFailure)
        assertEquals(0, inner.calls)
    }

    @Test fun legacyGateWithoutConfirmedAbsencePreservesOfflineCache() = runBlocking {
        val result = MarketGateProvider(Counting(), confirmsAbsence = false) { false }.fetch(RetailerRequest("45127"))
        assertFalse(result.noLocalMarket)
    }

    @Test
    fun fetchesWhenThereIsAMarket() = runBlocking {
        val inner = Counting()
        MarketGateProvider(inner) { true }.fetch(RetailerRequest("45127"))
        assertEquals(1, inner.calls)
    }

    @Test
    fun holabMarketMustMatchThePostalCode() = runBlocking {
        MockWebServer().use { server ->
            val html = """<ul><li class="store"><a href="/maerkte/essen">HOL'AB! Essen, Musterweg 1, 45127 Essen</a></li>
                <li class="store"><a href="/maerkte/koeln">HOL'AB! Köln, 50667 Köln</a></li></ul>"""
            repeat(2) { server.enqueue(MockResponse().setBody(html)) }
            val markets = HolabMarkets(OkHttpClient(), server.url("/").toString().trimEnd('/'))
            assertTrue(markets.hasMarket("45127"))
            assertFalse(markets.hasMarket("10115"))
            assertEquals("/maerkte?q=45127", server.takeRequest().path)
        }
    }
}
