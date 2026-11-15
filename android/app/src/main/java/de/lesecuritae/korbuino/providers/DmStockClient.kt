package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*
import okhttp3.Authenticator
import okhttp3.CookieJar
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.time.Instant
import java.util.concurrent.TimeUnit

/** Direct official dm MCP. No retailer app, account, API key or tracking SDK. */
internal class DmStockClient(
    http: OkHttpClient = OkHttpClient(),
    private val endpoint: String = "https://mcp.dm.de/mcp",
    private val now: () -> Long = { System.nanoTime() / 1_000_000 },
    private val pause: suspend (Long) -> Unit = { delay(it) },
) {
    private val http = http.newBuilder().cookieJar(CookieJar.NO_COOKIES)
        .authenticator(Authenticator.NONE).proxyAuthenticator(Authenticator.NONE)
        .followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(15, TimeUnit.SECONDS)
        .callTimeout(20, TimeUnit.SECONDS).build()
    private val lock = Mutex()
    private var session: String? = null
    private var protocol: String? = null
    private var sequence = 0
    private var nextRequest = 0L
    private val cache = linkedMapOf<Pair<String, String>, Pair<Long, StockProduct>>()
    private val markets = linkedMapOf<String, Pair<Long, List<Map<String, String>>>>()

    suspend fun check(postal: String, dans: List<String>): List<StockProduct> = withContext(Dispatchers.IO) {
        require(Regex("[0-9]{5}").matches(postal) && dans.size in 1..5 && dans.all { Regex("[0-9]{7}").matches(it) }) { "dm benötigt PLZ und siebenstellige Artikelnummern." }
        check(lock.tryLock()) { "Eine dm-Bestandsabfrage läuft bereits." }
        try {
            val missing = dans.distinct().filter { cache[postal to it]?.let { v -> now() - v.first < 60_000 } != true }
            if (missing.isNotEmpty()) {
                val saved = markets[postal]
                val stores = if (saved != null && now() - saved.first < 86_400_000) saved.second else {
                    val reply = tool("findNearbyStores", buildJsonObject { put("location", postal); put("min_results", 5) })
                    parseStores(reply).also {
                        if (markets.size >= 128) markets.remove(markets.keys.first())
                        markets[postal] = now() to it
                    }
                }
                check(stores.isNotEmpty()) { "Keine bestätigten dm-Märkte in 25 km Umkreis; Bestand unbekannt." }
                val raw = tool("getStoreAvailability", buildJsonObject {
                    putJsonArray("storeIds") { stores.forEach { add(JsonPrimitive(it.getValue("storeId"))) } }
                    putJsonArray("dans") { missing.forEach { add(JsonPrimitive(it.toInt())) } }
                })
                val products = parseStock(raw, stores, missing)
                for (product in products) {
                    if (product.error == null) {
                        if (cache.size >= 128) cache.remove(cache.keys.first())
                        cache[postal to product.dan] = now() to product
                    }
                }
                return@withContext dans.distinct().map { dan ->
                    products.firstOrNull { it.dan == dan } ?: cache.getValue(postal to dan).second.copy(fromCache = true)
                }
            }
            dans.distinct().map { cache.getValue(postal to it).second.copy(fromCache = true) }
        } finally { lock.unlock() }
    }

    private suspend fun tool(name: String, arguments: JsonObject): String {
        val wait = nextRequest - now()
        check(wait <= 2000) { "dm-Rate-Limit: bitte später erneut abfragen." }
        if (wait > 0) pause(wait)
        nextRequest = now() + 2000
        if (protocol == null) {
            val init = rpc("initialize", buildJsonObject {
                put("protocolVersion", "2025-11-25"); put("capabilities", buildJsonObject {})
                put("clientInfo", buildJsonObject { put("name", "korbuino-android"); put("version", "1") })
            })
            val version = init["protocolVersion"]?.jsonPrimitive?.content
            check(version in setOf("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")) { "Nicht unterstützte dm-MCP-Version." }
            protocol = version
            rpc("notifications/initialized", buildJsonObject {}, notification = true)
        }
        val result = rpc("tools/call", buildJsonObject { put("name", name); put("arguments", arguments) })
        check(result["isError"]?.jsonPrimitive?.booleanOrNull != true) { "dm-Werkzeug meldet einen Abruffehler." }
        val wrapper = result["structuredContent"] as? JsonObject ?: run {
            val blocks = result["content"] as? JsonArray ?: error("dm-Ergebnis fehlt")
            val text = blocks.single().jsonObject["text"]?.jsonPrimitive?.content ?: error("dm-Ergebnis fehlt")
            Json.parseToJsonElement(text).jsonObject
        }
        // The upstream "instruction" field is deliberately not executed or
        // promoted to an app/agent policy; only the requested data is read.
        return wrapper["result"]?.jsonPrimitive?.content ?: error("dm-Ergebnisformat geändert")
    }

    private fun rpc(method: String, params: JsonObject, notification: Boolean = false): JsonObject {
        val id = ++sequence
        val body = buildJsonObject { put("jsonrpc", "2.0"); put("method", method); put("params", params); if (!notification) put("id", id) }
        val request = Request.Builder().url(endpoint).header("Accept", "application/json, text/event-stream")
            .header("User-Agent", "Korbuino-dm/1 (+https://github.com/lesecuritae/Korbunio)")
            .post(body.toString().toRequestBody("application/json".toMediaType()))
        session?.let { request.header("Mcp-Session-Id", it) }
        protocol?.let { request.header("MCP-Protocol-Version", it) }
        val raw = http.newCall(request.build()).execute().use { response ->
            if (response.code in setOf(400, 404)) { protocol = null; session = null }
            if (response.code == 429) nextRequest = now() + 60_000
            check(response.isSuccessful) { "dm MCP HTTP ${response.code}; Bestand unbekannt, keine automatische Wiederholung." }
            response.header("Mcp-Session-Id")?.let { value ->
                check(value.length <= 200 && value.all { it.code in 32..126 }); session = value
            }
            val source = response.body?.source() ?: return@use ""
            check(!source.request(2_000_001)) { "dm-Antwort zu groß" }
            source.readUtf8()
        }
        if (notification && raw.isBlank()) return buildJsonObject {}
        val root = if (raw.trimStart().startsWith("{")) Json.parseToJsonElement(raw).jsonObject else {
            raw.lineSequence().filter { it.startsWith("data:") }.map { Json.parseToJsonElement(it.substring(5).trim()).jsonObject }
                .firstOrNull { it["id"]?.jsonPrimitive?.intOrNull == id } ?: error("dm-MCP-Antwort fehlt")
        }
        check(root["error"] == null && root["id"]?.jsonPrimitive?.intOrNull == id) { "dm-MCP-Anfrage abgewiesen" }
        return root["result"] as? JsonObject ?: error("dm-MCP-Ergebnis fehlt")
    }

    companion object {
        val shared by lazy { DmStockClient() }

        fun parseStores(value: String): List<Map<String, String>> {
            val lines = value.trim().lines()
            val header = Regex("stores\\[([0-9]{1,2})]\\{([^}]+)}:").matchEntire(lines.firstOrNull().orEmpty()) ?: error("dm-Marktformat geändert")
            val fields = header.groupValues[2].split(',')
            check(fields.toSet().containsAll(listOf("storeId", "city", "zip", "street", "distanceKm")) && fields.distinct().size == fields.size)
            val rows = lines.drop(1).map { parseRow(it.trim()) }
            check(rows.size == header.groupValues[1].toInt() && rows.size <= 20)
            val seen = mutableSetOf<String>()
            return rows.map { row ->
                check(row.size == fields.size)
                fields.zip(row).toMap().also { check(Regex("[A-Za-z0-9]{1,16}").matches(it.getValue("storeId")) && seen.add(it.getValue("storeId"))) }
            }.filter { it.getValue("distanceKm").toDouble().let { d -> d.isFinite() && d in 0.0..25.0 } }
        }

        private fun parseRow(value: String): List<String> {
            val parts = mutableListOf<String>(); var start = 0; var quoted = false; var escaped = false
            for ((i, c) in value.withIndex()) {
                if (escaped) { escaped = false; continue }
                if (c == '\\' && quoted) { escaped = true; continue }
                if (c == '"') quoted = !quoted
                if (c == ',' && !quoted) { parts += value.substring(start, i); start = i + 1 }
            }
            check(!quoted && !escaped) { "dm-Marktzeile unvollständig" }
            parts += value.substring(start)
            return parts.map { part -> if (part.startsWith('"')) Json.parseToJsonElement(part).jsonPrimitive.content else part }
        }

        fun parseStock(value: String, stores: List<Map<String, String>>, dans: List<String>): List<StockProduct> {
            val root = Json.parseToJsonElement(value).jsonObject
            check(root["errorMessage"] == null || root["errorMessage"] is JsonNull)
            val rows = root["productAvailabilities"]!!.jsonArray
            val byDan = rows.associate { it.jsonObject["dan"]!!.jsonPrimitive.content to it.jsonObject }
            check(byDan.size == rows.size && byDan.keys == dans.toSet()) { "dm-Artikelzuordnung widersprüchlich" }
            return dans.map { dan ->
                val row = byDan.getValue(dan)
                if (row["found"]?.jsonPrimitive?.booleanOrNull == false) return@map StockProduct(dan, error = "dm-Artikel unbekannt; kein Nullbestand.")
                val stock = row["stores"]!!.jsonArray
                val byStore = stock.associate { it.jsonObject["storeId"]!!.jsonPrimitive.content to it.jsonObject }
                check(byStore.size == stock.size && byStore.keys == stores.map { it.getValue("storeId") }.toSet())
                val parsed = stores.map { store ->
                    val state = byStore.getValue(store.getValue("storeId")); val status = state["status"]!!.jsonPrimitive.content
                    check(status in setOf("VERFUEGBAR", "NICHT_VERFUEGBAR", "NUR_ONLINE", "PRODUKT_UNBEKANNT", "STORE_UNBEKANNT"))
                    val count = state["stockLevel"]?.takeUnless { it is JsonNull }?.jsonPrimitive?.intOrNull
                    check(state["stockLevel"] == null || state["stockLevel"] is JsonNull || (count != null && count >= 0))
                    check(status != "VERFUEGBAR" || count != 0)
                    StockStore(store.getValue("storeId"), store.getValue("city"), store.getValue("street"), store.getValue("zip"),
                        status, if (status == "VERFUEGBAR") count else if (status == "NICHT_VERFUEGBAR") 0 else null,
                        status == "VERFUEGBAR" && count != null, status)
                }
                StockProduct(dan, parsed, Instant.now().toString())
            }
        }
    }
}
