package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
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

    @Test fun `keeps dot decimal prices and resolves image metadata`() = runTest {
        server.enqueue(MockResponse().setBody("<script>{\"apiKey\":\"a\",\"clientKey\":\"c\"}</script>"))
        server.enqueue(MockResponse().setBody("""
            {"results":[{"id":"24731503","imageType":"offer","images":{"count":1,"metadata":[{"aspectRatio":1.0}]},"product":{"name":"Apple iPhone 17 Salbei"},"price":"2.76"}]}
        """))
        val provider = MarktguruProvider("Netto Marken-Discount", OkHttpClient(), server.url("/home").toString(), server.url("/search").toString())
        val result = provider.fetch(RetailerRequest("12345"))
        assertEquals(276, result.offers.single().priceCents)
        assertEquals("https://mg2de.b-cdn.net/api/v1/offers/24731503/images/default/0/medium.jpg", result.offers.single().imageUrl)
    }

    @Test fun `follows all result pages instead of stopping at the first hundred`() = runTest {
        server.enqueue(MockResponse().setBody("<script>{\"apiKey\":\"a\",\"clientKey\":\"c\"}</script>"))
        val firstPage = (1..100).joinToString(",") { index ->
            "{\"id\":\"page-one-$index\",\"product\":{\"name\":\"Produkt $index\"},\"price\":\"1,00\"}"
        }
        server.enqueue(MockResponse().setBody("{\"totalResults\":101,\"results\":[$firstPage]}"))
        server.enqueue(MockResponse().setBody("{\"totalResults\":101,\"results\":[{\"id\":\"page-two\",\"product\":{\"name\":\"Letztes Produkt\"},\"price\":\"2,00\"}]}"))

        val provider = MarktguruProvider("REWE", OkHttpClient(), server.url("/home").toString(), server.url("/search").toString())
        val result = provider.fetch(RetailerRequest("12345"))

        assertEquals(101, result.offers.size)
        assertTrue(server.takeRequest().path!!.endsWith("/home"))
        assertEquals("/search?as=web&limit=100&offset=0&q=REWE&zipCode=12345", server.takeRequest().path)
        assertEquals("/search?as=web&limit=100&offset=100&q=REWE&zipCode=12345", server.takeRequest().path)
    }
}
