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

    @Test fun `Netto selects sale price not rating UVP unit price or pack size`() = runTest {
        for ((raw, cents) in listOf("0,99" to 99, "1,49" to 149, "12,99" to 1299, "839.–" to 83900, "4.689.–" to 468900, "89.<sup>99</sup>" to 8999)) {
            server.enqueue(MockResponse().setBody("""
                <article><h4>Apple iPhone 17 Salbei 256 GB 6er Pack</h4>
                  <div class="rating">Kundenbewertung: 2,76 von 5 Sternen</div>
                  <s>949,00 €</s><div class="base-price">0,12 €/kg</div>
                  <div class="product__current-price"><strong>$raw<span class="product__current-price--asterisk">*</span></strong></div>
                  <img data-src="https://media.netto-online.de/item?im=Resize=(310,310),type=downsize;" />
                </article>
            """))
            val result = HtmlFlyerProvider("netto-marken", "Netto", server.url("/").toString(), OkHttpClient()).fetch(RetailerRequest("12345"))
            assertEquals(cents, result.offers.single().priceCents)
            assertEquals("https://media.netto-online.de/item?im=Resize=(310,310),type=downsize;", result.offers.single().imageUrl)
        }
    }

    @Test fun `Netto nested cards use stable article numbers without duplicate offers`() = runTest {
        server.enqueue(MockResponse().setBody("""
            <li class="product"><article><a data-sku="12345"><h4>Kofferset 3 teilig</h4>
              <div class="product__current-price"><strong>89.<sup>99</sup></strong></div>
            </a></article></li>
        """))
        val result = HtmlFlyerProvider("netto-marken", "Netto", server.url("/").toString(), OkHttpClient())
            .fetch(RetailerRequest("12345"))
        assertEquals(1, result.offers.size)
        assertEquals("12345", result.offers.single().externalId)
        assertEquals(8999, result.offers.single().priceCents)
    }

    @Test fun `Netto without sale price rejects rating and UVP`() = runTest {
        server.enqueue(MockResponse().setBody("<article><h4>iPhone</h4><div>Bewertung 2,76 UVP 949,00</div></article>"))
        assertTrue(HtmlFlyerProvider("netto-marken", "Netto", server.url("/").toString(), OkHttpClient()).fetch(RetailerRequest("12345")).offers.isEmpty())
    }

    @Test fun `Netto Scottie reads its accessible weekly offer cards`() = runTest {
        server.enqueue(MockResponse().setBody("""
            <section aria-label="product-4711">
              <h4><span>BioBio</span><span>Haferdrink</span></h4>
              <p>1 Liter</p>
              <h3><span>1</span><span>29</span></h3>
              <img src="/images/haferdrink.webp">
            </section>
        """))
        val result = HtmlFlyerProvider(
            "netto-schwarz", "Netto mit Hund", server.url("/angebote/").toString(), OkHttpClient(),
        ).fetch(RetailerRequest("26122"))

        assertEquals(1, result.offers.size)
        assertEquals(129, result.offers.single().priceCents)
        assertEquals(server.url("/images/haferdrink.webp").toString(), result.offers.single().imageUrl)
    }

    @Test fun `Rossmann uses the current article price instead of the earlier base price`() = runTest {
        server.enqueue(MockResponse().setBody("""
            <article data-testid="product-card" data-item-id="031160" data-item-ean="8011530001865"
                     data-item-brand="Laura Biagiotti" data-item-name="Roma Rosa, EdT 25 ml">
              <img src="https://www.rossmann.de/media-neu/roma.png">
              <div data-testid="product-baseprice">25 ml (1L = 919.6)</div>
              <div data-testid="product-price">
                <div class="inline-flex">22<span>.</span><span>99</span></div>
                <span class="sr-only">Aktueller Artikelpreis: 22,99 €</span>
              </div>
            </article>
        """))
        val result = HtmlFlyerProvider(
            "rossmann", "Rossmann", server.url("/angebote/").toString(), OkHttpClient(),
        ).fetch(RetailerRequest("26122"))

        assertEquals(1, result.offers.size)
        assertEquals(2299, result.offers.single().priceCents)
        assertEquals("031160", result.offers.single().externalId)
        assertEquals("Roma Rosa, EdT 25 ml", result.products.single().name)
        assertEquals("Laura Biagiotti", result.products.single().brand)
        assertEquals("8011530001865", result.products.single().gtin)
    }

    @Test fun `retains transformed image URLs and resolves relative URLs across HTML retailers`() = runTest {
        val transformed = "https://cdn.example.test/product?im=Resize=(310,310),type=downsize;"
        for (retailer in listOf("aldi-nord", "aldi-sued", "rossmann", "mueller", "kaufland", "netto-schwarz", "holab")) {
            for ((attribute, expected) in listOf(
                "src=\"$transformed\"" to transformed,
                "data-src=\"/real.webp\" src=\"/placeholder.png\"" to server.url("/real.webp").toString(),
                "srcset=\"/small.png 320w, $transformed 1200w\"" to transformed,
                "src=\"javascript:alert(1)\"" to null,
                "src=\"\"" to null,
            )) {
                server.enqueue(MockResponse().setBody("<article><h3>Shampoo</h3><span class='price'>1,49 €</span><img $attribute></article>"))
                val result = HtmlFlyerProvider(retailer, retailer, server.url("/offers").toString(), OkHttpClient())
                    .fetch(RetailerRequest("12345"))
                assertEquals("$retailer: $attribute", expected, result.offers.single().imageUrl)
            }
        }
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
