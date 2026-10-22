package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.TimeUnit

class RetailerMarketsTest {
    private val north = """<script id="__NEXT_DATA__">{"props":{"pageProps":{"apiData":[["STORE_UBERALL_LOCATIONS_GET",{"res":{"status":"SUCCESS","response":{"locations":[
        {"name":"ALDI Nord","country":"DE","zip":"04205","lat":51.32,"lng":12.29},
        {"name":"ALDI Nord","country":"DE","zip":"51645","lat":51.03,"lng":7.57}
    ]}}}]]}}}</script>"""
    private val south = """{"status":"SUCCESS","response":{"locations":[
        {"name":"ALDI SÜD München","country":"DE","zip":"80335","lat":48.14,"lng":11.56},
        {"name":"ALDI SÜD Gummersbach","country":"DE","zip":"51647","lat":51.02,"lng":7.56}
    ]}}"""
    private val client = OkHttpClient.Builder().readTimeout(2, TimeUnit.SECONDS).build()

    private fun server(): MockWebServer = MockWebServer().apply {
        dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when (request.requestUrl!!.encodedPath) {
                "/north" -> MockResponse().setBody(north)
                "/south" -> MockResponse().setBody(south)
                "/geo" -> when (val code = request.requestUrl!!.queryParameter("postalcode")) {
                    "80331" -> MockResponse().setBody("""[{"lat":"48.1359","lon":"11.5731","address":{"postcode":"$code","country_code":"de"}}]""")
                    "51643" -> MockResponse().setBody("""[{"lat":"51.02","lon":"7.56","address":{"postcode":"$code","country_code":"de"}}]""")
                    else -> MockResponse().setBody("[]")
                }
                else -> MockResponse().setResponseCode(404)
            }
        }
    }

    private fun markets(server: MockWebServer) = AldiMarkets(client, server.url("/north").toString(),
        server.url("/south").toString(), server.url("/geo").toString())

    @Test fun munichHasSouthButNotNorthEvenWithoutAStoreInTheExactPostalCode() = runBlocking {
        server().use { s ->
            val markets = markets(s)
            assertFalse(markets.hasMarket("80331", "nord"))
            assertTrue(markets.hasMarket("80331", "sued"))
            assertEquals(3, s.requestCount)
            s.takeRequest(); s.takeRequest()
            val request = s.takeRequest()
            assertEquals("80331", request.requestUrl!!.queryParameter("postalcode"))
            assertEquals("de", request.requestUrl!!.queryParameter("countrycodes"))
            assertTrue(request.getHeader("User-Agent")!!.startsWith("Korbuino/"))
        }
    }

    @Test fun leipzigHasNorthButNotSouthAndNeedsNoExtraGeocoding() = runBlocking {
        server().use { s ->
            val markets = markets(s)
            assertTrue(markets.hasMarket("04205", "nord"))
            assertFalse(markets.hasMarket("04205", "sued"))
            assertEquals(2, s.requestCount)
        }
    }

    @Test fun borderAreasKeepBothChains() = runBlocking {
        server().use { s ->
            val markets = markets(s)
            assertTrue(markets.hasMarket("51643", "nord"))
            assertTrue(markets.hasMarket("51643", "sued"))
        }
    }

    @Test fun brokenStoreListsAndUnknownPostalCoordinatesRemainFailures() = runBlocking {
        server().use { s -> assertTrue(runCatching { markets(s).hasMarket("00000", "sued") }.isFailure) }
        MockWebServer().use { s ->
            s.enqueue(MockResponse().setResponseCode(503))
            assertTrue(runCatching { markets(s).hasMarket("80331", "nord") }.isFailure)
        }
        MockWebServer().use { s ->
            s.enqueue(MockResponse().setBody("<html>format changed</html>"))
            assertTrue(runCatching { markets(s).hasMarket("80331", "nord") }.isFailure)
        }
    }

    @Test fun irmaRequiresAnActualSupermarketWithTheRequestedPostalCode() = runBlocking {
        MockWebServer().use { s ->
            val markets = AktivIrmaMarkets(client, s.url("/").toString())
            s.enqueue(MockResponse().setBody("[]"))
            assertFalse(markets.hasMarket("80331"))
            s.enqueue(MockResponse().setBody("""[{"standort_art":"verwaltung","standort_plz":"26127"},{"standort_art":"aktivirma","standort_plz":"26127"}]"""))
            assertTrue(markets.hasMarket("26127"))
            s.enqueue(MockResponse().setBody("""[{"standort_art":"plopp","standort_plz":"80331"},{"standort_art":"aktivirma","standort_plz":"26127"}]"""))
            assertFalse(markets.hasMarket("80331"))
            assertEquals("80331", s.takeRequest().requestUrl!!.queryParameter("q"))
        }
    }

    @Test fun irmaMalformedOrFailedLookupIsNotMarketAbsence() = runBlocking {
        MockWebServer().use { s ->
            val markets = AktivIrmaMarkets(client, s.url("/").toString())
            listOf("{}", "[{\"standort_art\":null,\"standort_plz\":80331}]", "<html>error</html>").forEach { body ->
                s.enqueue(MockResponse().setBody(body))
                assertTrue(runCatching { markets.hasMarket("80331") }.isFailure)
            }
            s.enqueue(MockResponse().setResponseCode(503))
            assertTrue(runCatching { markets.hasMarket("80331") }.isFailure)
        }
    }
    @Test fun irmaExplicitNotFoundResponseConfirmsAbsence() = runBlocking {
        MockWebServer().use { s ->
            s.enqueue(MockResponse().setBody("""{"error":"Kein Eintrag gefunden"}"""))
            assertFalse(AktivIrmaMarkets(client, s.url("/").toString()).hasMarket("80331"))
        }
    }

}
