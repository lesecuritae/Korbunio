package de.lesecuritae.korbuino.grocy

import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/** In-memory Grocy 4.7 behaviour (shapes verified against a real instance) behind MockWebServer on loopback. */
class GrocyClientTest {
    private val key = "k".repeat(48)
    private lateinit var server: MockWebServer
    private val products = linkedMapOf<Int, String>()
    private val rows = linkedMapOf<Int, MutableMap<String, String>>()
    private var nextId = 1
    private val seenKeys = mutableListOf<String?>()
    private val seenPaths = mutableListOf<String>()
    private var dropNextCreate = false

    @Before fun setUp() {
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                seenKeys += request.getHeader("GROCY-API-KEY"); seenPaths += request.path.orEmpty()
                if (request.getHeader("GROCY-API-KEY") != key) return MockResponse().setResponseCode(401).setBody("""{"error_message":"Unauthorized"}""")
                val path = request.path.orEmpty().substringBefore('?')
                val body = request.body.readUtf8()
                return when {
                    path == "/api/system/info" -> ok("""{"grocy_version":{"Version":"4.7.1"}}""")
                    path == "/api/objects/shopping_lists" -> ok("""[{"id":"1","name":"Shopping list"},{"id":"2","name":"Other"}]""")
                    path == "/api/objects/locations" -> ok("""[{"id":"2","name":"Fridge"}]""")
                    path == "/api/objects/quantity_units" -> ok("""[{"id":"2","name":"Piece"},{"id":"3","name":"Pack"}]""")
                    path == "/api/objects/products" && request.method == "GET" ->
                        ok(products.entries.joinToString(",", "[", "]") { """{"id":"${it.key}","name":"${it.value}"}""" })
                    path == "/api/objects/products" && request.method == "POST" -> {
                        val id = nextId++; products[id] = obj(body)["name"]!!.jsonPrimitive.content; ok("""{"created_object_id":"$id"}""")
                    }
                    path.startsWith("/api/objects/products/") -> {
                        val id = path.substringAfterLast('/').toIntOrNull()
                        if (id == null || id !in products) notFound() else ok("""{"id":"$id","name":"${products[id]}"}""")
                    }
                    path == "/api/objects/shopping_list" && request.method == "GET" ->
                        ok(rows.values.joinToString(",", "[", "]") { r -> r.entries.joinToString(",", "{", "}") { """"${it.key}":"${it.value}"""" } })
                    path == "/api/objects/shopping_list" && request.method == "POST" -> {
                        val j = obj(body); val id = nextId++
                        rows[id] = mutableMapOf("id" to "$id", "product_id" to j.str("product_id"), "note" to j.str("note"),
                            "amount" to j.str("amount"), "shopping_list_id" to j.str("shopping_list_id"), "done" to "0")
                        if (dropNextCreate) { dropNextCreate = false; MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AFTER_REQUEST) }
                        else ok("""{"created_object_id":"$id"}""")
                    }
                    path.startsWith("/api/objects/shopping_list/") -> {
                        val id = path.substringAfterLast('/').toIntOrNull()
                        when {
                            request.method == "GET" -> if (id != null && id in rows) ok(rows[id]!!.entries.joinToString(",", "{", "}") { """"${it.key}":"${it.value}"""" }) else notFound()
                            request.method == "DELETE" -> if (id != null && rows.remove(id) != null) MockResponse().setResponseCode(204) else MockResponse().setResponseCode(400).setBody("""{"error_message":"Object not found"}""")
                            else -> MockResponse().setResponseCode(405)
                        }
                    }
                    else -> MockResponse().setResponseCode(400)
                }
            }
        }
        server.start()
    }

    @After fun tearDown() { server.shutdown() }

    private fun obj(body: String): JsonObject = Json.parseToJsonElement(body).jsonObject
    private fun JsonObject.str(key: String) = this[key]?.jsonPrimitive?.contentOrNull.orEmpty()
    private fun ok(body: String) = MockResponse().setResponseCode(200).setBody(body)
    private fun notFound() = MockResponse().setResponseCode(404).setBody("""{"error_message":"Object not found"}""")
    private fun client(apiKey: String = key) = GrocyClient(server.url("/").toString(), apiKey, OkHttpClient())
    private fun failsWith(fragment: String, block: () -> Unit) {
        try { block(); fail("expected failure containing '$fragment'") } catch (e: Exception) {
            assertTrue("was: ${e.message}", e.message.orEmpty().contains(fragment))
        }
    }

    @Test fun verifyReadsVersionAndTargets() {
        assertEquals("4.7.1", client().verify())
        assertEquals(listOf("1" to "Shopping list", "2" to "Other"), client().targets().map { it.id to it.label })
        assertTrue(seenKeys.all { it == key })
        assertTrue(seenPaths.none { key in it })
    }

    @Test fun wrongOrMissingKeyIsRejectedWithoutEchoingBodyOrKey() {
        failsWith("abgelehnt") { client("x".repeat(48)).verify() }
        failsWith("Schlüssel fehlt") { client("").verify() }
    }

    @Test fun httpsIsRequiredForNonLoopbackHosts() {
        failsWith("HTTPS") { GrocyClient("http://grocy.example.net", key).verify() }
        failsWith("Zugangsdaten") { GrocyClient("https://user:pw@grocy.example.net", key).verify() }
        failsWith("HTTPS") { GrocyClient("ftp://x", key).verify() }
    }

    @Test fun addCreatesProductAndRowAndRetryDoesNotDuplicate() {
        val first = client().addItem("1", "Monster Energy 0,5 l", "bei REWE · 0,99 €", 2.0)
        assertTrue(first.added); assertEquals(1, products.size); assertEquals(1, rows.size)
        val again = client().addItem("1", "monster energy 0,5 l", "bei REWE · 0,99 €", 2.0)
        assertFalse(again.added); assertEquals(first.rowId, again.rowId)
        assertEquals(1, products.size); assertEquals(1, rows.size)
        assertEquals("bei REWE · 0,99 €", rows.values.first()["note"])
    }

    @Test fun lostAnswerAfterCreateIsRecoveredNotDuplicated() {
        client().addItem("1", "Haferflocken")
        rows.clear()
        dropNextCreate = true
        val result = client().addItem("1", "Haferflocken")
        assertTrue(result.added); assertEquals(1, rows.size)
    }

    @Test fun openRowsListsOnlyTheChosenListWithProductNames() {
        client().addItem("1", "Eier", "10er")
        rows[99] = mutableMapOf("id" to "99", "product_id" to "", "note" to "Fremd", "amount" to "1", "shopping_list_id" to "2", "done" to "0")
        assertEquals(listOf("Eier"), client().openRows("1").map { it.name })
    }

    @Test fun removeRowIsIdentityBoundConfirmedAndKeepsTheProduct() {
        val a = client().addItem("1", "Kaffee"); val b = client().addItem("1", "Tee")
        failsWith("passt nicht") { client().removeRow("1", a.rowId, "Tee") }
        assertEquals(2, rows.size)
        assertTrue(client().removeRow("1", a.rowId, "kaffee"))
        assertEquals(listOf(b.rowId.toInt()), rows.keys.toList())
        assertTrue("Kaffee" in products.values)            // master data stays
        assertFalse(client().removeRow("1", a.rowId, "Kaffee")) // already gone: nothing deleted
        assertTrue(seenPaths.none { it.startsWith("/api/objects/products/") && false })
    }

    @Test fun rowOfAnotherListAndInvalidIdsAreNeverDeleted() {
        rows[50] = mutableMapOf("id" to "50", "product_id" to "", "note" to "fremd", "amount" to "1", "shopping_list_id" to "2", "done" to "0")
        failsWith("gehört nicht") { client().removeRow("1", "50", "fremd") }
        assertNotNull(rows[50])
        val before = server.requestCount
        for (bad in listOf("abc", "", "1;2", "../x", "-1", "1.5")) failsWith("Ungültige") { client().removeRow("1", bad, "x") }
        failsWith("Ungültige") { client().removeRow("x", "1", "x") }
        assertEquals(before, server.requestCount)
    }

    @Test fun redirectsAreNotFollowed() {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest) = MockResponse().setResponseCode(302).setHeader("Location", "http://127.0.0.1:1/steal")
        }
        failsWith("leitet um") { client().verify() }
        assertEquals(1, server.requestCount)
    }

    @Test fun timeoutIsReportedAsUnknownOutcome() {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest) = MockResponse().setBodyDelay(5, TimeUnit.SECONDS).setBody("{}")
        }
        val quick = GrocyClient(server.url("/").toString(), key, OkHttpClient.Builder().readTimeout(300, TimeUnit.MILLISECONDS).build())
        failsWith("unbekannt") { quick.verify() }
    }
}
