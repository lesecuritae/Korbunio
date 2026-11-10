package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.intOrNull
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
        val products = linkedMapOf<String, ProductEntity>()
        val offers = linkedMapOf<String, OfferEntity>()
        val seenPages = mutableSetOf<String>()
        var expectedCount: Int? = null
        var loadedCount = 0
        for (page in 0 until 4) {
            val url = endpoint.toHttpUrl().newBuilder().addQueryParameter("query", "ausverkauf")
                .addQueryParameter("pageSize", "500").addQueryParameter("currentPage", page.toString()).build()
            val call = Request.Builder().url(url).header("Accept", "application/json")
                .header("Referer", challengeUrl)
                .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36").build()
            val root = http.newCall(call).execute().use { response ->
                check(response.isSuccessful) { "dm HTTP ${response.code}" }
                val source = response.body?.source() ?: error("dm Antwort fehlt")
                check(!source.request(10_000_001)) { "dm Antwort zu groß" }
                json.parseToJsonElement(source.readUtf8()).jsonObject
            }
            val rows = root["products"] as? JsonArray ?: error("dm Angebotsformat unbekannt")
            val count = root["count"]?.jsonPrimitive?.intOrNull
            check(root["count"] == null || (count != null && count in 0..2000)) { "dm Gesamtzahl unbekannt oder zu groß" }
            check(expectedCount == null || count == null || count == expectedCount) { "dm Katalog während des Abrufs verändert" }
            if (count != null) expectedCount = count
            val current = root["currentPage"]?.jsonPrimitive?.intOrNull
            check(root["currentPage"] == null || current == page) { "dm falsche Pagination-Seite geliefert" }
            loadedCount += rows.size
            val pages = root["totalPages"]?.jsonPrimitive?.intOrNull
            check(root["totalPages"] == null || (pages != null && pages in 1..4)) { "dm Seitenzahl unbekannt oder Seitenlimit überschritten" }
            if (rows.isNotEmpty()) check(seenPages.add(rows.toString())) { "dm wiederholt eine Seite" }
            check(rows.isNotEmpty() || (page == 0 && (pages == null || pages == 1))) { "dm Folgeseite fehlt" }
            val result = parse(root)
            result.products.forEach { products[it.id] = it }
            result.offers.forEach { offers[it.id] = it }
            check(offers.size <= 2000) { "dm Katalog zu groß" }
            if ((pages != null && page + 1 >= pages) || (pages == null && rows.size < 500)) {
                check(expectedCount == null || loadedCount == expectedCount) { "dm Teilantwort: Produktzahl stimmt nicht mit Gesamtzahl überein" }
                return@withContext ProviderResult(products.values.toList(), offers.values.toList(), paginationComplete = true)
            }
        }
        error("dm Seitenlimit erreicht")
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
            val productId = item.text("dan", "id", "productId") ?: tile.text("dan") ?: "${id}-${slug(name)}"
            val image = tile["images"]?.jsonArray?.asSequence()
                ?.mapNotNull { runCatching { it.jsonObject.text("tileSrc", "url", "src") }.getOrNull() }
                ?.firstOrNull { !it.isNullOrBlank() }
            products += ProductEntity("dm-product-$productId", name, brand = item.text("brandName") ?: tile["brand"]?.jsonObject?.text("name").orEmpty(), normalizedKey = slug(name), gtin = item.text("gtin"))
            offers += OfferEntity(
                id = "$id:$productId", retailerId = id, productId = "dm-product-$productId",
                externalId = productId, priceCents = ProviderParsing.cents(price),
                sourceUrl = "https://www.dm.de/ausverkauf", imageUrl = image,
                description = tile["price"]?.jsonObject?.get("tileInfos")?.jsonArray.orEmpty().joinToString(" · ") { it.jsonPrimitive.content },
                packSize = ProviderParsing.packSize("$name ${tile["price"]?.jsonObject?.get("tileInfos")?.jsonArray.orEmpty().joinToString(" ") { it.jsonPrimitive.content }}"),
                cachedAt = System.currentTimeMillis(),
            )
        }
        return ProviderResult(products.distinctBy { it.id }, offers.distinctBy { it.id })
    }

    private fun JsonObject.text(vararg keys: String): String? = keys.asSequence()
        .mapNotNull { key -> runCatching { this[key]?.jsonPrimitive?.contentOrNull?.trim() }.getOrNull() }
        .firstOrNull { it.isNotBlank() }

    private fun slug(value: String): String = value.lowercase().replace("[^a-z0-9]+".toRegex(), "-").trim('-')
}
