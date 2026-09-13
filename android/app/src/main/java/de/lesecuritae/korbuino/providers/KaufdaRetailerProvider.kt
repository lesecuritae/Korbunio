package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import org.jsoup.Jsoup
import java.math.BigDecimal
import java.math.RoundingMode
import java.text.Normalizer
import java.time.Instant
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Public, read-only weekly offer fallback from KaufDA's structured web page. */
class KaufdaRetailerProvider(
    override val id: String,
    override val displayName: String,
    private val publisherName: String,
    private val publisherSlug: String,
    private val http: OkHttpClient = OkHttpClient(),
    private val baseUrl: String = "https://www.kaufda.de",
    private val now: () -> Instant = Instant::now,
) : RetailerProvider {
    private val json = Json { ignoreUnknownKeys = true }
    private val sourceUrl get() = "$baseUrl/Geschaefte/$publisherSlug"
    override val challengeUrl: String get() = sourceUrl

    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(request.postalCode.matches(Regex("^\\d{5}$"))) { "Ungültige PLZ" }
        val response = http.newCall(
            Request.Builder().url(sourceUrl)
                .header("Accept", "text/html,application/xhtml+xml")
                .header("Accept-Language", "de-DE,de;q=0.9")
                .build(),
        ).execute()
        val html = response.use {
            check(it.isSuccessful) { "KaufDA HTTP ${it.code}" }
            it.body?.string().orEmpty()
        }
        parse(html)
    }

    private fun parse(html: String): ProviderResult {
        val payload = Jsoup.parse(html, sourceUrl).selectFirst("script#__NEXT_DATA__")?.data()
            ?.takeIf(String::isNotBlank) ?: error("KaufDA lieferte keine strukturierten $displayName-Angebote")
        val items = json.parseToJsonElement(payload).jsonObject["props"]?.jsonObject
            ?.get("pageProps")?.jsonObject?.get("pageInformation")?.jsonObject
            ?.get("offers")?.jsonObject?.get("main")?.jsonObject?.get("items")?.jsonArray
            ?: error("KaufDA-$displayName-Angebotsformat unbekannt")
        val products = linkedMapOf<String, ProductEntity>()
        val offers = linkedMapOf<String, OfferEntity>()
        items.forEachIndexed { index, raw ->
            val item = raw.jsonObject
            if (!item.text("type").equals("OFFER", ignoreCase = true) ||
                !item.text("publisherName").equals(publisherName, ignoreCase = true)
            ) return@forEachIndexed
            val validFrom = item.instant("validFrom") ?: return@forEachIndexed
            val validUntil = item.instant("validUntil") ?: return@forEachIndexed
            if (now() < validFrom || now() > validUntil) return@forEachIndexed
            val title = item.text("title") ?: return@forEachIndexed
            val brand = item.text("brand").orEmpty()
            val name = if (brand.isBlank() || title.contains(brand, ignoreCase = true)) title else "$brand $title"
            val price = item["prices"]?.jsonObject?.get("mainPrice")?.jsonPrimitive?.doubleOrNull
                ?.takeIf { it > 0.0 } ?: return@forEachIndexed
            val external = item.text("id") ?: "$index-${normalize(name)}"
            val productId = "$id-product-${normalize(name)}"
            val images = item["offerImages"]?.jsonObject?.get("url")?.jsonObject
            val image = sequenceOf("normal", "large", "thumbnail").mapNotNull { key -> images?.text(key) }
                .firstOrNull { it.startsWith("https://content-media.bonial.biz/") && it.contains("SEO-offer", true) }
            products[productId] = ProductEntity(productId, name, brand, normalize(name))
            offers[external] = OfferEntity(
                id = "$id:$external",
                retailerId = id,
                productId = productId,
                externalId = external,
                priceCents = BigDecimal.valueOf(price).movePointRight(2)
                    .setScale(0, RoundingMode.HALF_UP).intValueExact(),
                validFrom = validFrom.toString(),
                validUntil = validUntil.toString(),
                sourceUrl = sourceUrl,
                imageUrl = image,
                cachedAt = System.currentTimeMillis(),
            )
        }
        return ProviderResult(products.values.toList(), offers.values.toList())
    }

    private fun JsonObject.text(key: String): String? = this[key]?.jsonPrimitive?.content?.trim()?.ifBlank { null }

    private fun JsonObject.instant(key: String): Instant? = text(key)?.let { value ->
        runCatching { Instant.parse(value) }.getOrElse {
            runCatching { OffsetDateTime.parse(value, DATE_WITH_COMPACT_OFFSET).toInstant() }.getOrNull()
        }
    }

    private fun normalize(value: String): String = Normalizer.normalize(
        value.lowercase(Locale.GERMAN),
        Normalizer.Form.NFKD,
    ).replace("\\p{M}".toRegex(), "").replace("[^a-z0-9]+".toRegex(), "-").trim('-')

    companion object {
        private val DATE_WITH_COMPACT_OFFSET = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSZ")
    }
}
