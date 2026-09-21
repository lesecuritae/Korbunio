package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
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

class ReweProviderTest {
    private lateinit var server: MockWebServer

    @Before fun setUp() { server = MockWebServer().also { it.start() } }
    @After fun tearDown() { server.shutdown() }

    @Test fun `parses public market offer cards`() = runTest {
        server.enqueue(MockResponse().setBody("""
            <a href="/angebote/teststadt/123456/rewe-markt-hauptstrasse/">REWE Markt 12345 Teststadt</a>
        """))
        server.enqueue(MockResponse().setBody("""
            <div class="cor-offer-renderer-tile">
              <div class="cor-offer-information__title">Coca-Cola Zero 1,25 l</div>
              <span class="cor-offer-price__tag-price">1,29 €</span>
              <img src="/placeholder.svg" data-srcset="/small.jpg 320w, https://img.rewe-static.de/example.jpg 1200w" />
            </div>
        """))
        val provider = ReweProvider(OkHttpClient(), server.url("/").toString().trimEnd('/'))
        val result = provider.fetch(RetailerRequest("12345", citySlug = "teststadt"))
        assertEquals(1, result.offers.size)
        assertEquals(129, result.offers.single().priceCents)
        assertTrue(result.products.single().name.contains("Coca-Cola"))
        assertEquals("https://img.rewe-static.de/example.jpg", result.offers.single().imageUrl)
    }

    @Test fun `reads the published REWE Bonus amount and ignores unpriced app benefits`() = runTest {
        server.enqueue(MockResponse().setBody("""
            <a href="/angebote/teststadt/123456/rewe-markt-hauptstrasse/">REWE Markt 12345 Teststadt</a>
        """))
        server.enqueue(MockResponse().setBody("""
            <div class="cor-offer-renderer-tile">
              <div class="cor-offer-information__title">Milch 1 l</div>
              <span class="cor-offer-price__tag-price">1,09 €</span>
              <span class="cor-loyalty-badge">0,10 €</span>
            </div>
            <div class="cor-offer-renderer-tile">
              <div class="cor-offer-information__title">Butter 250 g</div>
              <div class="cor-offer-information__additional">MIT APP 0,20 € REWE BONUS</div>
              <span class="cor-offer-price__tag-price">1,79 €</span>
            </div>
            <div class="cor-offer-renderer-tile">
              <div class="cor-offer-information__title">Joghurt</div>
              <div class="cor-offer-information__additional">20 % REWE Bonus Punkte</div>
              <span class="cor-offer-price__tag-price">0,49 €</span>
            </div>
            <div class="cor-offer-renderer-tile">
              <div class="cor-offer-information__title">Brot</div>
              <span class="cor-offer-price__tag-price">2,29 €</span>
            </div>
        """))
        val provider = ReweProvider(OkHttpClient(), server.url("/").toString().trimEnd('/'))
        val offers = provider.fetch(RetailerRequest("12345", citySlug = "teststadt")).offers.associateBy { it.priceCents }
        assertEquals(10, offers.getValue(109).loyaltyCashbackCents)
        assertEquals("rewe_bonus", offers.getValue(109).loyaltyProgram)
        assertEquals("REWE Bonus", offers.getValue(109).loyaltyLabel)
        assertEquals(20, offers.getValue(179).loyaltyCashbackCents)
        assertEquals(null, offers.getValue(49).loyaltyCashbackCents)
        assertEquals(null, offers.getValue(229).loyaltyProgram)
        // Guthaben senkt den Preis nicht (wie im Server): der Regalpreis bleibt stehen.
        assertEquals(109, offers.getValue(109).priceCents)
    }

    @Test fun `rejects invalid postal code before network`() = runTest {
        val provider = ReweProvider(OkHttpClient(), server.url("/").toString().trimEnd('/'))
        try {
            provider.fetch(RetailerRequest("1234", citySlug = "teststadt"))
            error("expected validation error")
        } catch (error: IllegalArgumentException) {
            assertTrue(error.message.orEmpty().contains("PLZ"))
        }
        assertEquals(0, server.requestCount)
    }

    @Test fun `selects next week automatically on Sunday in Berlin`() = runTest {
        server.enqueue(MockResponse().setBody("""
            <a href="/angebote/teststadt/123456/rewe-markt-hauptstrasse/">REWE Markt 12345 Teststadt</a>
        """))
        server.enqueue(MockResponse().setBody("""
            <div class="cor-offer-renderer-tile">
              <div class="cor-offer-information__title">Montagsangebot</div>
              <span class="cor-offer-price__tag-price">1,29 €</span>
            </div>
        """))
        val provider = ReweProvider(
            OkHttpClient(), server.url("/").toString().trimEnd('/'),
            now = { Instant.parse("2026-09-13T10:00:00Z") },
        )

        val result = provider.fetch(RetailerRequest("12345", citySlug = "teststadt"))

        assertTrue(server.takeRequest().path.orEmpty().contains("marktsuche"))
        assertTrue(server.takeRequest().path.orEmpty().endsWith("?week=next"))
        assertEquals("2026-09-14", result.offers.single().validFrom)
    }

    @Test fun `uses regional fallback when direct page only exposes ten offers`() = runTest {
        server.enqueue(MockResponse().setBody("""
            <a href="/angebote/teststadt/123456/rewe-markt-hauptstrasse/">REWE Markt 12345 Teststadt</a>
        """))
        val cards = (1..10).joinToString("") { index ->
            """
            <div class="cor-offer-renderer-tile">
              <div class="cor-offer-information__title">Direkt $index</div>
              <span class="cor-offer-price__tag-price">1,29 €</span>
            </div>
            """
        }
        server.enqueue(MockResponse().setBody(cards))
        val fallback = object : RetailerProvider {
            override val id = "marktguru-rewe"
            override val displayName = "REWE (regional)"
            override suspend fun fetch(request: RetailerRequest) = ProviderResult(
                products = (1..11).map { ProductEntity("regional-product-$it", "Regionaler Treffer $it", normalizedKey = "regionaler-treffer-$it") },
                offers = (1..11).map { OfferEntity("regional-offer-$it", id, "regional-product-$it", externalId = "regional-$it", priceCents = 199, sourceUrl = "https://example.test", cachedAt = 1) },
            )
        }
        val provider = ReweProvider(OkHttpClient(), server.url("/").toString().trimEnd('/'), fallback)

        val result = provider.fetch(RetailerRequest("12345", citySlug = "teststadt"))

        assertEquals(11, result.offers.size)
        assertTrue(result.offers.all { it.retailerId == "rewe" })
    }

    private fun marketPage(cards: Int): List<MockResponse> = listOf(
        MockResponse().setBody("""<a href="/angebote/teststadt/123456/rewe-markt-hauptstrasse/">REWE Markt 12345 Teststadt</a>"""),
        MockResponse().setBody((1..cards).joinToString("") { index ->
            """
            <div class="cor-offer-renderer-tile">
              <div class="cor-offer-information__title">Direkt $index</div>
              <span class="cor-offer-price__tag-price">1,29 €</span>
            </div>
            """
        }),
    )

    private fun regionalSource(count: Int?) = object : RetailerProvider {
        override val id = "marktguru-rewe"
        override val displayName = "REWE (regional)"
        override suspend fun fetch(request: RetailerRequest): ProviderResult {
            if (count == null) error("regional nicht erreichbar")
            return ProviderResult(
                products = (1..count).map { ProductEntity("regional-product-$it", "Regionaler Treffer $it", normalizedKey = "regionaler-treffer-$it") },
                offers = (1..count).map { OfferEntity("regional-offer-$it", id, "regional-product-$it", externalId = "regional-$it", priceCents = 199, sourceUrl = "https://example.test", cachedAt = 1) },
            )
        }
    }

    @Test fun `a market page with eleven offers does not hide the full regional list`() = runTest {
        // Reported by a user: the page showed 11 of about 200 offers.
        marketPage(11).forEach(server::enqueue)
        val provider = ReweProvider(OkHttpClient(), server.url("/").toString().trimEnd('/'), regionalSource(200))

        val result = provider.fetch(RetailerRequest("12345", citySlug = "teststadt"))

        assertEquals(200, result.offers.size)
        assertTrue(result.offers.all { it.retailerId == "rewe" })
    }

    @Test fun `the market page wins when it has more offers than the regional source`() = runTest {
        marketPage(30).forEach(server::enqueue)
        val provider = ReweProvider(OkHttpClient(), server.url("/").toString().trimEnd('/'), regionalSource(12))

        assertEquals(30, provider.fetch(RetailerRequest("12345", citySlug = "teststadt")).offers.size)
    }

    @Test fun `the market page is used when the regional source fails`() = runTest {
        marketPage(11).forEach(server::enqueue)
        val provider = ReweProvider(OkHttpClient(), server.url("/").toString().trimEnd('/'), regionalSource(null))

        assertEquals(11, provider.fetch(RetailerRequest("12345", citySlug = "teststadt")).offers.size)
    }
}
