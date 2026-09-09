package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

/** Optional server mode. The native app can use a self-hosted Korbuino API. */
class ServerProvider(
    private val baseUrl: String,
    private val token: String,
    private val http: OkHttpClient,
) : RetailerProvider {
    override val id = "korbuino-server"
    override val displayName = "Korbuino Server"
    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(request.postalCode.matches(Regex("^\\d{5}$"))) { "Ungültige PLZ" }
        val requestBuilder = Request.Builder().url(baseUrl.trimEnd('/') + "/api/v1/compare")
            .header("Accept", "application/json")
            .post("""{"postal_code":"${request.postalCode}","refresh":true,"retailers":[]}""".toRequestBody("application/json".toMediaType()))
        if (token.isNotBlank()) requestBuilder.header("Authorization", "Bearer $token")
        val root = json.parseToJsonElement(
            http.newCall(requestBuilder.build()).execute().use { response ->
                check(response.isSuccessful) { "Korbuino Server HTTP ${response.code}" }
                response.body?.string().orEmpty()
            },
        ).jsonObject
        val resultRoot = if (root["offers"]?.jsonArray?.isNotEmpty() == true) root else fetchResult(root)
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        resultRoot["offers"]?.jsonArray.orEmpty().forEachIndexed { index, element ->
            val item = element.jsonObject
            val name = item.text("product") ?: item.text("name") ?: return@forEachIndexed
            val price = item.number("regular_price") ?: item.number("price") ?: return@forEachIndexed
            val retailer = item.text("retailer") ?: "Unbekannt"
            val external = item.text("offer_id") ?: "$index-${name.lowercase().hashCode()}"
            val productId = "server-product-${name.lowercase().hashCode()}"
            products += ProductEntity(productId, name, brand = item.text("brand").orEmpty(), normalizedKey = productId)
            offers += OfferEntity(
                id = "server:$external", retailerId = retailer, productId = productId,
                externalId = external, priceCents = (price * 100).toInt(),
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
