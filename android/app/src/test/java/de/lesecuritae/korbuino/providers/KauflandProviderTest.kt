package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertNull
import de.lesecuritae.korbuino.OfferPricing
import java.time.LocalDate
import org.junit.Before
import org.junit.Test
import java.time.Instant

class KauflandProviderTest {
    private lateinit var server: MockWebServer
    private val cookies = mutableListOf<String>()
    private val paths = mutableListOf<String>()
    private var availabilityBody: String? = null
    private var pageBody: String? = null

    @Before fun setUp() {
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val path = request.path.orEmpty()
                paths += path
                return when {
                    path.startsWith("/.sitemap.xml") -> MockResponse().setBody(SITEMAP)
                    path.startsWith("/.klstorebygeo.storeName=DE4330") -> MockResponse().setBody("""{"n":"DE4330","pc":"01917","t":"Kamenz"}""")
                    path.startsWith("/.klstorebygeo.storeName=DE2543") -> MockResponse().setBody("""{"n":"DE2543","pc":"45141","t":"Essen"}""")
                    path.startsWith("/.klstorebygeo.storeName=DE3203") -> MockResponse().setBody("""{"n":"DE3203","pc":"45143","t":"Essen"}""")
                    path.startsWith("/.kloffers.storeName=") -> MockResponse().setBody(availabilityBody ?: availability())
                    path.startsWith("/angebote/uebersicht.html") -> {
                        val cookie = request.getHeader("Cookie").orEmpty()
                        cookies += cookie
                        // The regional price depends on the store named in the cookie.
                        val price = if ("DE4330" in cookie) "1.59" else "1.79"
                        MockResponse().setBody(pageBody ?: page(price))
                    }
                    else -> MockResponse().setResponseCode(404)
                }
            }
        }
        server.start()
    }

    @After fun tearDown() { server.shutdown() }

    private fun provider() = KauflandProvider(OkHttpClient(), server.url("/").toString().trimEnd('/')) { Instant.parse("2026-09-19T10:00:00Z") }

    private fun availability() = (0 until 120).joinToString(",", "[", "]") {
        """{"klNr":"$it","dateFrom":"2026-09-17","dateTo":"2026-09-23"}"""
    }

    private fun page(price: String): String {
        val offers = (0 until 120).joinToString(",") { index ->
            val title = if (index == 0) "HOCHLAND" else "Produkt $index"
            val subtitle = if (index == 0) "Schmelzkäse " else ""
            val formatted = if (index == 0) price else "2.49"
            val base = if (index == 0 && price == "1.59") "(1 kg = 7.95 - 10.60)" else "(1 kg = 8.95 - 11.94)"
            """{"offerId":"ART.$index","klNr":"$index","dateFrom":"2026-09-17","dateTo":"2026-09-23","title":"$title","subtitle":"$subtitle",
               "price":$formatted,"formattedPrice":"$formatted","formattedBasePrice":"$base","loyaltyFormattedPrice":"${if (index == 1) "1.99*" else ""}",
               "listImage":"/media/$index.jpg"}"""
        }
        return """<html><script>{"component":"OfferTemplate","props":{"offerData":{"cycles":[{"categories":[{"displayName":"Molkereiprodukte, Fette","offers":[$offers]}]}]}}};</script></html>"""
    }

    @Test fun `bundle restriction in detail title remains conditional on selected card`() {
        val raw = page("1.59").replace("\"offerId\":\"ART.0\"", "\"bbyMessage\":[\"3 Stück\"],\"detailTitle\":\"Mit Kaufland Card\",\"offerId\":\"ART.0\"")
        val offer = provider().parse(raw, setOf("0"), LocalDate.parse("2026-09-19")).offers.single()
        assertEquals(3, offer.multiBuyQuantity)
        assertTrue(offer.multiBuyCondition!!.contains("Mit Kaufland Card"))
        assertNull(OfferPricing.quote(offer,3).totalCents)
        assertEquals(159,OfferPricing.quote(offer,3,setOf("kaufland_xtra")).totalCents)
    }

    @Test fun `the store's region decides the price`() = runTest {
        val kamenz = provider().fetch(RetailerRequest("01917", citySlug = "Kamenz"))
        val hochland = kamenz.offers.first { it.externalId == "ART.0" }
        assertEquals(159, hochland.priceCents)
        assertEquals(795, hochland.basePriceCents)
        assertEquals("kg", hochland.baseUnit)
        assertTrue(cookies.last().contains("x-aem-variant=DE4330"))

        val essen = provider().fetch(RetailerRequest("45141", citySlug = "Essen"))
        assertEquals(179, essen.offers.first { it.externalId == "ART.0" }.priceCents)
        assertTrue(cookies.last().contains("x-aem-variant=DE2543"))
    }

    @Test fun `several stores in one city are told apart by the postal code`() = runTest {
        provider().fetch(RetailerRequest("45143", citySlug = "Essen"))
        assertTrue(cookies.last().contains("x-aem-variant=DE3203"))
    }

    @Test fun `the member price and the offer details are taken over`() = runTest {
        val offers = provider().fetch(RetailerRequest("01917", citySlug = "Kamenz")).offers
        val xtra = offers.first { it.externalId == "ART.1" }
        assertEquals(199, xtra.loyaltyPriceCents)
        assertEquals("kaufland_xtra", xtra.loyaltyProgram)
        assertEquals("Molkereiprodukte, Fette", xtra.categoryId)
        assertEquals("2026-09-17", xtra.validFrom)
        assertTrue(xtra.imageUrl.orEmpty().endsWith("/media/1.jpg"))
    }

    @Test fun `without a city the provider gives way to the default page`() = runTest {
        val failure = runCatching { provider().fetch(RetailerRequest("01917")) }.exceptionOrNull()
        assertTrue(failure?.message.orEmpty().contains("Stadt"))
    }

    @Test fun `explicit store is honored without a city and must match postal code`() = runTest {
        val result = provider().fetch(RetailerRequest("45143", marketId = "DE3203"))
        assertEquals("DE3203", result.storeId)
        assertTrue(cookies.last().contains("x-aem-variant=DE3203"))
        assertTrue(paths.none { it.contains("sitemap") })
        val failure = runCatching { provider().fetch(RetailerRequest("45141", marketId = "DE3203")) }.exceptionOrNull()
        assertTrue(failure?.message.orEmpty().contains("PLZ"))
    }

    @Test fun `city match never selects a different postal code`() = runTest {
        val failure = runCatching { provider().fetch(RetailerRequest("45149", citySlug = "Essen")) }.exceptionOrNull()
        assertTrue(failure?.message.orEmpty().contains("PLZ"))
        assertTrue(cookies.isEmpty())
    }

    @Test fun `next week absence is empty and old offers are never redated`() = runTest {
        val result = provider().fetch(RetailerRequest("01917", marketId = "DE4330", week = OfferWeek.NEXT))
        // Source fixture ends Wednesday 23 September; the requested next week starts Monday 21.
        assertTrue(result.offers.isNotEmpty())
        assertTrue(result.offers.all { it.validFrom == "2026-09-17" && it.validUntil == "2026-09-23" })
        assertTrue(paths.last().contains("kloffer-week=next"))
        availabilityBody = "[]"
        assertTrue(provider().fetch(RetailerRequest("01917", marketId = "DE4330", week = OfferWeek.NEXT)).offers.isEmpty())
    }

    @Test fun `availability and raw validity must overlap each other within requested week`() = runTest {
        availabilityBody = """[{"klNr":"0","dateFrom":"2026-09-21","dateTo":"2026-09-21"}]"""
        pageBody = page("1.59").replace("2026-09-17", "2026-09-22")
        val result = provider().fetch(RetailerRequest("01917", marketId = "DE4330", week = OfferWeek.NEXT))
        assertTrue(result.offers.isEmpty())
    }

    @Test fun `authentic public bundle remains conditional for incomplete pack quantities`() {
        val raw = javaClass.getResource("/kaufland-de5220-multibuy-20261015.json")!!.readText()
        val page = """{"component":"OfferTemplate","props":{"offerData":{"cycles":[{"categories":[{"offers":[$raw]}]}]}}}"""
        val offer = provider().parse(page, setOf("01468850"), LocalDate.of(2026, 10, 15)).offers.single()
        assertEquals("2026-10-12", offer.validFrom)
        assertEquals("2026-10-17", offer.validUntil)
        assertEquals(3, offer.multiBuyQuantity)
        assertEquals(300, offer.multiBuyTotalCents)
        assertEquals("75 g", offer.packSize)
        assertNull(offer.singlePriceCents)
        assertNull(offer.multiBuyMixGroup)
        for (q in listOf(1, 2, 4)) assertNull(OfferPricing.quote(offer, q).totalCents)
        assertEquals(300, OfferPricing.quote(offer, 3).totalCents)
        assertEquals(600, OfferPricing.quote(offer, 6).totalCents)
        assertTrue(provider().parse(page, setOf("01468850"), LocalDate.of(2026, 10, 18)).offers.isEmpty())
        assertTrue(provider().parse(page, setOf("01468850"), LocalDate.of(2026, 10, 10)).offers.isEmpty())
    }

    @Test fun `registry keeps Kaufland regional failures and empty weeks authoritative`() {
        assertTrue(ProviderRegistry.default(OkHttpClient()).byId("kaufland") is KauflandProvider)
    }

    private companion object {
        val SITEMAP = """<urlset>
            <url><loc>https://filiale.kaufland.de/service/filiale/kamenz-willy-muehle-str-4330.html</loc></url>
            <url><loc>https://filiale.kaufland.de/service/filiale/essen-nordviertel-2543.html</loc></url>
            <url><loc>https://filiale.kaufland.de/service/filiale/essen-altendorf-3203.html</loc></url>
            <url><loc>https://filiale.kaufland.de/service/filiale/hamm-heessen-4363.html</loc></url>
            <url><loc>https://filiale.kaufland.de/service/filiale/giessen-5013.html</loc></url>
        </urlset>"""
    }
}
