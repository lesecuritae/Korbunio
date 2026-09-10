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
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import java.math.BigDecimal
import java.math.RoundingMode
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
    providerId: String? = null,
    providerDisplayName: String? = null,
    private val advertiserUniqueName: String = advertiserSlug(retailerName),
) : RetailerProvider {
    override val id: String = providerId ?: "marktguru-${slug(retailerName)}"
    override val displayName: String = providerDisplayName ?: "$retailerName (regional)"
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
            val advertisers = item["advertisers"]?.jsonArray.orEmpty()
            if (advertisers.isNotEmpty() && advertisers.none { advertiser ->
                    advertiser.jsonObject["uniqueName"]?.jsonPrimitive?.content
                        ?.equals(advertiserUniqueName, ignoreCase = true) == true
                }
            ) return@forEachIndexed
            val product = item["product"]?.jsonObject ?: item
            val name = text(product, "name", "title", "productName") ?: return@forEachIndexed
            val advertisedPrice = number(item, "price", "currentPrice", "regularPrice")
                ?: number(product, "price", "currentPrice") ?: return@forEachIndexed
            val pricing = pricing(item, advertisedPrice)
            val external = text(item, "id", "offerId") ?: "$index-${slug(name)}"
            val productId = "$id-product-${slug(name)}"
            val image = ProviderParsing.imageUrl(item, product)
            val loyalty = pricing.loyalty
            products += ProductEntity(productId, name, normalizedKey = slug(name))
            offers += OfferEntity(
                id = "$id:$external", retailerId = id, productId = productId,
                externalId = external,
                priceCents = BigDecimal.valueOf(pricing.regularPrice).movePointRight(2)
                    .setScale(0, RoundingMode.HALF_UP).intValueExact(),
                sourceUrl = "https://www.marktguru.de/", imageUrl = image,
                loyaltyProgram = loyalty?.first,
                loyaltyLabel = loyalty?.second,
                loyaltyPriceCents = loyalty?.third,
                cachedAt = System.currentTimeMillis(),
            )
        }
        return ProviderResult(products.distinctBy { it.id }, offers.distinctBy { it.id })
    }

    private fun text(obj: JsonObject, vararg keys: String): String? = keys.asSequence()
        .mapNotNull { key -> runCatching { obj[key]?.jsonPrimitive?.content?.trim() }.getOrNull() }
        .firstOrNull { it.isNotBlank() }

    private fun number(obj: JsonObject, vararg keys: String): Double? = ProviderParsing.price(text(obj, *keys))

    private data class Pricing(
        val regularPrice: Double,
        val loyalty: Triple<String, String, Int>?,
    )

    private data class LoyaltyDefinition(
        val marker: Regex,
        val directPrice: Regex,
        val publicPrice: Regex,
        val program: String,
        val label: String,
    )

    private fun pricing(item: JsonObject, advertisedPrice: Double): Pricing {
        val description = text(item, "description").orEmpty()
        val definitions = listOf(
            loyaltyDefinition("NETTO\\s+PLUS\\s+APP", "netto_plus", "Netto Plus App"),
            loyaltyDefinition("LIDL\\s+PLUS(?:\\s+APP)?", "lidl_plus", "Lidl Plus"),
            loyaltyDefinition("PENNY\\s+APP", "penny_app", "PENNY App"),
            loyaltyDefinition("KAUFLAND\\s+CARD\\s+XTRA", "kaufland_xtra", "Kaufland Card XTRA"),
            loyaltyDefinition("MEIN\\s+GLOBUS", "mein_globus", "Mein Globus"),
        )
        val definition = definitions.firstOrNull { it.marker.containsMatchIn(description) }
            ?: return Pricing(advertisedPrice, null)

        val directMemberPrice = ProviderParsing.price(
            definition.directPrice.find(description)?.groupValues?.get(1),
        )
        if (directMemberPrice != null && directMemberPrice > 0.0 && directMemberPrice < advertisedPrice) {
            return Pricing(advertisedPrice, definition.benefit(directMemberPrice))
        }

        val requiresMembership = item["requiresLoyalityMembership"]?.jsonPrimitive?.booleanOrNull == true
        if (requiresMembership) {
            val publicPrice = ProviderParsing.price(
                definition.publicPrice.find(description)?.groupValues?.get(1),
            )
            if (publicPrice != null && publicPrice > advertisedPrice) {
                return Pricing(publicPrice, definition.benefit(advertisedPrice))
            }
        }
        return Pricing(advertisedPrice, null)
    }

    private fun loyaltyDefinition(marker: String, program: String, label: String): LoyaltyDefinition =
        LoyaltyDefinition(
            marker = Regex(marker, RegexOption.IGNORE_CASE),
            directPrice = Regex("$marker\\s*[:=-]?\\s*(\\d{1,4}[,.]\\d{2})(?:\\s*€)?", RegexOption.IGNORE_CASE),
            publicPrice = Regex(
                "(?:NORMALPREIS\\s*:|OHNE\\s+$marker)\\s*(\\d{1,4}[,.]\\d{2})(?:\\s*€)?",
                RegexOption.IGNORE_CASE,
            ),
            program = program,
            label = label,
        )

    private fun LoyaltyDefinition.benefit(price: Double): Triple<String, String, Int> {
        val cents = BigDecimal.valueOf(price).movePointRight(2)
            .setScale(0, RoundingMode.HALF_UP).intValueExact()
        return Triple(program, label, cents)
    }

    private fun firstKey(html: String, vararg names: String): String? = names.asSequence()
        .mapNotNull { name -> Regex("[\\\"']$name[\\\"']\\s*[:=]\\s*[\\\"']([^\\\"']+)").find(html)?.groupValues?.get(1) }
        .firstOrNull { it.isNotBlank() }

    private fun slug(value: String): String = value.lowercase(Locale.GERMAN).replace("[^a-z0-9]+".toRegex(), "-").trim('-')

    companion object {
        private fun advertiserSlug(value: String): String = value.lowercase(Locale.GERMAN)
            .replace("ä", "a")
            .replace("ö", "o")
            .replace("ü", "u")
            .replace("ß", "ss")
            .replace("[^a-z0-9]+".toRegex(), "-")
            .trim('-')
    }
}
