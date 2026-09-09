package de.lesecuritae.korbuino.kitchenowl

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

data class KitchenOwlTarget(val id: String, val label: String, val householdId: String)

/** Direct, optional KitchenOwl API access. The token never enters Korbuino. */
class KitchenOwlClient(
    private val baseUrl: String,
    private val token: String,
    private val http: OkHttpClient = OkHttpClient(),
) {
    private val json = Json { ignoreUnknownKeys = true }
    private val mediaType = "application/json; charset=utf-8".toMediaType()

    private fun checkSecure() {
        check(baseUrl.startsWith("https://")) { "KitchenOwl benötigt HTTPS" }
        check(token.isNotBlank()) { "KitchenOwl-Token fehlt" }
    }

    private fun call(path: String, body: JsonObject? = null): JsonElement {
        checkSecure()
        val request = Request.Builder().url(baseUrl.trimEnd('/') + path)
            .header("Authorization", "Bearer $token")
            .header("Accept", "application/json")
            .apply { if (body != null) post(json.encodeToString(JsonObject.serializer(), body).toRequestBody(mediaType)) }
            .build()
        http.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "KitchenOwl HTTP ${response.code}" }
            return json.parseToJsonElement(response.body?.string().orEmpty())
        }
    }

    fun targets(): List<KitchenOwlTarget> {
        val households = call("/api/household") as? JsonArray ?: return emptyList()
        return households.flatMap { value ->
            val household = value as? JsonObject ?: return@flatMap emptyList()
            val householdId = household["id"]?.toString()?.trim('"') ?: return@flatMap emptyList()
            val householdName = household["name"]?.toString()?.trim('"').orEmpty()
            val lists = call("/api/household/$householdId/shoppinglist") as? JsonArray ?: return@flatMap emptyList()
            lists.mapNotNull { listValue ->
                val list = listValue as? JsonObject ?: return@mapNotNull null
                val id = list["id"]?.toString()?.trim('"') ?: return@mapNotNull null
                val name = list["name"]?.toString()?.trim('"').orEmpty().ifBlank { "Einkauf" }
                KitchenOwlTarget(id, listOf(householdName, name).filter(String::isNotBlank).joinToString(" · "), householdId)
            }
        }
    }

    fun addItem(listId: String, name: String, description: String = "") {
        require(listId.all(Char::isDigit)) { "Ungültige KitchenOwl-Listen-ID" }
        val body = buildJsonObject {
            put("name", name)
            if (description.isNotBlank()) put("description", description)
        }
        call("/api/shoppinglist/$listId/add-item-by-name", body)
    }

    /**
     * Returns the article names currently present on a list.  Reading the
     * list before synchronizing makes repeated syncs idempotent and avoids
     * creating duplicate KitchenOwl items.  KitchenOwl may return either a
     * flat `name` field or an embedded `item.name` depending on its version.
     */
    fun existingItems(listId: String): Set<String> {
        require(listId.all(Char::isDigit)) { "Ungültige KitchenOwl-Listen-ID" }
        val values = call("/api/shoppinglist/$listId/items") as? JsonArray ?: return emptySet()
        return values.mapNotNull { value ->
            val item = value as? JsonObject ?: return@mapNotNull null
            item["name"]?.toString()?.trim('"')?.trim()?.takeIf(String::isNotBlank)
                ?: (item["item"] as? JsonObject)?.get("name")?.toString()?.trim('"')?.trim()?.takeIf(String::isNotBlank)
        }.toSet()
    }
}
