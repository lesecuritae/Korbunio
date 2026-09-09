package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

class MarktguruProviderTest {
    private lateinit var server: MockWebServer

    @Before fun setUp() { server = MockWebServer().also { it.start() } }
    @After fun tearDown() { server.shutdown() }

    @Test fun `discovers public keys and parses regional result`() = runTest {
        server.enqueue(MockResponse().setBody("<script>{\"apiKey\":\"a\",\"clientKey\":\"c\"}</script>"))
        server.enqueue(MockResponse().setBody("""
            {"results":[{"id":"o1","product":{"name":"Milch 1 l","imageUrl":"https://cdn.example/milch.jpg"},"price":"0,99"}]}
        """))
        val provider = MarktguruProvider("REWE", OkHttpClient(), server.url("/home").toString(), server.url("/search").toString())
        val result = provider.fetch(RetailerRequest("12345"))
        assertEquals(1, result.offers.size)
        assertEquals(99, result.offers.single().priceCents)
        server.takeRequest()
        assertEquals("a", server.takeRequest().getHeader("x-apikey"))
    }
}
