package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.time.LocalDate

class EdekaProviderTest {
    private lateinit var server: MockWebServer
    private val friday = LocalDate.of(2026, 9, 18)

    @Before fun setUp() { server = MockWebServer().also { it.start() } }
    @After fun tearDown() { server.shutdown() }

    private fun market(id: String, zip: String) =
        """{"id":"$id","name":"EDEKA $id","url":"/eh/markt/$id","contact":{"address":{"city":{"zipCode":"$zip"}}}}"""

    private fun provider(handoff: (String) -> String? = { null }) = EdekaProvider(
        http = OkHttpClient(),
        marketApi = server.url("/api/marketsearch/markets").toString(),
        offersApi = server.url("/eh/service/eh/offers").toString(),
        today = { friday },
        handoff = handoff,
        now = { 1_000L },
    )

    /** Serves the market search and per-market offers from a fixed table. */
    private fun serve(markets: List<String>, offers: Map<String, String>, marketStatus: Int = 200) {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val url = request.requestUrl!!
                return when {
                    url.encodedPath.endsWith("/markets") ->
                        MockResponse().setResponseCode(marketStatus).setBody("""{"markets":[${markets.joinToString(",")}]}""")
                    else -> offers[url.queryParameter("marketId")]
                        ?.let { MockResponse().setBody(it) } ?: MockResponse().setResponseCode(404)
                }
            }
        }
    }

    private val pricedOffers = """
        {"docs":[
          {"angebotid":"a1","titel":"Butter 250 g","preis":"1,79","basicPrice":"1 kg = 7,16","warengruppe":"Molkerei",
           "gueltig_von":"2026-09-14","gueltig_bis":"2026-09-19","bild_app":"//img.edeka.de/butter.jpg"},
          {"angebotid":"a2","titel":"Milch 1 l","preis":"0,99","gueltig_von":"2026-09-14","gueltig_bis":"2026-09-19"},
          {"angebotid":"a3","titel":"Ohne Preis","preis":"0"},
          {"angebotid":"a4","titel":"Abgelaufen","preis":"2,00","gueltig_von":"2026-09-01","gueltig_bis":"2026-09-05"},
          {"angebotid":"a5","titel":"Naechste Woche","preis":"3,00","gueltig_von":"2026-09-21","gueltig_bis":"2026-09-26"}
        ]}
    """.trimIndent()

    @Test fun `finds the exact market beyond the services default ten results`() = runTest {
        val nearby = (1..10).map { market("near$it", "99999") }
        val all = nearby + market("exact", "12345")
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val url = request.requestUrl!!
                if (url.encodedPath.endsWith("/markets")) {
                    val size = url.queryParameter("size")?.toIntOrNull() ?: 10
                    return MockResponse().setBody("""{"markets":[${all.take(size).joinToString(",")}]}""")
                }
                return MockResponse().setBody(if (url.queryParameter("marketId") == "exact") pricedOffers else """{"docs":[]}""")
            }
        }
        val result = provider().fetch(RetailerRequest("12345"))
        assertEquals("exact", result.storeId)
        assertEquals(2, result.offers.size)
    }

    @Test fun `parses priced current offers and skips the rest`() = runTest {
        serve(listOf(market("m1", "26188")), mapOf("m1" to pricedOffers))
        val result = provider().fetch(RetailerRequest("26188"))

        assertEquals(listOf("Butter 250 g", "Milch 1 l"), result.products.map { it.name })
        val butter = result.offers.first { it.externalId == "m1:a1" }
        assertEquals("edeka:m1:a1", butter.id)
        assertEquals(179, butter.priceCents)
        assertEquals(716, butter.basePriceCents)
        assertEquals("kg", butter.baseUnit)
        assertEquals("2026-09-14", butter.validFrom)
        assertEquals("2026-09-19", butter.validUntil)
        assertEquals("https://img.edeka.de/butter.jpg", butter.imageUrl)
        assertEquals("https://www.edeka.de/eh/markt/m1", butter.sourceUrl)
        assertEquals("m1", result.storeId)
    }

    @Test fun `next week shows the following weeks offers`() = runTest {
        serve(listOf(market("m1", "26188")), mapOf("m1" to pricedOffers))
        val result = provider().fetch(RetailerRequest("26188", week = OfferWeek.NEXT))
        assertEquals(listOf("Naechste Woche"), result.products.map { it.name })
    }

    @Test fun `an empty first market falls through to the next nearby one`() = runTest {
        serve(
            listOf(market("m1", "04109"), market("m2", "04103")),
            mapOf("m1" to """{"docs":[{"angebotid":"x","titel":"Gratis","preis":"0"}]}""", "m2" to pricedOffers),
        )
        val result = provider().fetch(RetailerRequest("04109"))
        assertEquals("m2", result.storeId)
        assertTrue(result.offers.isNotEmpty())
    }

    @Test fun `the market with the exact postal code is tried before nearer listed ones`() = runTest {
        serve(
            listOf(market("near", "26122"), market("exact", "26188")),
            mapOf("near" to pricedOffers, "exact" to pricedOffers),
        )
        assertEquals("exact", provider().fetch(RetailerRequest("26188")).storeId)
    }

    @Test fun `gives up with a clear message when no market has priced offers`() = runTest {
        val empty = """{"docs":[]}"""
        serve(listOf(market("m1", "04109"), market("m2", "04103")), mapOf("m1" to empty, "m2" to empty))
        val failure = runCatching { provider().fetch(RetailerRequest("04109")) }.exceptionOrNull()
        assertTrue(failure!!.message!!.contains("2 Märkte"))
        assertTrue(failure.message!!.contains("keiner lieferte Angebote mit Preisen"))
    }

    @Test fun `a blocked request surfaces as 403 so the app can offer the confirmation`() = runTest {
        serve(emptyList(), emptyMap(), marketStatus = 403)
        val failure = runCatching { provider().fetch(RetailerRequest("26188")) }.exceptionOrNull()
        assertTrue(failure!!.message!!.contains("403"))
    }

    @Test fun `a block on the offers request also surfaces instead of trying every market`() = runTest {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse =
                if (request.requestUrl!!.encodedPath.endsWith("/markets")) {
                    MockResponse().setBody("""{"markets":[${market("m1", "26188")},${market("m2", "26188")}]}""")
                } else MockResponse().setResponseCode(403)
        }
        val failure = runCatching { provider().fetch(RetailerRequest("26188")) }.exceptionOrNull()
        assertTrue(failure!!.message!!.contains("403"))
        assertEquals("only the first market should have been asked", 2, server.requestCount)
    }

    @Test fun `data handed over by the browser is used without any network request`() = runTest {
        val handoff = """{"postalCode":"26188","market":${market("m9", "26188")},"offers":$pricedOffers,"error":null}"""
        val result = provider(handoff = { if (it == "26188") handoff else null }).fetch(RetailerRequest("26188"))
        assertEquals("m9", result.storeId)
        assertEquals(2, result.offers.size)
        assertEquals(0, server.requestCount)
    }

    @Test fun `an error reported by the browser is passed on`() = runTest {
        val handoff = """{"postalCode":"26188","market":null,"offers":null,"error":"EDEKA-Abruf im Browser fehlgeschlagen: HTTP 403"}"""
        val failure = runCatching { provider(handoff = { handoff }).fetch(RetailerRequest("26188")) }.exceptionOrNull()
        assertTrue(failure!!.message!!.contains("HTTP 403"))
    }

    @Test fun `the confirmation url carries the postal code once one was requested`() = runTest {
        val edeka = provider()
        assertEquals("https://www.edeka.de/marktsuche.jsp", edeka.challengeUrl)
        serve(listOf(market("m1", "26188")), mapOf("m1" to pricedOffers))
        edeka.fetch(RetailerRequest("26188"))
        assertEquals("https://www.edeka.de/marktsuche.jsp?korbuino_plz=26188", edeka.challengeUrl)
    }

    @Test fun `rejects an invalid postal code`() = runTest {
        assertFalse(runCatching { provider().fetch(RetailerRequest("abc")) }.isSuccess)
        assertNull(runCatching { provider().fetch(RetailerRequest("123456")) }.getOrNull())
    }

    @Test fun `parses a real EDEKA answer, including explicit nulls and millisecond dates`() = runTest {
        val sample = kotlinx.serialization.json.Json.parseToJsonElement(
            javaClass.getResource("/edeka-real-sample.json")!!.readText(),
        ).let { it as kotlinx.serialization.json.JsonObject }
        val handoff = """{"postalCode":"26188","market":${sample["market"]},"offers":${sample["offers"]},"error":null}"""

        val result = provider(handoff = { handoff }).fetch(RetailerRequest("26188"))

        assertTrue("real sample must yield offers", result.offers.isNotEmpty())
        result.offers.forEach { offer ->
            assertTrue("price must be positive: ${offer.priceCents}", offer.priceCents > 0)
            assertTrue("validUntil comes from epoch milliseconds", offer.validUntil!!.matches(Regex("\\d{4}-\\d{2}-\\d{2}")))
            assertTrue(offer.imageUrl!!.startsWith("https://"))
        }
        assertTrue("unit price like '1kg = 15,92' must be read", result.offers.any { it.baseUnit == "kg" && it.basePriceCents != null })
    }

    @Test fun `a validity date given once for the whole answer applies to every offer`() = runTest {
        // Real answers carry "gueltig_von": null on each offer and the dates on the root.
        val payload = """{"gueltig_von":1789689600000,"gueltig_bis":1789776000000,"docs":[
            {"angebotid":1,"titel":"Butter","preis":1.99,"gueltig_von":null,"gueltig_bis":null}]}"""
        serve(listOf(market("m1", "26188")), mapOf("m1" to payload))
        val result = provider().fetch(RetailerRequest("26188"))
        assertEquals("2026-09-19", result.offers.single().validUntil)
        assertEquals("2026-09-18", result.offers.single().validFrom)
    }
}
