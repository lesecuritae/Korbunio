package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.*
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class RossmannStockClientTest {
    private lateinit var server: MockWebServer
    private val fixture get() = javaClass.classLoader!!.getResource("availability/rossmann.json")!!.readText()
    private var ticks = 0L
    private val pauses = mutableListOf<Long>()
    @Before fun setup() { server = MockWebServer().also { it.start() } }
    @After fun teardown() { server.shutdown() }
    private fun client() = RossmannStockClient(OkHttpClient(), server.url("/stores").toString(),
        server.url("/geocode").toString(), { ticks }, { pauses.add(it); ticks += it })
    private fun geocode() = server.enqueue(MockResponse().setBody("""[{"lat":"51.3","lon":"12.3","address":{"country_code":"de","postcode":"12345"}}]"""))

    @Test fun `zero is out of stock even if available true and five plus is a bound`() {
        val rows = RossmannStockClient.parse(Json.parseToJsonElement(fixture), "120585")
        assertEquals(5, rows[0].minimum); assertFalse(rows[0].exact)
        assertEquals(false, rows[1].inStock)
        assertNull(rows[2].inStock)
    }
    @Test fun `wrong product is an error not zero`() {
        assertThrows(IllegalStateException::class.java) {
            RossmannStockClient.parse(Json.parseToJsonElement(fixture), "195333")
        }
    }
    @Test fun `zero lower bound does not prove sold out`() {
        assertNull(StockStore("101", "Teststadt", "Testweg", "12345", "0+", 0, false).inStock)
    }
    @Test fun `deduplicates uses own agent and caches without app credentials`() = runTest {
        geocode(); server.enqueue(MockResponse().setBody(fixture))
        val client = client()
        val first = client.check("12345", listOf("120585", "120585"))
        val second = client.check("12345", listOf("120585"))
        assertEquals(1, first.size); assertTrue(second.single().fromCache)
        assertEquals(2, server.requestCount); assertEquals(listOf(2000L), pauses)
        server.takeRequest()
        val request = server.takeRequest()
        assertEquals("120585", request.requestUrl!!.queryParameter("dan"))
        assertEquals(RossmannStockClient.USER_AGENT, request.getHeader("User-Agent"))
        assertNull(request.getHeader("Authorization")); assertNull(request.getHeader("Cookie"))
        assertNull(request.getHeader("x-api-key")); assertNull(request.getHeader("Android-Id"))
    }
    @Test fun `406 preserves per product failure and does not destroy successful cache`() = runTest {
        geocode(); server.enqueue(MockResponse().setBody(fixture)); server.enqueue(MockResponse().setResponseCode(406))
        val client = client();val result = client.check("12345", listOf("120585", "195333"))
        assertNull(result[0].error); assertTrue(result[1].error!!.contains("406"))
        assertTrue(result[1].stores.isEmpty())
        assertTrue(client.check("12345", listOf("120585")).single().fromCache)
    }
    @Test fun `unconfirmed postal area never sends product request`() = runTest {
        server.enqueue(MockResponse().setBody("""[{"lat":"51.3","lon":"12.3","address":{"country_code":"de","postcode":"99999"}}]"""))
        try { client().check("12345", listOf("120585")); fail("must refuse wrong postal area") }
        catch (_: IllegalStateException) { assertEquals(1, server.requestCount) }
    }
    @Test fun `redirect is not followed`() = runTest {
        geocode(); server.enqueue(MockResponse().setResponseCode(302).addHeader("Location", server.url("/unexpected")))
        val result = client().check("12345", listOf("120585"))
        assertTrue(result.single().error!!.contains("302")); assertEquals(2, server.requestCount)
    }
    @Test fun `invalid input is rejected before network`() = runTest {
        try { client().check("12345", List(6) { "120585" }); fail("must bound requests") }
        catch (_: IllegalArgumentException) { assertEquals(0, server.requestCount) }
    }
}
