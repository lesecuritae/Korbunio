package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import org.jsoup.Jsoup
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.LocalDate
import java.time.ZoneId

/** Reads ALDI Nord's structured, public weekly-offer payload. */
class AldiNordProvider(
    private val http: OkHttpClient,
    private val pageUrl: String = "https://www.aldi-nord.de/angebote.html",
    private val today: () -> LocalDate = { LocalDate.now(ZoneId.of("Europe/Berlin")) },
) : RetailerProvider {
    override val id = "aldi-nord"
    override val displayName = "ALDI Nord"
    override val challengeUrl: String get() = pageUrl
    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(Regex("^\\d{5}$").matches(request.postalCode)) { "Ungültige PLZ" }
        val html = http.newCall(
            Request.Builder().url(pageUrl)
                .header("Accept", "text/html,application/xhtml+xml")
                .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36")
                .build(),
        ).execute().use { response ->
            check(response.isSuccessful) { "ALDI Nord HTTP ${response.code}" }
            response.body?.string().orEmpty()
        }
        val script = Jsoup.parse(html).selectFirst("script#__NEXT_DATA__")?.data().orEmpty()
        check(script.isNotBlank()) { "ALDI Nord Angebotsdaten fehlen" }
        val pageProps = json.parseToJsonElement(script).jsonObject["props"]?.jsonObject
            ?.get("pageProps")?.jsonObject ?: error("ALDI Nord Seitenformat ungültig")
        val apiElement = pageProps["apiData"] ?: error("ALDI Nord API-Daten fehlen")
        val apiData = when (apiElement) {
            is JsonArray -> apiElement
            is JsonPrimitive -> json.parseToJsonElement(apiElement.content).jsonArray
            else -> error("ALDI Nord API-Daten ungültig")
        }
        val response = apiData.firstNotNullOfOrNull { entry ->
            val pair = entry as? JsonArray ?: return@firstNotNullOfOrNull null
            if (pair.size != 2 || pair[0].jsonPrimitive.content != "OFFER_GET") return@firstNotNullOfOrNull null
            pair[1].jsonObject["res"]?.jsonObject
        } ?: error("ALDI Nord Angebotsblock fehlt")

        val placements = placements(response["categories"]?.jsonArray.orEmpty())
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        response["algoliaDataMap"]?.jsonObject.orEmpty().forEach { (externalId, product) ->
            val item = product.jsonObject
            val placement = placements[externalId] ?: return@forEach
            val price = currentPrice(item, placement) ?: return@forEach
            val name = text(item, "name") ?: return@forEach
            val brand = text(item, "brandName").orEmpty()
            val displayName = if (brand.isBlank() || name.contains(brand, ignoreCase = true)) name else "$brand $name"
            val productId = "aldi-nord-product-$externalId"
            val image = item["assets"]?.jsonArray.orEmpty().firstNotNullOfOrNull { asset ->
                val value = asset.jsonObject
                value["url"]?.jsonPrimitive?.contentOrNullIfBlank()
                    ?.takeIf { value["type"]?.jsonPrimitive?.content == "primary" }
            }
            val base = price["basePrice"]?.let { element ->
                when (element) {
                    is JsonArray -> element.firstOrNull()?.jsonObject
                    is JsonObject -> element
                    else -> null
                }
            }
            products += ProductEntity(productId, displayName, brand, normalize(displayName))
            offers += OfferEntity(
                id = "aldi-nord:$externalId",
                retailerId = id,
                productId = productId,
                categoryId = placement.category,
                externalId = externalId,
                priceCents = cents(price["priceValue"]?.jsonPrimitive?.doubleOrNull ?: return@forEach),
                basePriceCents = base?.get("basePriceValue")?.jsonPrimitive?.doubleOrNull?.let(::cents),
                baseUnit = base?.get("basePriceScale")?.jsonPrimitive?.contentOrNullIfBlank(),
                depositCents = item["depositValue"]?.jsonPrimitive?.doubleOrNull
                    ?.takeIf { item["isDepositProduct"]?.jsonPrimitive?.content == "true" }?.let(::cents),
                validFrom = placement.from.toString(),
                validUntil = placement.until.toString(),
                sourceUrl = pageUrl,
                imageUrl = image,
                cachedAt = System.currentTimeMillis(),
            )
        }
        ProviderResult(products.distinctBy { it.id }, offers.distinctBy { it.id })
    }

    private data class Placement(val category: String, val from: LocalDate, val until: LocalDate)

    private fun placements(groups: List<kotlinx.serialization.json.JsonElement>): Map<String, Placement> {
        val result = linkedMapOf<String, Placement>()
        groups.forEach { rawGroup ->
            val group = rawGroup.jsonObject
            val from = text(group, "startDate")?.let(LocalDate::parse) ?: return@forEach
            val until = text(group, "endDate")?.let(LocalDate::parse) ?: return@forEach
            if (today() !in from..until) return@forEach
            group["content"]?.jsonArray.orEmpty().forEach { rawCategory ->
                val category = rawCategory.jsonObject
                val label = text(category, "title", "teaserTitle") ?: "Weitere Angebote"
                category["productIds"]?.jsonArray.orEmpty().forEach { id ->
                    result.putIfAbsent(id.jsonPrimitive.content, Placement(label, from, until))
                }
            }
        }
        return result
    }

    private fun currentPrice(item: JsonObject, placement: Placement): JsonObject? {
        val active = item["promotionPrices"]?.jsonArray.orEmpty().firstOrNull { raw ->
            val price = raw.jsonObject
            val from = text(price, "validFromLocalDate")?.let(LocalDate::parse)
            val until = text(price, "validUntilLocalDate")?.let(LocalDate::parse)
            from == null || until == null || today() in from..until
        }?.jsonObject
        return active ?: item["currentPrice"]?.jsonObject
            ?.takeIf { placement.from <= today() && today() <= placement.until }
    }

    private fun text(obj: JsonObject, vararg keys: String): String? = keys.asSequence()
        .mapNotNull { key -> runCatching { obj[key]?.jsonPrimitive?.content?.trim() }.getOrNull() }
        .firstOrNull { it.isNotBlank() }

    private fun JsonPrimitive.contentOrNullIfBlank(): String? = content.trim().takeIf(String::isNotBlank)
    private fun cents(value: Double): Int = BigDecimal.valueOf(value).movePointRight(2)
        .setScale(0, RoundingMode.HALF_UP).intValueExact()
    private fun normalize(value: String): String = value.lowercase()
        .replace("[^a-z0-9äöüß]+".toRegex(), "-").trim('-')
}
