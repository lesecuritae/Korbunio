package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.OfferDisplay
import de.lesecuritae.korbuino.OfferMatcher
import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import org.junit.Assume.assumeTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import java.io.File
import java.time.Instant

class OfferCoverageTest {
    @Test fun `published grouped quantity does not become one gram`() {
        assertEquals("1000 g", ProviderParsing.packSize("je 1.000 g"))
        assertEquals("2 x 1000 g", ProviderParsing.packSize("2 x 1.000 g"))
        assertEquals("1.5 l", ProviderParsing.packSize("1.5 l"))
        assertEquals("0.500 l", ProviderParsing.packSize("0.500 l"))
    }

    @Test fun `actual aktiv weekend marker does not start on Monday`() {
        val result = AktivIrmaProvider().parse(fixture("aktiv_selected.html"))
        val product = result.products.single { it.name.contains("iglo") }
        assertEquals("2026-11-12", result.offers.single { it.productId == product.id }.validFrom)
        assertEquals("2026-11-14", result.offers.single { it.productId == product.id }.validUntil)
        assertTrue(result.offers.filter { it.productId != product.id }.all { it.validFrom == "2026-11-09" })
    }

    private fun fixture(name: String) = javaClass.classLoader!!.getResourceAsStream("offer_coverage/$name")!!.bufferedReader().use { it.readText() }
    private val now = { Instant.parse("2026-11-09T12:00:00Z") }
    private fun keys(server: MockWebServer) = server.enqueue(MockResponse().setBody("""<script>{"apiKey":"fixture","clientKey":"fixture"}</script>"""))

    @Test fun `actual public response retains price dates descriptions and quantity in searchable entity`() = runTest {
        MockWebServer().use { server ->
            server.start(); keys(server)
            server.enqueue(MockResponse().setBody("""{"results":[${fixture("marktguru_kania.json")}]}"""))
            val result = MarktguruProvider("Lidl", OkHttpClient(), server.url("/home").toString(), server.url("/search").toString(), now = now).fetch(RetailerRequest("04109"))
            val offer = result.offers.single()
            assertEquals(399, offer.priceCents)
            assertEquals("400 g", offer.packSize)
            assertEquals("Versch. Sorten. Je 400 g", offer.description)
            assertEquals("2026-11-09", offer.validFrom)
            assertEquals("2026-11-14", offer.validUntil)
            val display = OfferDisplay(offer, result.products.single().name, brand = "Kania")
            for (query in listOf("Kania", "Wildgerichte", "400 g", "Sorten")) assertEquals(query, 1, OfferMatcher.matches(query, listOf(display)).size)
            for (query in listOf("Hirschgulasch", "Wildschwein", "Wildgulasch")) assertTrue(OfferMatcher.matches(query, listOf(display)).isEmpty())
        }
    }

    @Test fun `regional KaufDA viewer keeps evidenced Wildschwein without inventing Hirsch`() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(MockResponse().setBody("<a href='${server.url("/Leipzig/Lidl/p-r74")}'>Lidl</a>"))
            server.enqueue(MockResponse().setBody("""[{"lat":"51.34","lon":"12.37","address":{"city":"Leipzig"}}]"""))
            server.enqueue(MockResponse().setBody("""<script id="__NEXT_DATA__">{"props":{"pageProps":{"pageInformation":{"brochures":{"viewer":[{"id":"2501324792","publisher":{"name":"Lidl"}}]}}}}}</script>"""))
            server.enqueue(MockResponse().setBody(fixture("kaufda_kania.json")))
            val result = KaufdaRetailerProvider("marktguru-lidl", "Lidl", "Lidl", "Lidl", OkHttpClient(), server.url("/").toString().trimEnd('/'), now,
                regionalViewer = true, viewerBaseUrl = server.url("/").toString().trimEnd('/'), geocodeUrl = server.url("/geocode").toString()).fetch(RetailerRequest("04109"))
            assertEquals("Kania Wildschwein", result.products.single().name)
            assertEquals(399, result.offers.single().priceCents)
            assertEquals("400 g", result.offers.single().packSize)
            assertTrue(result.offers.single().sourceUrl.contains("/Leipzig/"))
            assertEquals("2026-11-14", result.offers.single().validUntil)
            assertFalse(result.products.single().name.contains("Hirsch"))
            repeat(3) { server.takeRequest() }
            val viewerRequest = server.takeRequest().requestUrl!!
            assertEquals("51.34", viewerRequest.queryParameter("lat"))
            assertEquals("12.37", viewerRequest.queryParameter("lng"))
        }
    }

    @Test fun `actual Lidl Plus response keeps the stated without and with prices`() = runTest {
        for ((file, regular, member) in listOf(Triple("marktguru_mayonnaise.json", 169, 129), Triple("marktguru_gulaschsuppe.json", 179, 139))) {
            MockWebServer().use { server ->
                server.start(); keys(server)
                server.enqueue(MockResponse().setBody("""{"results":[${fixture(file)}]}"""))
                val result = MarktguruProvider("Lidl", OkHttpClient(), server.url("/home").toString(), server.url("/search").toString(), now = now).fetch(RetailerRequest("50939"))
                assertEquals(regular, result.offers.single().priceCents)
                assertEquals(member, result.offers.single().loyaltyPriceCents)
                assertEquals("lidl_plus", result.offers.single().loyaltyProgram)
            }
        }
    }

    @Test fun `KaufDA regular price and Lidl Plus price remain separate`() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(MockResponse().setBody("<a href='${server.url("/Koeln/Lidl/p-r74")}'>Lidl</a>"))
            server.enqueue(MockResponse().setBody("""[{"lat":"50.92","lon":"6.92","address":{"city":"Köln"}}]"""))
            server.enqueue(MockResponse().setBody("""<script id="__NEXT_DATA__">{"props":{"pageProps":{"pageInformation":{"brochures":{"viewer":[{"id":"2501324797","publisher":{"name":"Lidl"}}]}}}}}</script>"""))
            server.enqueue(MockResponse().setBody(fixture("kaufda_lidl_plus.json")))
            val result = KaufdaRetailerProvider("marktguru-lidl", "Lidl", "Lidl", "Lidl", OkHttpClient(), server.url("/").toString().trimEnd('/'), now,
                regionalViewer = true, viewerBaseUrl = server.url("/").toString().trimEnd('/'), geocodeUrl = server.url("/geocode").toString()).fetch(RetailerRequest("50939"))
            val mayo = result.offers.single { offer -> result.products.single { it.id == offer.productId }.name.contains("Mayonnaise") }
            val soup = result.offers.single { offer -> result.products.single { it.id == offer.productId }.name.contains("Gulaschsuppe") }
            assertEquals(169, mayo.priceCents); assertEquals(129, mayo.loyaltyPriceCents)
            assertEquals(179, soup.priceCents); assertEquals(139, soup.loyaltyPriceCents)
        }
    }

    @Test fun `HOLAB crate threshold never becomes an unconditional single price`() = runTest {
        MockWebServer().use { server ->
            server.start(); server.enqueue(MockResponse().setBody(fixture("holab_selected.html")))
            val result = HtmlFlyerProvider("holab", "HOL’AB!", server.url("/angebote").toString(), OkHttpClient(),
                now = { java.time.LocalDate.parse("2026-11-09") }).fetch(RetailerRequest("26135"))
            assertEquals(5, result.offers.size)
            val water = result.offers.single { offer -> result.products.single { it.id == offer.productId }.name == "Vilsa Mineralwasser Glas" }
            assertEquals(2, water.multiBuyQuantity)
            assertEquals(898, water.multiBuyTotalCents)
            assertEquals(499, water.singlePriceCents)
            assertEquals(499, de.lesecuritae.korbuino.OfferPricing.quote(water, 1).totalCents)
            assertEquals("2026-11-14", water.validUntil)
            assertEquals("12 x 0.7 l", water.packSize)
        }
    }

    private fun provider(result: ProviderResult? = null) = object : RetailerProvider {
        override val id = "marktguru-lidl"
        override val displayName = "Lidl"
        override suspend fun fetch(request: RetailerRequest) = result ?: error("fixture outage")
    }
    private fun result(name: String, count: Int = 1): ProviderResult {
        val product = ProductEntity(name, name, "", name)
        return ProviderResult(listOf(product), (0 until count).map { i ->
            OfferEntity("$name:$i", "marktguru-lidl", name, externalId = "$i", priceCents = 399,
                sourceUrl = "https://example.org/", cachedAt = 0, packSize = "400 g", description = if (count == 1) "" else "Fixture $i")
        })
    }

    @Test fun `complements 150 existing articles and retains primary during source failure`() = runTest {
        val primary = result("Fixture catalogue", 150)
        val extra = result("Kania Wildschwein")
        assertEquals(151, SupplementingRetailerProvider(provider(primary), provider(extra)).fetch(RetailerRequest("04109")).offers.size)
        val failure = SupplementingRetailerProvider(provider(primary), provider()).fetch(RetailerRequest("04109"))
        assertEquals(primary.offers, failure.offers)
        assertTrue(failure.sourceWarnings.isNotEmpty())
        val wrong = extra.copy(offers = extra.offers.map { it.copy(retailerId = "wrong") })
        assertEquals(primary.offers, SupplementingRetailerProvider(provider(primary), provider(wrong)).fetch(RetailerRequest("04109")).offers)
    }

    @Test fun `exact duplicates collapse but different varieties and packs survive`() = runTest {
        val base = result("Kania Wildgerichte")
        val duplicate = base.copy(offers = base.offers.map { it.copy(id = "other", externalId = "other") })
        assertEquals(1, SupplementingRetailerProvider(provider(base), provider(duplicate)).fetch(RetailerRequest("04109")).offers.size)
        for (variant in listOf(duplicate.copy(offers = duplicate.offers.map { it.copy(packSize = "800 g") }),
            duplicate.copy(offers = duplicate.offers.map { it.copy(description = "Ausdrücklich andere Sorte") }))) {
            assertEquals(2, SupplementingRetailerProvider(provider(base), provider(variant)).fetch(RetailerRequest("04109")).offers.size)
        }
    }

    @Test fun `changed schema empty response and later page failure are distinguishable`() = runTest {
        for (body in listOf("{}", """{"results":{}}""", """{"results":[null]}""", """{"results":[]}""")) {
            MockWebServer().use { server ->
                server.start(); keys(server); server.enqueue(MockResponse().setBody(body))
                val attempt = runCatching { MarktguruProvider("Lidl", OkHttpClient(), server.url("/home").toString(), server.url("/search").toString(), now = now).fetch(RetailerRequest("04109")) }
                assertEquals(body, body.contains("\"results\":[]"), attempt.isSuccess)
            }
        }
        MockWebServer().use { server ->
            server.start(); keys(server)
            val rows = (1..100).joinToString(",") { """{"id":$it,"product":{"name":"Fixture $it"},"price":1} """ }
            server.enqueue(MockResponse().setBody("""{"results":[$rows],"totalResults":101}"""))
            server.enqueue(MockResponse().setResponseCode(503))
            assertTrue(runCatching { MarktguruProvider("Lidl", OkHttpClient(), server.url("/home").toString(), server.url("/search").toString(), now = now).fetch(RetailerRequest("04109")) }.isFailure)
        }
    }

    @Test fun `optional live captured Lidl pages retain Kania beyond first hundred`() = runTest {
        val directory = System.getenv("KORBUINO_AUDIT_RAW_DIR")
        assumeTrue("Explicit offline replay of locally captured live pages only", !directory.isNullOrBlank())
        for (postal in listOf("04109", "50939")) {
            val rows = Json.parseToJsonElement(File(directory, "mg-$postal-Lidl.json").readText()).jsonArray
            MockWebServer().use { server ->
                server.start(); keys(server)
                rows.chunked(100).forEach { chunk -> server.enqueue(MockResponse().setBody("""{"results":[${chunk.joinToString(",")}],"totalResults":${rows.size}}""")) }
                val result = MarktguruProvider("Lidl", OkHttpClient(), server.url("/home").toString(), server.url("/search").toString(), now = now).fetch(RetailerRequest(postal))
                val hit = result.offers.single { it.externalId == "25583947" }
                assertEquals(399, hit.priceCents)
                assertTrue(hit.description.contains("400 g"))
                println("LIVE_CAPTURE_REPLAY postal=$postal raw=${rows.size} imported=${result.offers.size} kania=present")
            }
        }
    }
}
