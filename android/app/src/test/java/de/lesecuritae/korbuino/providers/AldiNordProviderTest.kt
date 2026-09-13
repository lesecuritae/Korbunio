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
import java.time.LocalDate

class AldiNordProviderTest {
    private lateinit var server: MockWebServer

    @Before fun setUp() { server = MockWebServer().also { it.start() } }
    @After fun tearDown() { server.shutdown() }

    @Test fun `reads current official offers with prices dates and images`() = runTest {
        val payload = """
            {
              "props":{"pageProps":{"apiData":[["OFFER_GET",{"res":{
                "categories":[
                  {"title":"Aktuell","startDate":"2026-09-07","endDate":"2026-09-12","content":[
                    {"title":"Obst & Gemüse","productIds":["current"]}
                  ]},
                  {"title":"Nächste Woche","startDate":"2026-09-14","endDate":"2026-09-19","content":[
                    {"title":"Vorschau","productIds":["future"]}
                  ]}
                ],
                "algoliaDataMap":{
                  "current":{
                    "brandName":"ALDI",
                    "name":"Kiwi",
                    "promotionPrices":[{"priceValue":0.49,"validFromLocalDate":"2026-09-07","validUntilLocalDate":"2026-09-12","basePrice":[{"basePriceValue":0.49,"basePriceScale":"Stück"}]}],
                    "assets":[{"type":"primary","url":"https://cdn.example/kiwi.webp"}]
                  },
                  "future":{"name":"Vorschauartikel","currentPrice":{"priceValue":9.99}}
                }
              }}]]}}}
        """.trimIndent()
        server.enqueue(MockResponse().setBody("<html><script id=\"__NEXT_DATA__\" type=\"application/json\">$payload</script></html>"))

        val result = AldiNordProvider(
            OkHttpClient(),
            server.url("/angebote.html").toString(),
            today = { LocalDate.parse("2026-09-10") },
        ).fetch(RetailerRequest("26122"))

        assertEquals(listOf("ALDI Kiwi"), result.products.map { it.name })
        with(result.offers.single()) {
            assertEquals(49, priceCents)
            assertEquals(49, basePriceCents)
            assertEquals("Stück", baseUnit)
            assertEquals("Obst & Gemüse", categoryId)
            assertEquals("2026-09-07", validFrom)
            assertEquals("2026-09-12", validUntil)
            assertEquals("https://cdn.example/kiwi.webp", imageUrl)
        }
    }

    @Test fun `fails safely when official structured data is missing`() = runTest {
        server.enqueue(MockResponse().setBody("<html>temporarily incomplete</html>"))
        val result = runCatching {
            AldiNordProvider(OkHttpClient(), server.url("/angebote.html").toString())
                .fetch(RetailerRequest("26122"))
        }
        assertTrue(result.exceptionOrNull()?.message.orEmpty().contains("Angebotsdaten fehlen"))
    }
}
