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
import kotlinx.serialization.json.intOrNull
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.Locale

/**
 * Direct, read-only fallback for retailers whose public sites block mobile
 * HTML. Marktguru's public web client exposes regional offer search; API keys
 * are discovered from its public page at runtime and are never persisted.
 */
class MarktguruProvider(
    private val retailerName: String,
    private val http: OkHttpClient = OkHttpClient(),
    private val homeUrl: String = "https://www.marktguru.de/",
    private val apiUrl: String = "https://api.marktguru.de/api/v1/offers/search",
) : RetailerProvider {
    override val id: String = "marktguru-${slug(retailerName)}"
    override val displayName: String = "$retailerName (regional)"
    override val challengeUrl: String get() = homeUrl
    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(Regex("^\\d{5}$").matches(request.postalCode)) { "Ungültige PLZ" }
        val credentials = discoverCredentials()
        val products = linkedMapOf<String, ProductEntity>()
        val offers = linkedMapOf<String, OfferEntity>()
        var offset = 0
        for (pageIndex in 0 until 50) {
            val root = fetchPage(request.postalCode, offset, credentials)
            val page = parse(root)
            page.products.forEach { products[it.id] = it }
            page.offers.forEach { offers[it.id] = it }
            val count = root["results"]?.jsonArray?.size ?: 0
            val total = root["totalResults"]?.jsonPrimitive?.intOrNull ?: 0
            if (count == 0 || count < 100 || (total > 0 && offset + count >= total)) break
            offset += count
        }
        ProviderResult(products.values.toList(), offers.values.toList())
    }

    private fun fetchPage(postalCode: String, offset: Int, credentials: Pair<String, String>): JsonObject {
        val url = apiUrl.toHttpUrl().newBuilder()
            .addQueryParameter("as", "web")
            .addQueryParameter("limit", "100")
            .addQueryParameter("offset", offset.toString())
            .addQueryParameter("q", retailerName)
            .addQueryParameter("zipCode", postalCode)
            .build()
        val requestBuilder = Request.Builder().url(url)
            .header("Accept", "application/json")
            .header("x-apikey", credentials.first)
            .header("x-clientkey", credentials.second)
        http.newCall(requestBuilder.build()).execute().use { response ->
            check(response.isSuccessful) { "Marktguru HTTP ${response.code}" }
            return json.parseToJsonElement(response.body?.string().orEmpty()).jsonObject
        }
    }

    private fun discoverCredentials(): Pair<String, String> {
        val request = Request.Builder().url(homeUrl)
            .header("Accept", "text/html,application/xhtml+xml")
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36")
            .build()
        val html = http.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "Marktguru HTTP ${response.code}" }
            response.body?.string().orEmpty()
        }
        val api = firstKey(html, "apiKey", "x-apikey", "x_apiKey") ?: error("Marktguru API-Key fehlt")
        val client = firstKey(html, "clientKey", "x-clientkey", "x_clientKey") ?: error("Marktguru Client-Key fehlt")
        return api to client
    }

    private fun parse(root: JsonObject): ProviderResult {
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        root["results"]?.jsonArray.orEmpty().forEachIndexed { index, raw ->
            val item = raw.jsonObject
            val product = item["product"]?.jsonObject ?: item
            val name = text(product, "name", "title", "productName") ?: return@forEachIndexed
            val price = number(item, "price", "currentPrice", "regularPrice")
                ?: number(product, "price", "currentPrice") ?: return@forEachIndexed
            val external = text(item, "id", "offerId") ?: "$index-${slug(name)}"
            val productId = "$id-product-${slug(name)}"
            val image = text(product, "image", "imageUrl", "image_url")
            products += ProductEntity(productId, name, normalizedKey = slug(name))
            offers += OfferEntity(
                id = "$id:$external", retailerId = id, productId = productId,
                externalId = external, priceCents = (price * 100).toInt(),
                sourceUrl = "https://www.marktguru.de/", imageUrl = image,
                cachedAt = System.currentTimeMillis(),
            )
        }
        return ProviderResult(products.distinctBy { it.id }, offers.distinctBy { it.id })
    }

    private fun text(obj: JsonObject, vararg keys: String): String? = keys.asSequence()
        .mapNotNull { key -> runCatching { obj[key]?.jsonPrimitive?.content?.trim() }.getOrNull() }
        .firstOrNull { it.isNotBlank() }

    private fun number(obj: JsonObject, vararg keys: String): Double? = text(obj, *keys)
        ?.replace("€", "")?.replace(".", "")?.replace(',', '.')?.trim()?.toDoubleOrNull()

    private fun firstKey(html: String, vararg names: String): String? = names.asSequence()
        .mapNotNull { name -> Regex("[\\\"']$name[\\\"']\\s*[:=]\\s*[\\\"']([^\\\"']+)").find(html)?.groupValues?.get(1) }
        .firstOrNull { it.isNotBlank() }

    private fun slug(value: String): String = value.lowercase(Locale.GERMAN).replace("[^a-z0-9]+".toRegex(), "-").trim('-')
}
