package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

class ServerProviderTest {
    private lateinit var server: MockWebServer

    @Before fun setUp() { server = MockWebServer().also { it.start() } }
    @After fun tearDown() { server.shutdown() }

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
