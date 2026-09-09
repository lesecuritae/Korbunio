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
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request

/** Direct read-only adapter for dm's public clearance search API. */
class DmProvider(
    private val http: OkHttpClient = OkHttpClient(),
    private val endpoint: String = "https://product-search.services.dmtech.com/de/search",
) : RetailerProvider {
    override val id = "dm"
    override val displayName = "dm"
    override val challengeUrl: String = "https://www.dm.de/ausverkauf"
    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(Regex("^\\d{5}$").matches(request.postalCode)) { "Ungültige PLZ" }
        val url = endpoint.toHttpUrl().newBuilder()
            .addQueryParameter("query", "ausverkauf")
            .addQueryParameter("pageSize", "500")
            .addQueryParameter("currentPage", "0")
            .build()
        val call = Request.Builder().url(url)
            .header("Accept", "application/json")
            .header("Referer", "https://www.dm.de/ausverkauf")
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36")
            .build()
        http.newCall(call).execute().use { response ->
            check(response.isSuccessful) { "dm HTTP ${response.code}" }
            parse(json.parseToJsonElement(response.body?.string().orEmpty()).jsonObject)
        }
    }

    private fun parse(root: JsonObject): ProviderResult {
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        root["products"]?.jsonArray.orEmpty().forEach { raw ->
            val item = raw.jsonObject
            val tile = item["tileData"]?.jsonObject ?: return@forEach
            val eye = tile["eyecatchers"]?.jsonArray.orEmpty().any {
                runCatching { it.jsonObject["alt"]?.jsonPrimitive?.content.orEmpty().contains("ausverkauf", true) }.getOrDefault(false)
            }
            if (!eye) return@forEach
            val name = item.text("title") ?: tile["title"]?.jsonObject?.text("tileHeadline") ?: return@forEach
            val priceRoot = tile["price"]?.jsonObject ?: return@forEach
            val price = priceRoot["price"]?.jsonObject?.get("current")?.jsonObject
                ?.text("value")?.let(ProviderParsing::price) ?: return@forEach
            val productId = item.text("id", "productId") ?: "${id}-${slug(name)}"
            val image = tile["images"]?.jsonArray?.asSequence()
                ?.mapNotNull { runCatching { it.jsonObject.text("tileSrc", "url", "src") }.getOrNull() }
                ?.firstOrNull { !it.isNullOrBlank() }
            products += ProductEntity("dm-product-$productId", name, brand = item.text("brandName").orEmpty(), normalizedKey = slug(name), gtin = item.text("gtin"))
            offers += OfferEntity(
                id = "$id:$productId", retailerId = id, productId = "dm-product-$productId",
                externalId = productId, priceCents = (price * 100).toInt(),
                sourceUrl = "https://www.dm.de/ausverkauf", imageUrl = image,
                cachedAt = System.currentTimeMillis(),
            )
        }
        return ProviderResult(products.distinctBy { it.id }, offers.distinctBy { it.id })
    }

    private fun JsonObject.text(vararg keys: String): String? = keys.asSequence()
        .mapNotNull { key -> runCatching { this[key]?.jsonPrimitive?.content?.trim() }.getOrNull() }
        .firstOrNull { it.isNotBlank() }

    private fun slug(value: String): String = value.lowercase().replace("[^a-z0-9]+".toRegex(), "-").trim('-')
}
