package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertNull
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

    private suspend fun published(payload: String): ProviderResult {
        server.enqueue(MockResponse().setBody("""{"data":{"1":{"betriebsstaette":"SBW","marktNummer":"10","marktNameKurz":"kmd","plz":"12345"}}}"""))
        server.enqueue(MockResponse().setBody(payload))
        server.enqueue(MockResponse().setBody("<html></html>"))
        val base = server.url("/").toString().trimEnd('/')
        return GlobusProvider(OkHttpClient(), base, base).fetch(RetailerRequest("12345"))
    }

    private fun fixture() = javaClass.classLoader!!.getResourceAsStream("offer_coverage/globus_published_prices.json")!!
        .bufferedReader().use { it.readText() }

    @Test fun `published member prices and quantity ranges remain distinct`() = runTest {
        val result = published(fixture())
        val cheese = result.offers.single { it.externalId == "77900000013772" }
        assertEquals(229, cheese.priceCents)
        assertEquals(199, cheese.loyaltyPriceCents)
        assertEquals("mein_globus", cheese.loyaltyProgram)
        assertEquals("100–200 g", cheese.packSize)
        assertNull(cheese.basePriceCents)
        val pizza = result.offers.single { it.externalId == "77632000000030" }
        assertEquals(179, pizza.priceCents)
        assertEquals(169, pizza.loyaltyPriceCents)
        assertEquals("1 Stück", result.offers.single { it.externalId == "77000099004246" }.packSize)
        assertTrue(result.offers.all { it.validFrom == "2026-11-09" && it.validUntil == "2026-11-14" })
    }

    @Test fun `published diameter variants retain exact individual prices and identities`() = runTest {
        val result = published(fixture())
        val pans = result.offers.filter { it.externalId.startsWith("77900000022161:") }
        assertEquals(listOf(999, 1199, 1399), pans.map { it.priceCents })
        assertEquals(3, pans.map { it.productId }.distinct().size)
        assertTrue(pans.all { it.loyaltyPriceCents == null })
        assertEquals(listOf("20 cm", "24 cm", "28 cm"), pans.map { offer ->
            result.products.single { it.id == offer.productId }.name.substringAfter("Ø ")
        })
    }

    @Test fun `unknown starting-price groups are refused visibly without retaining stale fixed prices`() = runTest {
        val result = published("""{"pages":[{"articles":[{"article_id":"unknown","title":"Varianten","menge":"ab","price":"9.99","mgprice":"8.99","subtitle":"verschiedene Größen"}]}]}""")
        assertTrue(result.offers.isEmpty())
        assertTrue(result.sourceWarnings.single().contains("ab-Preisgruppen"))
        assertTrue(!result.preserveMissingOffers)
    }

    @Test fun `a partly ambiguous diameter price list is never silently truncated`() = runTest {
        val result = published("""{"pages":[{"articles":[{"article_id":"mixed","title":"Pfanne","menge":"ab","price":"9.99","subtitle":"Ø 20 cm: 9.99, Ø 24 cm: 11.99, Ø 28 cm: 13.99–15.99"}]}]}""")
        assertTrue(result.offers.isEmpty())
        assertTrue(result.sourceWarnings.isNotEmpty())
    }
}
