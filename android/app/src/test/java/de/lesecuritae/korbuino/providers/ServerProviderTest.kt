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
    @Test fun `server preview keeps dates so it is excluded from todays shopping`() = runTest {
        server.enqueue(MockResponse().setBody("""
            {"offers":[{"offer_id":"cola","retailer":"Lidl","product":"Coca-Cola Cola",
              "regular_price":3.99,"valid_from":"2026-10-22","valid_until":"2026-10-24"}]}
        """))
        val offer = ServerProvider(server.url("/").toString(), "", OkHttpClient())
            .fetch(RetailerRequest("26122")).offers.single()
        assertEquals("2026-10-22", offer.validFrom)
        assertEquals("2026-10-24", offer.validUntil)
        assertEquals(399, offer.priceCents)
    }

    @Test fun `confirmed absence survives combined mode and direct fallback`() = runTest {
        val body = """{"offers":[],"unavailable_retailers":["ALDI Nord","aktiv & irma"]}"""
        server.enqueue(MockResponse().setBody(body))
        val combined = ServerProvider(server.url("/").toString(), "", OkHttpClient())
            .fetch(RetailerRequest("80331"))
        assertEquals(setOf("ALDI Nord", "aldi-nord", "aktiv & irma", "aktiv-irma"), combined.unavailableRetailerIds.toSet())
        server.enqueue(MockResponse().setBody(body))
        val direct = ServerProvider(server.url("/").toString(), "", OkHttpClient(), "ALDI Nord", "aldi-nord")
            .fetch(RetailerRequest("80331"))
        org.junit.Assert.assertTrue(direct.noLocalMarket)
        assertNull(ProviderImportPolicy.rejectionReason("aldi-nord", direct, 100))
    }

    @Test fun `older empty response cannot claim confirmed market absence`() = runTest {
        server.enqueue(MockResponse().setBody("""{"offers":[]}"""))
        val direct = ServerProvider(server.url("/").toString(), "", OkHttpClient(), "ALDI Nord", "aldi-nord")
            .fetch(RetailerRequest("80331"))
        org.junit.Assert.assertFalse(direct.noLocalMarket)
        org.junit.Assert.assertNotNull(ProviderImportPolicy.rejectionReason("aldi-nord", direct, 100))
        assertEquals(emptyList<String>(), direct.unavailableRetailerIds)
    }

    @Test fun `real undated dm shape does not turn JSON null into an invisible date or fake image`() = runTest {
        server.enqueue(MockResponse().setBody("""{"offers":[{"offer_id":"dm:3061034","retailer":"dm","product":"Seifendose stapelbar, 1 St","regular_price":1.95,"valid_from":null,"valid_until":null,"brand":null,"image_url":null,"description":null,"pack_size":null,"pack":"1 Stück"}]}"""))
        val result = ServerProvider(server.url("/").toString(), "", OkHttpClient()).fetch(RetailerRequest("04109"))
        val offer = result.offers.single()
        assertNull(offer.validFrom); assertNull(offer.validUntil); assertNull(offer.imageUrl)
        assertEquals("1 Stück", offer.packSize)
        org.junit.Assert.assertTrue(de.lesecuritae.korbuino.OfferMatcher.isShown(offer.validFrom, offer.validUntil, "2026-11-10", false))
        assertEquals("", result.products.single().brand)
    }

    @Test fun `server preserves published crate bundle single price and deposit`() = runTest {
        server.enqueue(MockResponse().setBody("""{"offers":[{"offer_id":"holab:3","retailer":"HOL’AB!","product":"Vilsa Mineralwasser Glas","regular_price":4.49,"multi_buy_quantity":2,"multi_buy_total_price":8.98,"single_price":4.99,"minimum_quantity":2,"multi_buy_condition":"ab 2 Kisten","pack_size":"12x700ml","deposit":3.30}]}"""))
        val offer = ServerProvider(server.url("/").toString(), "", OkHttpClient()).fetch(RetailerRequest("26135")).offers.single()
        assertEquals(449, offer.priceCents); assertEquals(2, offer.multiBuyQuantity)
        assertEquals(898, offer.multiBuyTotalCents); assertEquals(499, offer.singlePriceCents)
        assertEquals(330, offer.depositCents); assertEquals("ab 2 Kisten", offer.multiBuyCondition)
    }

    @Test fun `server variants with equal names retain their individual brand and quantity`() = runTest {
        server.enqueue(MockResponse().setBody("""{"offers":[{"offer_id":"fixture:a","retailer":"Test","product":"Fixture same name","brand":"A","regular_price":1.99,"pack":"500 g"},{"offer_id":"fixture:b","retailer":"Test","product":"Fixture same name","brand":"B","regular_price":1.99,"pack":"1000 g"}]}"""))
        val result = ServerProvider(server.url("/").toString(), "", OkHttpClient()).fetch(RetailerRequest("04109"))
        assertEquals(2, result.products.size)
        assertEquals(setOf("A", "B"), result.products.map { it.brand }.toSet())
        assertEquals(2, result.offers.map { it.productId }.toSet().size)
    }

    @Test fun `server partial catalogues preserve offline data and typed absence reaches all supported retailers`() = runTest {
        server.enqueue(MockResponse().setBody("""{"incomplete_retailers":["Lidl"],"unavailable_retailers":["trinkgut","Globus"],"warnings":["fixture page timeout"],"offers":[{"offer_id":"x","retailer":"Lidl","product":"Fixture","regular_price":1.99}]}"""))
        val result = ServerProvider(server.url("/").toString(), "", OkHttpClient()).fetch(RetailerRequest("04109"))
        org.junit.Assert.assertTrue(result.preserveMissingOffers)
        org.junit.Assert.assertTrue(result.unavailableRetailerIds.containsAll(listOf("trinkgut", "Globus", "globus")))
        assertEquals(listOf("fixture page timeout"), result.sourceWarnings)
    }

    @Test fun `server refuses missing repeated and excessive pagination instead of silently importing a partial list`() = runTest {
        for (second in listOf("""{"page_count":2,"offers":[]}""", """{"page_count":2,"offers":[{"offer_id":"first","product":"Fixture","regular_price":1.99}]}""")) {
            server.enqueue(MockResponse().setBody("""{"page_count":2,"offers":[{"offer_id":"first","product":"Fixture","regular_price":1.99}]}"""))
            server.enqueue(MockResponse().setBody(second))
            org.junit.Assert.assertTrue(runCatching { ServerProvider(server.url("/").toString(), "", OkHttpClient()).fetch(RetailerRequest("04109")) }.isFailure)
        }
        server.enqueue(MockResponse().setBody("""{"page_count":201,"offers":[]}"""))
        org.junit.Assert.assertTrue(runCatching { ServerProvider(server.url("/").toString(), "", OkHttpClient()).fetch(RetailerRequest("04109")) }.isFailure)
    }

    @Test fun `server cannot redirect its result request and bearer to another origin`() = runTest {
        MockWebServer().use { other ->
            other.start()
            server.enqueue(MockResponse().setBody("""{"result_url":"${other.url("/results/foreign")}"}"""))
            org.junit.Assert.assertTrue(runCatching { ServerProvider(server.url("/").toString(), "fixture-only", OkHttpClient()).fetch(RetailerRequest("04109")) }.isFailure)
            assertEquals(0, other.requestCount)
        }
    }

    @Test fun `server refuses a shrinking page count instead of losing the last advertised page`() = runTest {
        server.enqueue(MockResponse().setBody("""{"page":1,"page_count":3,"offers":[{"offer_id":"first","product":"Fixture A","regular_price":1.99}]}"""))
        server.enqueue(MockResponse().setBody("""{"page":2,"page_count":2,"offers":[{"offer_id":"second","product":"Fixture B","regular_price":1.99}]}"""))
        val result = runCatching { ServerProvider(server.url("/").toString(), "", OkHttpClient()).fetch(RetailerRequest("04109")) }
        org.junit.Assert.assertTrue(result.isFailure)
        org.junit.Assert.assertTrue(result.exceptionOrNull()!!.message!!.contains("Seitenzahl"))
        assertEquals(2, server.requestCount)
    }

    @Test fun `server retains pack-size-only variants and accepts genuinely absent GTINs`() = runTest {
        server.enqueue(MockResponse().setBody("""{"offers":[{"offer_id":"a","product":"Same fixture","regular_price":1.99,"pack_size":"500g","product_gtins":null},{"offer_id":"b","product":"Same fixture","regular_price":1.99,"pack_size":"1000g","product_gtins":null}]}"""))
        val result = ServerProvider(server.url("/").toString(), "", OkHttpClient()).fetch(RetailerRequest("04109"))
        assertEquals(2, result.products.size)
        assertEquals(2, result.offers.map { it.productId }.distinct().size)
        assertEquals(setOf("500g", "1000g"), result.offers.map { it.packSize }.toSet())
    }

    @Test fun `server mode actually requests the selected preview week`() = runTest {
        server.enqueue(MockResponse().setBody("""{"offers":[]}"""))
        ServerProvider(server.url("/").toString(), "", OkHttpClient()).fetch(RetailerRequest("04109", week = OfferWeek.NEXT))
        org.junit.Assert.assertTrue(server.takeRequest().body.readUtf8().contains("\"offer_week\":\"next\""))
    }

}
