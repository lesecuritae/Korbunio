package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate

class EdekaHtmlOffersTest {
    private fun fixture() = javaClass.classLoader!!.getResourceAsStream("offer_coverage/edeka_romano_offers.html")!!.bufferedReader().use { it.readText() }
    private val day = LocalDate.of(2026, 11, 10)

    @Test fun `real public market markup keeps normal app prices deposits quantities and distinct gtins`() {
        val provider = EdekaProvider()
        val result = provider.parseOffers(EdekaHtmlOffers.parse(fixture(), "https://www.edeka.de/maerkte/070696/angebote/"), "12145", "https://www.edeka.de/maerkte/070696/angebote/", day)
        assertEquals(9, result.offers.size)
        val butter = result.products.single { it.name == "Meggle Feine Butter oder Streichzart" }
        val offer = result.offers.single { it.productId == butter.id }
        assertEquals(129, offer.priceCents); assertEquals(111, offer.loyaltyPriceCents)
        assertEquals("250 g", offer.packSize)
        assertEquals("2026-11-09", offer.validFrom); assertEquals("2026-11-14", offer.validUntil)
        assertEquals(setOf("4000508059087", "8711000708651"), result.products.filter { it.name == "Jacobs Krönung" }.map { it.gtin }.toSet())
        val drink = result.products.single { it.name == "Red Bull Energy Drink" }
        assertEquals(25, result.offers.single { it.productId == drink.id }.depositCents)
        assertNull(ProviderParsing.depositCents("250 ml für 0,99 €"))
        assertNull(ProviderParsing.depositCents("zzgl. 0,25 € Pfand plus zzgl. 0,15 € Pfand"))
        val avocado = result.products.single { it.name == "Avocados" }
        val bundle = result.offers.single { it.productId == avocado.id }
        assertEquals(4, bundle.multiBuyQuantity); assertEquals(300, bundle.multiBuyTotalCents); assertEquals(99, bundle.singlePriceCents)
        assertEquals(75, bundle.priceCents)
        assertTrue(provider.parseOffers(EdekaHtmlOffers.parse(fixture(), "https://www.edeka.de/maerkte/070696/angebote/"), "12145", "https://www.edeka.de/maerkte/070696/angebote/", day.plusWeeks(1)).offers.isEmpty())
    }

    @Test fun `unknown price or validity layout cannot become a successful partial replacement`() {
        for (html in listOf(fixture().replace("Gültig vom", "Datum unbekannt"), fixture().replace("Festpreis von", "Unbekannter Preis"))) {
            assertTrue(runCatching { EdekaHtmlOffers.parse(html, "https://www.edeka.de/maerkte/070696/angebote/") }.isFailure)
        }
    }

    @Test fun `network reader follows only the selected market and replaces incomplete legacy metadata`() = runTest {
        MockWebServer().use { server ->
            server.start()
            val market = server.url("/eh/romano/index.jsp").toString()
            server.enqueue(MockResponse().setBody("""{"markets":[{"id":"12145","url":"$market","contact":{"address":{"city":{"zipCode":"50939"}}}}]}"""))
            server.enqueue(MockResponse().setBody("""{"docs":[{"angebotid":"legacy","titel":"Legacy","preis":1.29,"gueltig_von":"2026-11-09","gueltig_bis":"2026-11-14"}]}"""))
            server.enqueue(MockResponse().setBody("<a href='/maerkte/070696/angebote/'>Angebote</a><a href='/maerkte/070696/angebote'>Angebote</a>"))
            server.enqueue(MockResponse().setBody(fixture()))
            val provider = EdekaProvider(OkHttpClient(), server.url("/markets").toString(), server.url("/api-offers").toString(), { day }, handoff = { null }, publicBaseUrl = server.url("/").toString().trimEnd('/'))
            val result = provider.fetch(RetailerRequest("50939"))
            assertEquals(9, result.offers.size)
            assertTrue(result.products.none { it.name == "Legacy" })
            assertTrue(result.offers.any { it.loyaltyPriceCents == 88 })
            assertEquals(4, server.requestCount)
        }
    }
    @Test fun `exactly matching legacy ids survive metadata upgrades while ambiguous variants never share an id`() {
        val provider = EdekaProvider()
        val current = provider.parseOffers(EdekaHtmlOffers.parse(fixture(), "https://www.edeka.de/maerkte/070696/angebote/"), "12145", "https://www.edeka.de/maerkte/070696/angebote/", day)
        val old = current.copy(products = current.products.map { it.copy(id = "old-${it.id}", gtin = null) },
            offers = current.offers.map { it.copy(id = "old-${it.id}", externalId = "old-${it.externalId}", productId = "old-${it.productId}", loyaltyPriceCents = null, loyaltyProgram = null, loyaltyLabel = null) })
        val upgraded = provider.preserveOfferIds(old, current)
        assertEquals(old.offers.map { it.id }.toSet(), upgraded.offers.map { it.id }.toSet())
        assertTrue(upgraded.offers.any { it.loyaltyPriceCents == 88 })
        assertEquals(setOf("4000508059087", "8711000708651"), upgraded.products.filter { it.name == "Jacobs Krönung" }.map { it.gtin }.toSet())
    }

}
