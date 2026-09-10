package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

class GlobusProviderTest {
    private lateinit var server: MockWebServer

    @Before fun setUp() { server = MockWebServer().also { it.start() } }
    @After fun tearDown() { server.shutdown() }

    @Test fun `parses exact postal market and article`() = runTest {
        server.enqueue(MockResponse().setBody("""
            {"data":{"1":{"betriebsstaette":"SBW","marktNummer":"10","marktNameKurz":"Test-Markt","marktName":"Teststadt","plz":"12345"}}}
        """))
        server.enqueue(MockResponse().setBody("""
            {"pages":[{"page":"1","image":"https://example.invalid/page.jpg","articles":[
              {"article_id":"a1","title":"Coca-Cola Zero 1,25 l","price":"1,29 €","product_image":"https://example.invalid/coke.jpg"},
              {"article_id":"a2","title":"Roggenmischbrot","price":"1,11 €"}
            ]}]}
        """))
        server.enqueue(MockResponse().setBody("""
            <script id="__NEXT_DATA__" type="application/json">
            {"props":{"pageProps":{"pageInformation":{"offers":{"main":{"items":[
              {"type":"OFFER","publisherName":"GLOBUS","title":"Roggenmischbrot","prices":{"mainPrice":1.11},"offerImages":{"url":{"normal":"https://content-media.bonial.biz/image/main.jpg?impolicy=SEO-offer-normal"}}}
            ]}}}}}}
            </script>
        """))
        val base = server.url("/").toString().trimEnd('/')
        val result = GlobusProvider(OkHttpClient(), base, base).fetch(RetailerRequest("12345"))
        assertEquals(2, result.offers.size)
        assertEquals(129, result.offers[0].priceCents)
        assertEquals("a1", result.offers[0].externalId)
        assertEquals("https://example.invalid/coke.jpg", result.offers[0].imageUrl)
        assertEquals(111, result.offers[1].priceCents)
        assertEquals(
            "https://content-media.bonial.biz/image/main.jpg?impolicy=SEO-offer-normal",
            result.offers[1].imageUrl,
        )
    }
}
