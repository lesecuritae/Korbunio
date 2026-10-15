package de.lesecuritae.korbuino.notifications

import de.lesecuritae.korbuino.providers.*
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import java.time.LocalDate

class UpcomingProviderTest {
    @Test fun marktguruNextUsesRealPublishedDatesAcrossYearBoundary() = runTest {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(MockResponse().setBody("<script>{\"apiKey\":\"a\",\"clientKey\":\"c\"}</script>"))
            server.enqueue(MockResponse().setBody("""{"results":[
                {"id":"current","product":{"name":"Aktuell"},"price":"1.00","validityDates":[{"from":"2026-12-28","to":"2027-01-03"}]},
                {"id":"next","product":{"name":"Vorschau"},"price":"2.00","validityDates":[{"from":"2027-01-04","to":"2027-01-10"}]},
                {"id":"undated","product":{"name":"Ohne Datum"},"price":"3.00"}
            ]}"""))
            val result = MarktguruProvider("REWE",OkHttpClient(),server.url("/home").toString(),server.url("/search").toString(),
                now = { Instant.parse("2026-12-31T12:00:00Z") }).fetch(RetailerRequest("12345",week=OfferWeek.NEXT))
            assertEquals(listOf("Vorschau"),result.products.map { it.name })
            assertEquals("2027-01-04",result.offers.single().validFrom)
            assertEquals(200,result.offers.single().priceCents)
        }
    }
    @Test fun aldiNextRequiresDatedPromotionalPriceAndPreservesSourceValidity() = runTest {
        MockWebServer().use { server ->
            server.start()
            val payload = """{"props":{"pageProps":{"apiData":[["OFFER_GET",{"res":{
                "categories":[{"startDate":"2027-01-04","endDate":"2027-01-09","content":[{"title":"Vorschau","productIds":["dated","undated"]}]}],
                "algoliaDataMap":{
                    "dated":{"name":"Verifiziert","promotionPrices":[{"priceValue":1.49,"validFromLocalDate":"2027-01-04","validUntilLocalDate":"2027-01-09"}]},
                    "undated":{"name":"Unbelegt","currentPrice":{"priceValue":0.49}}
                }
            }}]]}}}"""
            server.enqueue(MockResponse().setBody("<script id=\"__NEXT_DATA__\">$payload</script>"))
            val result = AldiNordProvider(OkHttpClient(),server.url("/offers").toString(),
                today = { LocalDate.parse("2026-12-31") }).fetch(RetailerRequest("12345",week=OfferWeek.NEXT))
            assertEquals(listOf("Verifiziert"),result.products.map { it.name })
            assertEquals("2027-01-04",result.offers.single().validFrom)
            assertEquals(149,result.offers.single().priceCents)
        }
    }
}
