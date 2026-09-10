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

    @Test fun `regional Netto identity and cent prices are retained`() = runTest {
        server.enqueue(MockResponse().setBody("<script>{\"apiKey\":\"a\",\"clientKey\":\"c\"}</script>"))
        server.enqueue(MockResponse().setBody("""
            {"results":[
              {"id":"kiwi","product":{"name":"Kiwi lose","imageUrl":"https://cdn.example/kiwi.webp"},"price":"0,99","description":"HINWEIS: MIT NETTO PLUS APP 0.79 € Stück"},
              {"id":"milk","product":{"name":"Milch 1 l"},"price":"1,49"},
              {"id":"pack","product":{"name":"Mehrfachpackung"},"price":"12,99"}
            ]}
        """))
        val provider = MarktguruProvider(
            "Netto Marken-Discount",
            OkHttpClient(),
            server.url("/home").toString(),
            server.url("/search").toString(),
            providerId = "netto-marken",
            providerDisplayName = "Netto Marken-Discount",
        )

        val result = provider.fetch(RetailerRequest("26122"))

        assertEquals("netto-marken", provider.id)
        assertEquals(listOf(99, 149, 1299), result.offers.map { it.priceCents })
        assertTrue(result.offers.all { it.retailerId == "netto-marken" })
        assertEquals("https://cdn.example/kiwi.webp", result.offers.first().imageUrl)
        assertEquals("netto_plus", result.offers.first().loyaltyProgram)
        assertEquals("Netto Plus App", result.offers.first().loyaltyLabel)
        assertEquals(79, result.offers.first().loyaltyPriceCents)
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

    @Test fun `does not parse package volume as Lidl Plus price`() = runTest {
        server.enqueue(MockResponse().setBody("<script>{\"apiKey\":\"a\",\"clientKey\":\"c\"}</script>"))
        server.enqueue(MockResponse().setBody("""
            {"results":[{
              "id":"wine",
              "product":{"name":"Handverlesen Riesling"},
              "price":6.99,
              "requiresLoyalityMembership":true,
              "description":"HINWEIS: MIT LIDL PLUS APP Weißwein, halbtrocken, je 0,75 l Normalpreis: 7.99"
            }]}
        """))
        val result = MarktguruProvider(
            "Lidl",
            OkHttpClient(),
            server.url("/home").toString(),
            server.url("/search").toString(),
        ).fetch(RetailerRequest("26122"))

        assertEquals(799, result.offers.single().priceCents)
        assertEquals("lidl_plus", result.offers.single().loyaltyProgram)
        assertEquals(699, result.offers.single().loyaltyPriceCents)
    }

    @Test fun `does not invent loyalty price when only package volume is present`() = runTest {
        server.enqueue(MockResponse().setBody("<script>{\"apiKey\":\"a\",\"clientKey\":\"c\"}</script>"))
        server.enqueue(MockResponse().setBody("""
            {"results":[{
              "id":"wine",
              "product":{"name":"Lugana"},
              "price":7.49,
              "requiresLoyalityMembership":true,
              "description":"HINWEIS: MIT LIDL PLUS APP DOP, Weißwein, trocken, je 0,75 l"
            }]}
        """))
        val result = MarktguruProvider(
            "Lidl",
            OkHttpClient(),
            server.url("/home").toString(),
            server.url("/search").toString(),
        ).fetch(RetailerRequest("26122"))

        assertEquals(749, result.offers.single().priceCents)
        assertEquals(null, result.offers.single().loyaltyProgram)
        assertEquals(null, result.offers.single().loyaltyPriceCents)
    }

    @Test fun `rejects unrelated advertisers returned by regional search`() = runTest {
        server.enqueue(MockResponse().setBody("<script>{\"apiKey\":\"a\",\"clientKey\":\"c\"}</script>"))
        server.enqueue(MockResponse().setBody("""
            {"results":[
              {"id":"right","advertisers":[{"uniqueName":"combi"}],"product":{"name":"Combi Brot"},"price":1.49},
              {"id":"wrong","advertisers":[{"uniqueName":"lidl"}],"product":{"name":"Fremdes Brot"},"price":0.69}
            ]}
        """))
        val result = MarktguruProvider(
            "Combi",
            OkHttpClient(),
            server.url("/home").toString(),
            server.url("/search").toString(),
        ).fetch(RetailerRequest("26122"))

        assertEquals(listOf("Combi Brot"), result.products.map { it.name })
        assertEquals(149, result.offers.single().priceCents)
    }
}
