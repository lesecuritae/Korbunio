package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

class DmProviderTest {
    private lateinit var server: MockWebServer
    @Before fun setUp() { server = MockWebServer().also { it.start() } }
    @After fun tearDown() { server.shutdown() }

    @Test fun `parses only explicitly marked clearance products`() = runTest {
        server.enqueue(MockResponse().setBody("""
            {"products":[
              {"id":"p1","title":"Shampoo 250 ml","brandName":"Test","tileData":{"eyecatchers":[{"alt":"Ausverkauf"}],"price":{"price":{"current":{"value":"1,29"}}},"images":[{"url":"https://cdn.example/shampoo.jpg"}]}},
              {"id":"p2","title":"Normal","tileData":{"eyecatchers":[],"price":{"price":{"current":{"value":"2,99"}}}}}
            ]}
        """))
        val provider = DmProvider(OkHttpClient(), server.url("/search").toString())
        val result = provider.fetch(RetailerRequest("12345"))
        assertEquals(1, result.offers.size)
        assertEquals(129, result.offers.single().priceCents)
    }
}
