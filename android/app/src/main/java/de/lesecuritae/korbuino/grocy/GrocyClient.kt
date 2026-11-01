package de.lesecuritae.korbuino.grocy

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

data class GrocyTarget(val id: String, val label: String)

/** One open shopping-list row: [rowId] is the Grocy row, never the product. */
data class GrocyRow(val rowId: String, val productId: String, val name: String, val note: String)

data class GrocyAddResult(val rowId: String, val productId: String, val added: Boolean)

open class GrocyException(message: String) : Exception(message)
class GrocyNotFoundException : GrocyException("Grocy kennt dieses Objekt nicht (HTTP 404).")
class GrocyUnknownOutcome : GrocyException("Grocy ist nicht (rechtzeitig) erreichbar; das Ergebnis ist unbekannt.")

/**
 * Optional, direct Grocy 4.x API access (header `GROCY-API-KEY`). The key stays on the device in the encrypted store.
 *
 * Deliberate properties: HTTPS only (plain http only for a loopback host), no redirects, no cookies, numeric ids,
 * generic error texts that never echo a response body. Removing a row deletes that shopping-list row only; Grocy
 * products are never deleted (Grocy would drop every list row of a deleted product).
 */
class GrocyClient(
    private val baseUrl: String,
    private val apiKey: String,
    http: OkHttpClient = OkHttpClient(),
) {
    private val transport = http.newBuilder().followRedirects(false).followSslRedirects(false)
        .retryOnConnectionFailure(false).callTimeout(30, TimeUnit.SECONDS).build()
    private val json = Json { ignoreUnknownKeys = true }
    private val mediaType = "application/json; charset=utf-8".toMediaType()

    private fun checkedBase(): String {
        val url = baseUrl.trim().toHttpUrlOrNull()
        val loopback = url != null && url.host in setOf("localhost", "127.0.0.1", "[::1]", "::1")
        check(url != null && (url.isHttps || loopback)) { "Grocy benötigt eine gültige HTTPS-Adresse" }
        check(url.username.isEmpty() && url.password.isEmpty() && url.query == null && url.fragment == null) {
            "Grocy-Adresse ohne Zugangsdaten, Suchparameter oder Fragment eingeben"
        }
        return url.toString().trimEnd('/')
    }

    private fun call(path: String, body: JsonObject? = null, method: String = if (body != null) "POST" else "GET"): JsonElement {
        val base = checkedBase()
        check(apiKey.isNotBlank()) { "Grocy-API-Schlüssel fehlt" }
        val request = Request.Builder().url(base + path)
            .header("GROCY-API-KEY", apiKey)
            .header("Accept", "application/json")
            .apply {
                val payload = body?.let { json.encodeToString(JsonObject.serializer(), it).toRequestBody(mediaType) }
                when (method) {
                    "POST" -> post(payload!!)
                    "DELETE" -> delete()
                }
            }
            .build()
        val response = try { transport.newCall(request).execute() } catch (_: IOException) {
            throw GrocyUnknownOutcome()
        }
        response.use {
            if (it.code in 300..399) throw GrocyException("Grocy leitet um; bitte die endgültige HTTPS-Adresse eintragen.")
            if (!it.isSuccessful) {
                throw when (it.code) {
                    401, 403 -> GrocyException("Grocy hat den API-Schlüssel abgelehnt.")
                    404 -> GrocyNotFoundException()
                    else -> GrocyException("Grocy HTTP ${it.code}")
                }
            }
            val text = try { it.body?.string().orEmpty() } catch (_: IOException) { throw GrocyUnknownOutcome() }
            if (text.isBlank()) return JsonNull
            return try { json.parseToJsonElement(text) } catch (_: IllegalArgumentException) { throw GrocyException("Ungültige Grocy-Antwort") }
        }
    }

    private fun JsonObject.text(key: String): String = (this[key] as? JsonPrimitive)?.contentOrNull.orEmpty().trim()

    private fun digits(value: String, what: String) = require(value.isNotEmpty() && value.all(Char::isDigit)) { "Ungültige Grocy-$what" }

    /** Checks address and key; returns the Grocy version. */
    fun verify(): String {
        val info = call("/api/system/info") as? JsonObject ?: throw GrocyException("Das ist keine Grocy-Instanz.")
        val version = (info["grocy_version"] as? JsonObject)?.text("Version").orEmpty()
        if (version.isBlank()) throw GrocyException("Das ist keine Grocy-Instanz.")
        return version
    }

    fun targets(): List<GrocyTarget> =
        (call("/api/objects/shopping_lists") as? JsonArray).orEmpty().mapNotNull { value ->
            val list = value as? JsonObject ?: return@mapNotNull null
            val id = list.text("id").takeIf { it.isNotEmpty() && it.all(Char::isDigit) } ?: return@mapNotNull null
            GrocyTarget(id, list.text("name").ifBlank { "Einkaufsliste" })
        }

    private fun products(): Map<String, JsonObject> =
        (call("/api/objects/products") as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
            .filter { it.text("name").isNotEmpty() && it.text("id").all(Char::isDigit) }
            .associateBy { it.text("name").lowercase() }

    private fun rawRows(listId: String): List<JsonObject> {
        digits(listId, "Listen-ID")
        return (call("/api/objects/shopping_list?query%5B%5D=shopping_list_id%3D$listId") as? JsonArray).orEmpty()
            .mapNotNull { it as? JsonObject }.filter { it.text("shopping_list_id") == listId }
    }

    /** Open rows of one list with their product names (read only). */
    fun openRows(listId: String): List<GrocyRow> {
        val names = products().values.associate { it.text("id") to it.text("name") }
        return rawRows(listId).filter { it.text("done") in setOf("", "0") }.mapNotNull { row ->
            val product = row.text("product_id")
            val name = names[product].orEmpty().ifBlank { row.text("note") }
            if (name.isBlank()) null else GrocyRow(row.text("id"), product, name, row.text("note"))
        }
    }

    /**
     * Puts one article on the list. Unknown articles become a Grocy product (name only); an article that already
     * stands open on the list is not added again, so retries and repeated syncs stay idempotent.
     */
    fun addItem(listId: String, name: String, note: String = "", amount: Double = 1.0): GrocyAddResult {
        digits(listId, "Listen-ID")
        val clean = name.trim().replace(Regex("\\s+"), " ").take(120)
        require(clean.isNotEmpty()) { "Artikelname fehlt" }
        var product = products()[clean.lowercase()]
        if (product == null) {
            val location = (call("/api/objects/locations") as? JsonArray).orEmpty().firstNotNullOfOrNull { (it as? JsonObject)?.text("id")?.takeIf(String::isNotEmpty) }
            val units = (call("/api/objects/quantity_units") as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }
            val unit = (units.firstOrNull { it.text("name").lowercase() in setOf("piece", "stück", "stk") } ?: units.firstOrNull())?.text("id")
            if (location == null || unit == null) throw GrocyException("In Grocy fehlen Standort oder Mengeneinheit.")
            val created = try {
                call("/api/objects/products", buildJsonObject {
                    put("name", clean); put("location_id", location.toInt()); put("qu_id_purchase", unit.toInt()); put("qu_id_stock", unit.toInt())
                }) as? JsonObject
            } catch (_: GrocyUnknownOutcome) {
                null
            }
            val id = created?.text("created_object_id") ?: products()[clean.lowercase()]?.text("id") ?: throw GrocyException("Grocy hat das Produkt nicht bestätigt.")
            product = buildJsonObject { put("id", id); put("name", clean) }
        }
        val productId = product.text("id")
        val before = rawRows(listId)
        before.firstOrNull { it.text("product_id") == productId && it.text("done") in setOf("", "0") }?.let {
            return GrocyAddResult(it.text("id"), productId, added = false)
        }
        val body = buildJsonObject {
            put("product_id", productId.toInt()); put("amount", amount.coerceAtLeast(0.0001)); put("shopping_list_id", listId.toInt())
            if (note.isNotBlank()) put("note", note.trim().replace(Regex("\\s+"), " ").take(500))
        }
        val knownIds = before.map { it.text("id") }.toSet()
        val rowId = try {
            (call("/api/objects/shopping_list", body) as? JsonObject)?.text("created_object_id")
        } catch (_: GrocyUnknownOutcome) {
            // The request may have been applied: look instead of retrying blindly.
            rawRows(listId).firstOrNull { it.text("product_id") == productId && it.text("id") !in knownIds }?.text("id")
                ?: throw GrocyUnknownOutcome()
        }
        if (rowId.isNullOrEmpty() || !rowId.all(Char::isDigit)) throw GrocyException("Grocy hat keine Zeilen-ID geliefert.")
        return GrocyAddResult(rowId, productId, added = true)
    }

    /**
     * Removes exactly this list row after checking list and article name, then confirms by reading it again.
     * `true` = removed and confirmed gone, `false` = it was already gone (nothing deleted).
     */
    fun removeRow(listId: String, rowId: String, expectedName: String): Boolean {
        digits(listId, "Listen-ID"); digits(rowId, "Zeilen-ID")
        val path = "/api/objects/shopping_list/$rowId"
        val row = try { call(path) as? JsonObject } catch (_: GrocyNotFoundException) { return false }
            ?: throw GrocyException("Ungültige Grocy-Antwort")
        if (row.text("shopping_list_id") != listId) throw GrocyException("Diese Position gehört nicht zur gewählten Grocy-Liste; nichts gelöscht.")
        val productId = row.text("product_id")
        val actual = if (productId.isNotEmpty()) {
            digits(productId, "Produkt-ID")
            (call("/api/objects/products/$productId") as? JsonObject)?.text("name").orEmpty()
        } else row.text("note")
        if (!actual.equals(expectedName.trim(), ignoreCase = true)) throw GrocyException("Die Position passt nicht zum erwarteten Artikel; nichts gelöscht.")
        call(path, method = "DELETE")
        try { call(path) } catch (_: GrocyNotFoundException) { return true }
        throw GrocyException("Grocy meldet die Position nach dem Löschen weiterhin; Löschen nicht bestätigt.")
    }
}

/** Only rows Korbuino created itself (tracked by Grocy row id) are ever removed; rows added by people stay. */
object GrocySyncPlan {
    data class Plan(val toAdd: Set<String>, val toRemoveKeys: Set<String>)

    /** [local] wanted keys, [synced] key -> row id Korbuino created earlier, [remoteRowIds] rows currently open on the list. */
    fun plan(local: Set<String>, synced: Map<String, String>, remoteRowIds: Set<String>): Plan {
        val present = synced.filterValues { it in remoteRowIds }.keys
        return Plan(toAdd = local - present, toRemoveKeys = synced.keys - local)
    }
}
