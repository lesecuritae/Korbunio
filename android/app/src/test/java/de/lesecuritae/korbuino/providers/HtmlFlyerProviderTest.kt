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

class HtmlFlyerProviderTest {
    private lateinit var server: MockWebServer

    @Before fun setUp() { server = MockWebServer().also { it.start() } }
    @After fun tearDown() { server.shutdown() }

    @Test fun `parses a public flyer card and keeps source`() = runTest {
        server.enqueue(MockResponse().setBody("""
            <article data-product-id="p1">
              <h3>Cola Zero 1,25 l</h3><span class="price">1,29 €</span>
              <img src="https://cdn.example.test/cola.jpg">
            </article>
        """))
        val provider = HtmlFlyerProvider("test", "Test", server.url("/offers").toString(), OkHttpClient())
        val result = provider.fetch(RetailerRequest("12345"))
        assertEquals(1, result.offers.size)
        assertEquals(129, result.offers.single().priceCents)
        assertEquals("https://cdn.example.test/cola.jpg", result.offers.single().imageUrl)
        assertTrue(result.offers.single().sourceUrl.endsWith("/offers"))
    }

    @Test fun `rejects invalid postal code without network`() = runTest {
        val provider = HtmlFlyerProvider("test", "Test", server.url("/").toString(), OkHttpClient())
        try {
            provider.fetch(RetailerRequest("12"))
            error("expected validation error")
        } catch (error: IllegalArgumentException) {
            assertTrue(error.message.orEmpty().contains("PLZ"))
        }
        assertEquals(0, server.requestCount)
    }

    @Test fun `parses ALDI product tile dot prices and lazy images`() = runTest {
        server.enqueue(MockResponse().setBody("""
            <article class="product-tile" data-product-id="aldi-1">
              <img data-src="/images/apple.jpg" src="/placeholder.svg">
              <div data-test="product-tile__name"><p>Äpfel 1 kg</p></div>
              <div data-test="product-tile__price"><span>1.79 €</span></div>
            </article>
        """))
        val provider = HtmlFlyerProvider("aldi-sued", "ALDI Süd", server.url("/angebote").toString(), OkHttpClient())

        val result = provider.fetch(RetailerRequest("12345"))

        assertEquals(1, result.offers.size)
        assertEquals(179, result.offers.single().priceCents)
        assertEquals(server.url("/images/apple.jpg").toString(), result.offers.single().imageUrl)
    }
}
