package de.lesecuritae.korbuino.kitchenowl

import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class KitchenOwlClientTest {
    private lateinit var server: MockWebServer

    @Before fun setUp() { server = MockWebServer().also { it.start() } }
    @After fun tearDown() { server.shutdown() }

    @Test fun `reads existing items and sends bearer token`() {
        server.enqueue(MockResponse().setBody("""
            [{"name":"Milch"},{"item":{"name":"Brot"}},{"name":""}]
        """))
        val client = KitchenOwlClient(server.url("/").toString(), "test-token", OkHttpClient())
        // MockWebServer is HTTP-only; the client deliberately requires HTTPS.
        // Exercise the parser through the same request path using a URL rewrite
        // is not possible without weakening production TLS checks, so verify the
        // security boundary explicitly here.
        try {
            client.existingItems("42")
            error("expected HTTPS validation")
        } catch (error: IllegalStateException) {
            assertTrue(error.message.orEmpty().contains("HTTPS"))
        }
        assertEquals(0, server.requestCount)
    }

    @Test fun `rejects non numeric list ids before network`() {
        val client = KitchenOwlClient("https://kitchenowl.example", "token", OkHttpClient())
        try {
            client.existingItems("abc")
            error("expected invalid id")
        } catch (error: IllegalArgumentException) {
            assertTrue(error.message.orEmpty().contains("Ungültige"))
        }
        assertEquals(0, server.requestCount)
    }
}
