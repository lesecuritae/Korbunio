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
import java.time.Instant

class KaufdaRetailerProviderTest {
    private lateinit var server: MockWebServer

    @Before fun setUp() { server = MockWebServer().also { it.start() } }
    @After fun tearDown() { server.shutdown() }

    @Test fun `loads only current offers for the requested publisher with images`() = runTest {
        server.enqueue(MockResponse().setBody("""
            <script id="__NEXT_DATA__" type="application/json">{
              "props":{"pageProps":{"pageInformation":{"offers":{"main":{"items":[
                {"type":"OFFER","id":"active","publisherName":"Müller","title":"Power Serum","brand":"CELLULAR",
                 "validFrom":"2026-09-06T22:00:00.000+0000","validUntil":"2026-09-12T20:00:00.000+0000",
                 "prices":{"mainPrice":15.99},"offerImages":{"url":{"normal":"https://content-media.bonial.biz/id/main.jpg?impolicy=SEO-offer-normal"}}},
                {"type":"OFFER","id":"expired","publisherName":"Müller","title":"Alt","validFrom":"2026-08-01T00:00:00Z",
                 "validUntil":"2026-08-02T00:00:00Z","prices":{"mainPrice":1.0}},
                {"type":"OFFER","id":"foreign","publisherName":"Rossmann","title":"Fremd","validFrom":"2026-09-01T00:00:00Z",
                 "validUntil":"2026-09-30T00:00:00Z","prices":{"mainPrice":2.0}}
              ]}}}}}}
            </script>
        """))
        val result = KaufdaRetailerProvider(
            "mueller", "Müller", "Müller", "Mueller", OkHttpClient(), server.url("").toString().trimEnd('/'),
            now = { Instant.parse("2026-09-12T10:00:00Z") },
        ).fetch(RetailerRequest("26122"))

        assertEquals(1, result.offers.size)
        assertEquals(1599, result.offers.single().priceCents)
        assertTrue(result.offers.single().imageUrl.orEmpty().contains("SEO-offer"))
        assertEquals("CELLULAR Power Serum", result.products.single().name)
    }
}
