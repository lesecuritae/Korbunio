package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import de.lesecuritae.korbuino.LoyaltyBenefits
import de.lesecuritae.korbuino.effectivePriceCents
import org.junit.Before
import org.junit.Test

class ServerProviderTest {
    private lateinit var server: MockWebServer

    @Before fun setUp() { server = MockWebServer().also { it.start() } }
    @After fun tearDown() { server.shutdown() }

    @Test fun `combined server mode loads every page without refreshing sources repeatedly`() = runTest {
        // Previously combined mode only fetched page one, and single-retailer
        // fallback silently stopped after 20 pages.
        for (page in 1..21) {
            server.enqueue(MockResponse().setBody("""
                {"page_count":21,"offers":[{"offer_id":"$page","retailer":"Test","product":"Produkt $page","regular_price":1.99}]}
            """))
        }
        val result = ServerProvider(server.url("/").toString(), "", OkHttpClient()).fetch(RetailerRequest("78467"))
        assertEquals(21, result.offers.size)
        for (page in 1..21) {
            val request = server.takeRequest().body.readUtf8()
            val payload = kotlinx.serialization.json.Json.parseToJsonElement(request).toString()
            org.junit.Assert.assertTrue(payload.contains("\"view\":\"all\""))
            org.junit.Assert.assertTrue(payload.contains("\"page\":$page,"))
            org.junit.Assert.assertTrue(payload.contains("\"refresh\":${page == 1}"))
        }
    }

    @Test fun `server import preserves every program and simultaneous price and cashback choices`() = runTest {
        val programs = listOf("rewe_bonus", "lidl_plus", "penny_app", "netto_plus",
            "netto_scottie_plus", "kaufland_xtra", "edeka_app", "marktkauf_app",
            "mein_globus", "payback", "rossmann_app", "mueller_blueten")
        val items = programs.mapIndexed { index, program -> """
            {"offer_id":"$index","retailer":"Test","product":"Produkt $index","regular_price":2.29,
             "benefits":[{"program_id":"$program","kind":"direct_price","value":1.79,"label":"$program","condition":"App-Preis"},
                         {"program_id":"payback","kind":"cashback","value":0.20,"label":"PAYBACK"}]}
        """ }
        server.enqueue(MockResponse().setBody("{\"offers\":[${items.joinToString(",") }]}"))
        val result = ServerProvider(server.url("/").toString(), "", OkHttpClient()).fetch(RetailerRequest("78467"))
        assertEquals(12, result.offers.size)
        result.offers.forEachIndexed { index, offer ->
            assertEquals(2, LoyaltyBenefits.forOffer(offer).size)
            assertEquals(229, effectivePriceCents(offer, emptySet()))
            assertEquals(179, effectivePriceCents(offer, setOf(programs[index])))
            if (programs[index] != "payback") assertEquals(229, effectivePriceCents(offer, setOf("payback")))
            assertEquals(20, LoyaltyBenefits.forOffer(offer).single { it.kind == "cashback" }.cents)
        }
    }

    @Test fun `invalid bonus amounts and older server responses remain safe`() = runTest {
        server.enqueue(MockResponse().setBody("""
            {"offers":[{"offer_id":"x","retailer":"Test","product":"Produkt","regular_price":1.11,
              "benefits":[{"program_id":"kaufland_xtra","kind":"direct_price","value":-1},
                          {"program_id":"payback","kind":"points","value":100}]}]}
        """))
        val offer = ServerProvider(server.url("/").toString(), "", OkHttpClient()).fetch(RetailerRequest("78467")).offers.single()
        assertEquals(111, offer.priceCents)
        assertEquals(emptyList<Any>(), LoyaltyBenefits.forOffer(offer))
        assertNull(offer.loyaltyProgram)
    }

    @Test fun `follows current result contract and keeps proxied images`() = runTest {
        server.enqueue(MockResponse().setBody("""
            {"result_url":"${server.url("/results/live").toString()}?token=test"}
        """))
        server.enqueue(MockResponse().setBody("""
            {"offers":[{"offer_id":"netto:iphone","retailer":"Netto Marken-Discount","product":"Apple iPhone 17 Salbei","regular_price":2.76,"image_url":"/image?src=https%3A%2F%2Fcdn.example%2Fiphone.jpg"}]}
        """))
        val provider = ServerProvider(server.url("/").toString().trimEnd('/'), "", OkHttpClient())
        val result = provider.fetch(RetailerRequest("12345"))
        assertEquals(276, result.offers.single().priceCents)
        assertEquals("${server.url("/").toString().trimEnd('/')}/image?src=https%3A%2F%2Fcdn.example%2Fiphone.jpg", result.offers.single().imageUrl)
    }
}
