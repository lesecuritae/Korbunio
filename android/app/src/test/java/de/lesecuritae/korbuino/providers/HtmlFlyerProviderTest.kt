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

    @Test fun `uses the highest priority direct image from srcset`() = runTest {
        server.enqueue(MockResponse().setBody("""
            <article class="product-tile"><img src="/placeholder.svg" data-srcset="/small.jpg 320w, /large.jpg 1200w">
              <h3>Produkt</h3><span class="price">1,79 €</span>
            </article>
        """))
        val provider = HtmlFlyerProvider("test", "Test", server.url("/angebote").toString(), OkHttpClient())
        assertEquals(server.url("/large.jpg").toString(), provider.fetch(RetailerRequest("12345")).offers.single().imageUrl)
    }

    @Test fun `uses a user rendered Müller document without a second network request`() = runTest {
        val rendered = """
            <html><body><article data-product-id="mueller-1">
              <h3 class="product-tile__product-name">Müller Shampoo 300 ml</h3>
              <span data-testid="plp-currentPrice-label">2,49 €</span>
              <img src="https://cdn.example.test/mueller.jpg">
            </article></body></html>
        """.trimIndent()
        val provider = HtmlFlyerProvider(
            "mueller", "Müller", "https://www.mueller.de/c/online-angebote/", OkHttpClient(),
            renderedHtmlProvider = { rendered },
        )

        val result = provider.fetch(RetailerRequest("12345"))

        assertEquals(1, result.offers.size)
        assertEquals(249, result.offers.single().priceCents)
        assertEquals(0, server.requestCount)
    }

    @Test fun `reports empty rendered Müller documents instead of a successful empty sync`() = runTest {
        val provider = HtmlFlyerProvider(
            "mueller", "Müller", "https://www.mueller.de/c/online-angebote/", OkHttpClient(),
            renderedHtmlProvider = { "<html><body>Nur Navigation</body></html>" },
        )

        try {
            provider.fetch(RetailerRequest("12345"))
            error("expected empty Müller document to fail")
        } catch (error: IllegalStateException) {
            assertTrue(error.message.orEmpty().contains("dynamischen Angebote"))
        }
    }
}
