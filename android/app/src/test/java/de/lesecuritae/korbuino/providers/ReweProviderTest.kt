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
import kotlinx.serialization.json.*
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.RecordedRequest

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

    @Test fun `forced next week without a preview container does not fabricate offers`() = runTest {
        // Monday: REWE has no preview, so ?week=next returns this week's catalogue.
        // Without a verified next-week container it must yield nothing (and the
        // caller falls back to the current week) instead of re-dating offers.
        server.enqueue(MockResponse().setBody("""
            <a href="/angebote/teststadt/123456/rewe-markt-hauptstrasse/">REWE Markt 12345 Teststadt</a>
        """))
        server.enqueue(MockResponse().setBody("""
            <div class="cor-offer-renderer-tile">
              <div class="cor-offer-information__title">Diese Woche</div>
              <span class="cor-offer-price__tag-price">1,29 €</span>
            </div>
        """))
        val provider = ReweProvider(
            OkHttpClient(), server.url("/").toString().trimEnd('/'),
            now = { Instant.parse("2026-09-14T10:00:00Z") }, // Monday
        )

        val failed = runCatching { provider.fetch(RetailerRequest("12345", citySlug = "teststadt", week = OfferWeek.NEXT)) }
        assertTrue(failed.isFailure)
    }

    @Test fun `forced next week honours a verified next-week container`() = runTest {
        server.enqueue(MockResponse().setBody("""
            <a href="/angebote/teststadt/123456/rewe-markt-hauptstrasse/">REWE Markt 12345 Teststadt</a>
        """))
        server.enqueue(MockResponse().setBody("""
            <div class="sos-categories-next" data-categories-week-value="next">
              <div class="cor-offer-renderer-tile">
                <div class="cor-offer-information__title">Nächste Woche</div>
                <span class="cor-offer-price__tag-price">0,99 €</span>
              </div>
            </div>
        """))
        val provider = ReweProvider(
            OkHttpClient(), server.url("/").toString().trimEnd('/'),
            now = { Instant.parse("2026-09-14T10:00:00Z") }, // Monday
        )

        val result = provider.fetch(RetailerRequest("12345", citySlug = "teststadt", week = OfferWeek.NEXT))
        assertEquals(1, result.offers.size)
        assertEquals("2026-09-21", result.offers.single().validFrom) // following Monday
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

    private fun capturedInclude() = Json.parseToJsonElement(javaClass.classLoader!!
        .getResourceAsStream("offer_coverage/rewe_public_include.json")!!.bufferedReader().use { it.readText() }).jsonObject

    private fun includeDispatcher(mode: String = "ok", reverse: Boolean = false): Dispatcher {
        val fixture = capturedInclude()
        fun field(key: String) = fixture.getValue(key).jsonPrimitive.content
        val market = field("market_id")
        val floating = field("rendered_card").replace("</article>", """<a data-offer-nan="${field("rendered_nan")}">Details</a></article>""")
        val wrappers = listOf(
            """<div data-offer-nan="${field("rendered_nan")}" data-offer-wwident="$market">${field("rendered_card")}</div>""",
            """<div data-offer-nan="${field("missing_nan")}" data-offer-wwident="${if (mode == "foreign-market") "99999" else market}"></div>""",
            """<div data-offer-nan="${field("rendered_nan")}" data-offer-wwident="$market"></div>""",
        ).let { if (reverse) it.reversed() else it }
        return object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when {
                request.path!!.startsWith("/marktsuche/") -> MockResponse().setBody("""<a href="/angebote/teststadt/$market/rewe-markt/">REWE 12345</a>""")
                request.path!!.startsWith("/angebote/") -> MockResponse().setBody(
                    """<div data-categories-week-value="current">${wrappers.joinToString("")}$floating</div><div data-categories-week-value="next">${field("included_card")}</div>""")
                request.path == "/api/frontend-includes" -> {
                    if (mode == "http") return MockResponse().setResponseCode(503)
                    if (mode == "missing") return MockResponse().setBody("[]")
                    val sent = Json.parseToJsonElement(request.body.readUtf8()).jsonArray
                    check(sent.size == 1)
                    check(sent.single().jsonObject["params"]!!.jsonObject["nan"]!!.jsonPrimitive.content == field("missing_nan"))
                    check(sent.single().jsonObject["query"]!!.jsonObject["wwIdent"]!!.jsonPrimitive.content == market)
                    val id = if (mode == "foreign-id") "unrequested" else sent.single().jsonObject["id"]!!.jsonPrimitive.content
                    MockResponse().setBody(buildJsonArray { add(buildJsonObject {
                        put("id", id); put("content", field("included_card"))
                    }) }.toString())
                }
                else -> MockResponse().setResponseCode(404)
            }
        }
    }

    @Test fun `official NAN placeholders are hydrated and market data wins over a larger aggregator`() = runTest {
        server.dispatcher = includeDispatcher()
        val fallback = object : RetailerProvider {
            override val id = "fallback"
            override val displayName = "unused"
            override suspend fun fetch(request: RetailerRequest): ProviderResult = error("must not call fallback")
        }
        val result = ReweProvider(OkHttpClient(), server.url("/").toString().trimEnd('/'), fallback,
            now = { Instant.parse("2026-11-10T12:00:00Z") }).fetch(RetailerRequest("12345", "teststadt"))
        assertTrue(result.paginationComplete)
        assertEquals("1940016", result.storeId)
        assertEquals(listOf(119, 379), result.offers.map { it.priceCents }.sorted())
        assertEquals(15, result.offers.single { it.priceCents == 119 }.depositCents)
        assertEquals(2, result.products.size)
        assertEquals(2, result.offers.map { it.id }.distinct().size)
        assertTrue(result.offers.all { it.validFrom == "2026-11-09" && it.validUntil == "2026-11-15" })
        assertEquals(3, server.requestCount)
    }

    @Test fun `missing HTTP and foreign response IDs never count as a complete official import`() = runTest {
        for (mode in listOf("http", "missing", "foreign-id", "foreign-market")) {
            server.dispatcher = includeDispatcher(mode)
            val provider = ReweProvider(OkHttpClient(), server.url("/").toString().trimEnd('/'), regionalSource(5),
                now = { Instant.parse("2026-11-10T12:00:00Z") })
            val result = provider.fetch(RetailerRequest("12345", "teststadt"))
            assertEquals(5, result.offers.size)
            assertTrue(!result.paginationComplete)
            assertTrue(result.sourceWarnings.any { it.contains("Filialgeltung") })
            assertTrue(result.preserveMissingOffers)
        }
    }

    @Test fun `official identities survive reordered wrappers and duplicated categories`() = runTest {
        suspend fun read(reverse: Boolean): ProviderResult {
            server.dispatcher = includeDispatcher(reverse = reverse)
            return ReweProvider(OkHttpClient(), server.url("/").toString().trimEnd('/'),
                now = { Instant.parse("2026-11-10T12:00:00Z") }).fetch(RetailerRequest("12345", "teststadt"))
        }
        val first = read(false)
        val reordered = read(true)
        assertEquals(first.offers.map { it.id }.toSet(), reordered.offers.map { it.id }.toSet())
        assertEquals(first.products.map { it.id }.toSet(), reordered.products.map { it.id }.toSet())
    }

    @Test fun `optional full captured official catalogue hydrates all public cards`() = runTest {
        val path = System.getenv("KORBUINO_REWE_HYDRATION_CAPTURE")
        org.junit.Assume.assumeTrue(!path.isNullOrBlank())
        val capture = Json.parseToJsonElement(java.io.File(path!!).readText()).jsonObject
        val market = capture.getValue("market").jsonPrimitive.content
        val cards = capture.getValue("cards").jsonObject
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when {
                request.path!!.startsWith("/marktsuche/") -> MockResponse().setBody("""<a href="/angebote/teststadt/$market/rewe-markt/">REWE 12345</a>""")
                request.path!!.startsWith("/angebote/") -> MockResponse().setBody(capture.getValue("html").jsonPrimitive.content)
                request.path == "/api/frontend-includes" -> MockResponse().setBody(buildJsonArray {
                    Json.parseToJsonElement(request.body.readUtf8()).jsonArray.forEach { raw ->
                        val row = raw.jsonObject
                        val nan = row.getValue("params").jsonObject.getValue("nan").jsonPrimitive.content
                        add(buildJsonObject {
                            put("id", row.getValue("id")); put("content", cards.getValue(nan))
                        })
                    }
                }.toString())
                else -> MockResponse().setResponseCode(404)
            }
        }
        val result = ReweProvider(OkHttpClient(), server.url("/").toString().trimEnd('/'),
            now = { Instant.parse("2026-11-10T12:00:00Z") }).fetch(RetailerRequest("12345", "teststadt"))
        assertEquals(188, cards.size)
        assertEquals(184, result.offers.size)
        assertTrue(result.sourceWarnings.toString(), result.paginationComplete)
        assertTrue(result.products.any { it.name.contains("Landliebe") })
    }
}
