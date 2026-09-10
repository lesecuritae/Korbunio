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
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import java.math.BigDecimal
import java.math.RoundingMode

class GlobusProvider(
    private val http: OkHttpClient = OkHttpClient(),
    private val baseUrl: String = "https://www.globus.de",
    private val kaufdaBaseUrl: String = "https://www.kaufda.de",
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
        val official = parsePages(pages, marketId, flyerUrl)
        val city = market["marktName"]?.jsonPrimitive?.content
            ?: market["name"]?.jsonPrimitive?.content
            ?: request.citySlug.orEmpty()
        enrichImages(official, runCatching { loadKaufdaImages(city.substringBefore('-')) }.getOrDefault(emptyList()))
    }

    private fun parsePages(pages: JsonArray, marketId: String, sourceUrl: String): ProviderResult {
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        pages.forEach { page ->
            val pageObject = page.jsonObject
            pageObject["articles"]?.jsonArray?.forEachIndexed { index, item ->
                val article = item.jsonObject
                val name = article.text("title") ?: return@forEachIndexed
                val price = ProviderParsing.price(article.text("price"))
                    ?: return@forEachIndexed
                val external = article.text("article_id") ?: "$marketId-${pageObject.text("page") ?: "0"}-$index"
                val productId = "globus-product-" + normalize(name)
                products += ProductEntity(productId, name, normalizedKey = normalize(name), gtin = article.text("ean"))
                offers += OfferEntity(
                    id = "globus:$marketId:$external",
                    retailerId = id,
                    productId = productId,
                    externalId = external,
                    priceCents = BigDecimal.valueOf(price).movePointRight(2)
                        .setScale(0, RoundingMode.HALF_UP).intValueExact(),
                    sourceUrl = sourceUrl,
                    imageUrl = article.text("product_image") ?: article.text("productImage"),
                    cachedAt = System.currentTimeMillis(),
                )
            }
        }
        return ProviderResult(products.distinctBy { it.id }, offers.distinctBy { it.id })
    }

    private data class ImageMatch(val normalizedName: String, val priceCents: Int, val url: String)

    private fun loadKaufdaImages(city: String): List<ImageMatch> {
        if (city.isBlank()) return emptyList()
        val url = kaufdaBaseUrl.toHttpUrl().newBuilder()
            .addPathSegment(city.trim())
            .addPathSegment("Globus")
            .addPathSegment("p-r37")
            .build()
        val request = Request.Builder().url(url)
            .header("Accept", "text/html,application/xhtml+xml")
            .build()
        val html = http.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "KaufDA HTTP ${response.code}" }
            response.body?.string().orEmpty()
        }
        val payload = Regex(
            "<script[^>]+id=[\\\"']__NEXT_DATA__[\\\"'][^>]*>(.*?)</script>",
            setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL),
        ).find(html)?.groupValues?.get(1) ?: return emptyList()
        val root = json.parseToJsonElement(payload).jsonObject
        val items = root["props"]?.jsonObject
            ?.get("pageProps")?.jsonObject
            ?.get("pageInformation")?.jsonObject
            ?.get("offers")?.jsonObject
            ?.get("main")?.jsonObject
            ?.get("items")?.jsonArray ?: return emptyList()
        return items.mapNotNull { raw ->
            val item = raw.jsonObject
            if (!item.text("type").equals("OFFER", ignoreCase = true) ||
                !item.text("publisherName").equals("GLOBUS", ignoreCase = true)
            ) return@mapNotNull null
            val name = item.text("title") ?: return@mapNotNull null
            val price = item["prices"]?.jsonObject?.get("mainPrice")?.jsonPrimitive?.content
                ?.let(ProviderParsing::price) ?: return@mapNotNull null
            val urls = item["offerImages"]?.jsonObject?.get("url")?.jsonObject
            val image = urls?.get("normal")?.jsonPrimitive?.content
                ?: urls?.get("large")?.jsonPrimitive?.content
                ?: return@mapNotNull null
            if (!image.startsWith("https://content-media.bonial.biz/") ||
                !image.contains("SEO-offer", ignoreCase = true)
            ) return@mapNotNull null
            ImageMatch(normalize(name), cents(price), image)
        }
    }

    private fun enrichImages(result: ProviderResult, images: List<ImageMatch>): ProviderResult {
        if (images.isEmpty()) return result
        val byIdentity = images.associateBy { it.normalizedName to it.priceCents }
        val productNames = result.products.associate { it.id to normalize(it.name) }
        return result.copy(offers = result.offers.map { offer ->
            if (offer.imageUrl != null) offer
            else offer.copy(imageUrl = byIdentity[productNames[offer.productId] to offer.priceCents]?.url)
        })
    }

    private fun cents(price: Double): Int = BigDecimal.valueOf(price).movePointRight(2)
        .setScale(0, RoundingMode.HALF_UP).intValueExact()

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
