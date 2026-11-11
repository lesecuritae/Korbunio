package de.lesecuritae.korbuino.providers

import java.io.File
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test

class NettoScottieMarketsTest {
    private fun catalogue() = javaClass.classLoader!!.getResourceAsStream("offer_coverage/netto_black_stores.html")!!.bufferedReader().use { it.readText() }
    private fun geo(postal: String, lat: String = "52.53", lon: String = "13.38", country: String = "de") =
        """[{"lat":"$lat","lon":"$lon","address":{"postcode":"$postal","country_code":"$country"}}]"""

    @Test fun `exact published postal code needs no invented point and reuses the bounded catalogue cache`() = runTest {
        MockWebServer().use { server ->
            server.start(); server.enqueue(MockResponse().setBody(catalogue()))
            val markets = NettoScottieMarkets(OkHttpClient(), server.url("/stores").toString(), server.url("/geo").toString())
            assertTrue(markets.hasMarket("13353"))
            assertTrue(markets.hasMarket("13353"))
            assertEquals(1, server.requestCount)
        }
    }

    @Test fun `a verified distant postal area blocks both direct offers and aggregator fallback`() = runTest {
        MockWebServer().use { server ->
            server.start(); server.enqueue(MockResponse().setBody(catalogue()))
            server.enqueue(MockResponse().setBody(geo("26135", "53.1367", "8.21653")))
            val markets = NettoScottieMarkets(OkHttpClient(), server.url("/stores").toString(), server.url("/geo").toString())
            var calls = 0
            val inner = object : RetailerProvider {
                override val id = "netto-schwarz"; override val displayName = "Netto schwarz"
                override suspend fun fetch(request: RetailerRequest): ProviderResult { calls++; error("No worker may be called for confirmed absence") }
            }
            val gate = MarketGateProvider(inner, hasMarket = markets::hasMarket)
            assertTrue(gate.fetch(RetailerRequest("26135")).noLocalMarket)
            assertTrue(gate.fetch(RetailerRequest("26135")).noLocalMarket)
            assertEquals(0, calls)
            assertEquals(2, server.requestCount)
        }
    }

    @Test fun `a wrong country or postal response is an error and is not cached as absence`() = runTest {
        for (invalid in listOf(geo("80331"), geo("10115", country = "at"), geo("10115", lat = "NaN"))) MockWebServer().use { server ->
            server.start(); server.enqueue(MockResponse().setBody(catalogue()))
            server.enqueue(MockResponse().setBody(invalid))
            server.enqueue(MockResponse().setBody(geo("10115")))
            var time = 0L
            val markets = NettoScottieMarkets(OkHttpClient(), server.url("/stores").toString(), server.url("/geo").toString(), now = { time += 2_000; time })
            assertTrue(runCatching { markets.hasMarket("10115") }.isFailure)
            assertTrue(markets.hasMarket("10115"))
            assertEquals(3, server.requestCount)
        }
    }

    @Test fun `changed or empty authoritative catalogue never proves local absence`() = runTest {
        val empty = "<script>self.__next_f.push(" + JsonArray(listOf(JsonPrimitive(1), JsonPrimitive("1:{\"initialStores\":[]}\n"))) + ")</script>"
        for (body in listOf("<html>changed</html>", empty, catalogue().replace("initialStores", "nearbyStores"))) {
            MockWebServer().use { server ->
                server.start(); server.enqueue(MockResponse().setBody(body))
                val markets = NettoScottieMarkets(OkHttpClient(), server.url("/stores").toString(), server.url("/geo").toString())
                assertTrue(runCatching { markets.hasMarket("26135") }.isFailure)
                assertEquals(1, server.requestCount)
            }
        }
    }

    @Test fun `optional captured complete official catalogue supports Berlin and excludes Oldenburg`() = runTest {
        val file = System.getenv("KORBUINO_NETTO_STORES_HTML")
        assumeTrue("Operator-supplied offline replay of the complete public catalogue", !file.isNullOrBlank())
        val html = File(file!!).readText()
        for ((postal, lat, lon, expected) in listOf(listOf("10115", "52.53", "13.38", "true"), listOf("26135", "53.1367", "8.21653", "false"))) {
            MockWebServer().use { server ->
                server.start(); server.enqueue(MockResponse().setBody(html))
                server.enqueue(MockResponse().setBody(geo(postal, lat, lon)))
                assertEquals(expected.toBoolean(), NettoScottieMarkets(OkHttpClient(), server.url("/stores").toString(), server.url("/geo").toString()).hasMarket(postal))
            }
        }
    }
}
