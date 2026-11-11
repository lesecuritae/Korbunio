package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test

class SourcePaginationTest {
    private fun tile(id: String, next: Boolean = false) = """
        <article><span class="product-badges__text">Sale</span><a href="/p/$id/" data-product-id="$id"></a><h3 class="product-tile__product-name">Fixture $id 250 ml</h3>
        <span data-testid="plp-currentPrice-label">1,15 €</span></article>
    """ + if (next) "<a href='?page=2'>2</a>" else ""

    @Test fun `Muller reads its next page and marks a failure partial while retaining the first`() = runTest {
        for (failure in listOf(false, true)) {
            MockWebServer().use { server ->
                server.start(); server.enqueue(MockResponse().setBody(tile("first", true)))
                server.enqueue(if (failure) MockResponse().setResponseCode(503) else MockResponse().setBody(tile("second")))
                val result = HtmlFlyerProvider("mueller", "Müller", server.url("/c/test/aktionen/").toString(), OkHttpClient()).fetch(RetailerRequest("04109"))
                assertEquals(if (failure) 1 else 2, result.offers.size)
                assertTrue(result.offers.all { it.priceCents == 115 })
                assertEquals(!failure, result.paginationComplete)
                assertEquals(failure, result.preserveMissingOffers)
                assertEquals(failure, result.sourceWarnings.isNotEmpty())
                server.takeRequest(); assertTrue(server.takeRequest().path!!.endsWith("?page=2"))
            }
        }
    }

    @Test fun `Muller regular assortment pages are enumerated but never imported as offers`() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(MockResponse().setBody(tile("regular-first", true).replace(">Sale<", ">Neu<")))
            server.enqueue(MockResponse().setBody(tile("regular-middle").replace(">Sale<", ">Müller Eigenmarke<") + "<a href='?page=3'>3</a>"))
            server.enqueue(MockResponse().setBody(tile("real-sale")))
            val result = HtmlFlyerProvider("mueller", "Müller", server.url("/c/test/aktionen/").toString(), OkHttpClient()).fetch(RetailerRequest("04109"))
            assertEquals(1, result.offers.size)
            assertEquals("real-sale", result.offers.single().externalId)
            assertTrue(result.paginationComplete)
            assertEquals(3, server.requestCount)
        }
    }

    @Test fun `actual mixed Muller listing excludes ordinary products including UVP comparisons`() = runTest {
        val payload = javaClass.classLoader!!.getResourceAsStream("offer_coverage/mueller_mixed_listing.html")!!.bufferedReader().use { it.readText() }
        MockWebServer().use { server ->
            server.start(); server.enqueue(MockResponse().setBody(payload))
            val result = HtmlFlyerProvider("mueller", "Müller", server.url("/offers").toString(), OkHttpClient()).fetch(RetailerRequest("04109"))
            assertEquals(setOf("fashy Wärmflasche 2l mit Fleecebezug", "fashy Wärmflasche 2l Halblamelle", "L'Oréal Men Expert Deo Roll-on Invincible Sport"), result.products.map { it.name }.toSet())
            assertEquals(setOf(899, 699, 235), result.offers.map { it.priceCents }.toSet())
        }
    }

    private fun dm(id: String) = """{"dan":"$id","title":"Fixture $id 250 ml","brandName":"Fixture brand","tileData":{"eyecatchers":[{"alt":"Ausverkauf"}],"price":{"price":{"current":{"value":"1,15"}}},"images":[]}}"""

    @Test fun `dm follows declared pagination instead of assuming a short first page is complete`() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(MockResponse().setBody("""{"products":[${dm("first")}],"totalPages":2,"currentPage":0}"""))
            server.enqueue(MockResponse().setBody("""{"products":[${dm("second")}],"totalPages":2,"currentPage":1}"""))
            val result = DmProvider(OkHttpClient(), server.url("/search").toString()).fetch(RetailerRequest("04109"))
            assertEquals(2, result.offers.size)
            assertTrue(result.offers.all { it.priceCents == 115 })
            assertTrue(result.paginationComplete)
            server.takeRequest(); assertEquals("1", server.takeRequest().requestUrl!!.queryParameter("currentPage"))
        }
    }

    @Test fun `dm refuses truncated declared totals even on a successful final HTTP page`() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(MockResponse().setBody("""{"products":[${dm("first")}],"totalPages":1,"currentPage":0,"count":2}"""))
            val result = runCatching { DmProvider(OkHttpClient(), server.url("/search").toString()).fetch(RetailerRequest("04109")) }
            assertTrue(result.isFailure)
            assertTrue(result.exceptionOrNull()!!.message!!.contains("Teilantwort"))
            assertEquals(1, server.requestCount)
        }
    }

    @Test fun `dm refuses an empty last page even without a declared total`() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(MockResponse().setBody("""{"products":[${dm("first")}],"totalPages":2,"currentPage":0}"""))
            server.enqueue(MockResponse().setBody("""{"products":[],"totalPages":2,"currentPage":1}"""))
            val result = runCatching { DmProvider(OkHttpClient(), server.url("/search").toString()).fetch(RetailerRequest("04109")) }
            assertTrue(result.isFailure)
            assertTrue(result.exceptionOrNull()!!.message!!.contains("Folgeseite"))
            assertEquals(2, server.requestCount)
        }
    }

    @Test fun `dm unknown schema and missing subsequent page are failures not complete empty catalogues`() = runTest {
        for (schema in listOf("{}", """{"products":{}}""", """{"products":[${dm("first")}],"totalPages":5}""")) {
            MockWebServer().use { server ->
                server.start(); server.enqueue(MockResponse().setBody(schema))
                assertTrue(runCatching { DmProvider(OkHttpClient(), server.url("/search").toString()).fetch(RetailerRequest("04109")) }.isFailure)
            }
        }
        MockWebServer().use { server ->
            server.start()
            server.enqueue(MockResponse().setBody("""{"products":[${dm("first")}],"totalPages":2}"""))
            server.enqueue(MockResponse().setResponseCode(503))
            assertTrue(runCatching { DmProvider(OkHttpClient(), server.url("/search").toString()).fetch(RetailerRequest("04109")) }.isFailure)
        }
    }
}
