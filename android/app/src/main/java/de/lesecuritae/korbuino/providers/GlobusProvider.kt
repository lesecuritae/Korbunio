package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request

class GlobusProvider(
    private val http: OkHttpClient = OkHttpClient(),
    private val baseUrl: String = "https://www.globus.de",
) : RetailerProvider {
    override val id = "globus"
    override val displayName = "GLOBUS"
    override val challengeUrl: String get() = baseUrl
    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(Regex("^\\d{5}$").matches(request.postalCode)) { "Ungültige PLZ" }
        val markets = postJson("$baseUrl/api/open", FormBody.Builder().add("type", "maerkte").build())
        val market = markets["data"]?.jsonObject?.values?.mapNotNull { it.jsonObjectOrNull() }
            ?.firstOrNull { it["betriebsstaette"]?.jsonPrimitive?.content == "SBW" && it["plz"]?.jsonPrimitive?.content == request.postalCode }
            ?: error("Kein GLOBUS-Markt für ${request.postalCode} gefunden")
        val code = market["marktNameKurz"]?.jsonPrimitive?.content?.lowercase()
            ?: market["nameKurz"]?.jsonPrimitive?.content?.lowercase()
            ?: error("GLOBUS-Marktcode fehlt")
        val marketId = market["marktNummer"]?.jsonPrimitive?.content ?: code
        val flyerUrl = "$baseUrl/faltblatt_online/aktuelle_woche/$code/pageitems.json"
        val pages = getJson(flyerUrl)["pages"]?.jsonArray ?: error("GLOBUS-Prospektformat unbekannt")
        parsePages(pages, marketId, flyerUrl)
    }

    private fun parsePages(pages: JsonArray, marketId: String, sourceUrl: String): ProviderResult {
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        pages.forEach { page ->
            page.jsonObject["articles"]?.jsonArray?.forEachIndexed { index, item ->
                val article = item.jsonObject
                val name = article.text("title") ?: return@forEachIndexed
                val price = article.text("price")?.replace(".", "")?.replace(',', '.')?.toDoubleOrNull()
                    ?: return@forEachIndexed
                val external = article.text("article_id") ?: "$marketId-${page.jsonObject.text("page") ?: "0"}-$index"
                val productId = "globus-product-" + normalize(name)
                products += ProductEntity(productId, name, normalizedKey = normalize(name), gtin = article.text("ean"))
                offers += OfferEntity(
                    id = "globus:$marketId:$external",
                    retailerId = id,
                    productId = productId,
                    externalId = external,
                    priceCents = (price * 100).toInt(),
                    sourceUrl = sourceUrl,
                    imageUrl = article.text("product_image") ?: article.text("productImage"),
                    cachedAt = System.currentTimeMillis(),
                )
            }
        }
        return ProviderResult(products.distinctBy { it.id }, offers.distinctBy { it.id })
    }

    private fun getJson(url: String): JsonObject {
        val request = Request.Builder().url(url).header("Accept", "application/json").build()
        http.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "GLOBUS HTTP ${response.code}" }
            return json.parseToJsonElement(response.body?.string().orEmpty()).jsonObject
        }
    }

    private fun postJson(url: String, body: FormBody): JsonObject {
        val request = Request.Builder().url(url).post(body).header("Accept", "application/json").build()
        http.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "GLOBUS HTTP ${response.code}" }
            return json.parseToJsonElement(response.body?.string().orEmpty()).jsonObject
        }
    }

    private fun JsonObject.text(key: String): String? = this[key]?.jsonPrimitive?.content?.trim()?.ifBlank { null }
    private fun kotlinx.serialization.json.JsonElement.jsonObjectOrNull(): JsonObject? = runCatching { jsonObject }.getOrNull()
    private fun normalize(value: String): String = value.lowercase().replace("[^a-z0-9]+".toRegex(), "-").trim('-')
}
