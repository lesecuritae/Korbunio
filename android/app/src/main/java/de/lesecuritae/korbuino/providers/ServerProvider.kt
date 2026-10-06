package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.LoyaltyBenefits
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.put
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

/**
 * Self-hosted Korbuino API. Without [retailerName] it returns the server's
 * consolidated result for every retailer (server mode). With it, it asks the
 * server for that one retailer, whose offers are stored under [localId]; the
 * server fetches with curl_cffi, so it gets through where the app is blocked.
 */
class ServerProvider(
    private val baseUrl: String,
    private val token: String,
    private val http: OkHttpClient,
    private val retailerName: String? = null,
    private val localId: String? = null,
) : RetailerProvider {
    override val id = localId ?: "korbuino-server"
    override val displayName = retailerName ?: "Korbuino Server"
    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(request.postalCode.matches(Regex("^\\d{5}$"))) { "Ungültige PLZ" }
        val offerItems = mutableListOf<JsonObject>()
        var page = 1
        var pageCount = 1
        do {
            val body = buildJsonObject {
                put("postal_code", request.postalCode)
                put("refresh", page == 1)
                // Lets the app load product images itself, like for its own offers. Older servers ignore it.
                put("include_image_urls", true)
                putJsonArray("retailers") { retailerName?.let { add(JsonPrimitive(it)) } }
                // Page through the complete result in both server and fallback modes.
                put("view", "all")
                put("page", page)
                put("page_size", 100)
            }.toString()
            val requestBuilder = Request.Builder().url(baseUrl.trimEnd('/') + "/api/v1/compare")
                .header("Accept", "application/json")
                .post(body.toRequestBody("application/json".toMediaType()))
            if (token.isNotBlank()) requestBuilder.header("Authorization", "Bearer $token")
            val root = json.parseToJsonElement(
                http.newCall(requestBuilder.build()).execute().use { response ->
                    check(response.isSuccessful) { "Korbuino Server HTTP ${response.code}" }
                    response.body?.string().orEmpty()
                },
            ).jsonObject
            val resultRoot = if (root["offers"]?.jsonArray?.isNotEmpty() == true) root else fetchResult(root)
            resultRoot["offers"]?.jsonArray.orEmpty().forEach { offerItems += it.jsonObject }
            pageCount = (resultRoot.number("page_count")?.toInt() ?: 1).coerceAtLeast(1)
            page++
        } while (page <= pageCount)
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        offerItems.forEachIndexed { index, item ->
            val name = item.text("product") ?: item.text("name") ?: return@forEachIndexed
            val price = item.number("regular_price") ?: item.number("price") ?: return@forEachIndexed
            val benefits = LoyaltyBenefits.parse(item["benefits"]?.toString().orEmpty())
            val retailer = localId ?: item.text("retailer") ?: "Unbekannt"
            val external = item.text("offer_id") ?: "$index-${name.lowercase().hashCode()}"
            val productId = "server-product-${name.lowercase().hashCode()}"
            products += ProductEntity(productId, name, brand = item.text("brand").orEmpty(), normalizedKey = productId)
            offers += OfferEntity(
                id = "${localId ?: "server"}:$external", retailerId = retailer, productId = productId,
                externalId = external, priceCents = Math.round(price * 100).toInt(),
                loyaltyBenefitsJson = LoyaltyBenefits.encode(benefits),
                basePriceCents = item.number("base_price")?.let { (it * 100).toInt() },
                categoryId = item.text("category"), sourceUrl = item.text("source_url").orEmpty(),
                imageUrl = item.text("image_url")?.let { image ->
                    val parsed = image.toHttpUrlOrNull()
                    if (parsed != null && parsed.host.isNotBlank()) image
                    else baseUrl.trimEnd('/') + "/" + image.trimStart('/')
                }, cachedAt = System.currentTimeMillis(),
            )
        }
        ProviderResult(products.distinctBy { it.id }, offers.distinctBy { it.id })
    }

    private fun fetchResult(compare: JsonObject): JsonObject {
        val resultUrl = compare.text("result_url") ?: return compare
        val parsed = resultUrl.toHttpUrlOrNull() ?: return compare
        val path = if (parsed.encodedPath.startsWith("/api/v1/")) parsed.encodedPath
        else "/api/v1${parsed.encodedPath}"
        val url = parsed.newBuilder().encodedPath(path).build()
        val requestBuilder = Request.Builder().url(url).header("Accept", "application/json")
        if (token.isNotBlank()) requestBuilder.header("Authorization", "Bearer $token")
        return json.parseToJsonElement(
            http.newCall(requestBuilder.build()).execute().use { response ->
                check(response.isSuccessful) { "Korbuino Ergebnis HTTP ${response.code}" }
                response.body?.string().orEmpty()
            },
        ).jsonObject
    }

    private fun JsonObject.text(key: String): String? = runCatching { this[key]?.jsonPrimitive?.content?.trim() }.getOrNull()?.ifBlank { null }
    private fun JsonObject.number(key: String): Double? = ProviderParsing.price(text(key))
}
