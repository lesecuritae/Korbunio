package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class ReweProviderTest {
    private lateinit var server: MockWebServer

    @Before fun setUp() { server = MockWebServer().also { it.start() } }
    @After fun tearDown() { server.shutdown() }

    @Test fun `parses public market offer cards`() = runTest {
        server.enqueue(MockResponse().setBody("""
            <a href="/angebote/teststadt/123456/rewe-markt-hauptstrasse/">REWE Markt 12345 Teststadt</a>
        """))
        server.enqueue(MockResponse().setBody("""
            <div class="cor-offer-renderer-tile">
              <div class="cor-offer-information__title">Coca-Cola Zero 1,25 l</div>
              <span class="cor-offer-price__tag-price">1,29 €</span>
              <img src="https://img.rewe-static.de/example.jpg" />
            </div>
        """))
        val provider = ReweProvider(OkHttpClient(), server.url("/").toString().trimEnd('/'))
        val result = provider.fetch(RetailerRequest("12345", citySlug = "teststadt"))
        assertEquals(1, result.offers.size)
        assertEquals(129, result.offers.single().priceCents)
        assertTrue(result.products.single().name.contains("Coca-Cola"))
    }

    @Test fun `rejects invalid postal code before network`() = runTest {
        val provider = ReweProvider(OkHttpClient(), server.url("/").toString().trimEnd('/'))
        try {
            provider.fetch(RetailerRequest("1234", citySlug = "teststadt"))
            error("expected validation error")
        } catch (error: IllegalArgumentException) {
            assertTrue(error.message.orEmpty().contains("PLZ"))
        }
        assertEquals(0, server.requestCount)
    }
}
