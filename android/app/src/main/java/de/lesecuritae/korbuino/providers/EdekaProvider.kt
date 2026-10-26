package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import java.time.DayOfWeek
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import kotlin.math.roundToInt

/**
 * EDEKA's own market search and offer service, local to the postal code.
 *
 * EDEKA answers plain HTTP clients with an anti-bot 403, so this provider
 * works in two ways and needs no Google services for either:
 *  - a page rendered in the user's WebView hands its JSON answer over
 *    through [EdekaHandoffStore] (see `ChallengeActivity`), or
 *  - the direct request is tried, which succeeds wherever EDEKA does not
 *    block it and otherwise fails with the 403 that makes the app offer the
 *    user-mediated confirmation.
 * Like the server adapter it tries the markets of the postal code first and
 * then the nearest ones until one lists offers with a price.
 */
class EdekaProvider(
    private val http: OkHttpClient = OkHttpClient(),
    private val marketApi: String = "https://www.edeka.de/api/marketsearch/markets",
    private val offersApi: String = "https://www.edeka.de/eh/service/eh/offers",
    private val today: () -> LocalDate = { LocalDate.now(BERLIN) },
    private val handoff: (String) -> String? = EdekaHandoffStore::consume,
    private val now: () -> Long = System::currentTimeMillis,
) : RetailerProvider {
    override val id = "edeka"
    override val displayName = "EDEKA"

    @Volatile private var lastPostalCode: String? = null

    /** Carries the postal code so the confirmation screen can fetch for it. */
    override val challengeUrl: String
        get() = lastPostalCode?.let { "$CHALLENGE_PAGE?$POSTAL_PARAMETER=$it" } ?: CHALLENGE_PAGE

    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(POSTAL.matches(request.postalCode)) { "Ungültige PLZ" }
        lastPostalCode = request.postalCode
        val reference = referenceDate(request.week)
        handoff(request.postalCode)?.let { return@withContext fromHandoff(it, reference) }
        fromNetwork(request.postalCode, reference)
    }

    // ---------------------------------------------------------------- handoff

    private fun fromHandoff(raw: String, reference: LocalDate): ProviderResult {
        val root = json.parseToJsonElement(raw).jsonObject
        root.text("error")?.let { error(it) }
        val market = root["market"] as? JsonObject ?: error("EDEKA: die Browser-Antwort enthielt keinen Markt")
        val offers = root["offers"] ?: error("EDEKA: die Browser-Antwort enthielt keine Angebote")
        val marketId = marketId(market) ?: error("EDEKA: der Markt hatte keine Kennung")
        val result = parseOffers(offers, marketId, marketUrl(market), reference)
        check(result.offers.isNotEmpty()) { "EDEKA Markt $marketId lieferte keine preislich verwertbaren Angebote" }
        return result
    }

    // ---------------------------------------------------------------- network

    private fun fromNetwork(postalCode: String, reference: LocalDate): ProviderResult {
        val url = marketApi.toHttpUrl().newBuilder()
            .addQueryParameter("size", "100")
            .addQueryParameter("searchstring", postalCode)
            .build()
        val candidates = candidateMarkets(getJson(url.toString()), postalCode)
        check(candidates.isNotEmpty()) { "EDEKA fand für PLZ $postalCode keinen nutzbaren Markt" }

        val problems = mutableListOf<String>()
        for (market in candidates) {
            val marketId = marketId(market) ?: continue
            val offersUrl = offersApi.toHttpUrl().newBuilder()
                .addQueryParameter("marketId", marketId)
                .addQueryParameter("limit", "99999")
                .build()
            val result = runCatching { parseOffers(getJson(offersUrl.toString()), marketId, marketUrl(market), reference) }
                .getOrElse { failure ->
                    // A blocked request applies to every market: let it surface as the
                    // 403 that offers the confirmation instead of hiding it.
                    if (failure.message.orEmpty().contains("HTTP 403") || failure.message.orEmpty().contains("HTTP 429")) throw failure
                    problems += "Markt $marketId: ${failure.message}"
                    null
                }
            if (result != null && result.offers.isNotEmpty()) return result
            if (result != null) problems += "Markt $marketId: keine preislich verwertbaren Angebote"
        }
        error(
            "EDEKA: ${candidates.size} Märkte in der Nähe von $postalCode geprüft, " +
                "keiner lieferte Angebote mit Preisen (${problems.take(3).joinToString("; ")})",
        )
    }

    private fun getJson(url: String): JsonElement {
        val call = Request.Builder().url(url)
            .header("Accept", "application/json")
            .header("Referer", "https://www.edeka.de/")
            .header("User-Agent", USER_AGENT)
            .build()
        http.newCall(call).execute().use { response ->
            check(response.isSuccessful) { "EDEKA HTTP ${response.code}" }
            return json.parseToJsonElement(response.body?.string().orEmpty())
        }
    }

    // ------------------------------------------------------------------ markets

    /** Markets to try, best first: exact postal code, then the nearest. */
    internal fun candidateMarkets(payload: JsonElement, postalCode: String): List<JsonObject> {
        val usable = markets(payload).filter { marketId(it) != null }
        val exact = usable.filter { postalOf(it) == postalCode }
        val rest = usable.filter { postalOf(it) != postalCode }
        return (exact + rest).distinctBy { marketId(it) }.take(MAX_MARKET_CANDIDATES)
    }

    private fun markets(payload: JsonElement): List<JsonObject> {
        val list = when (payload) {
            is JsonArray -> payload
            is JsonObject -> listOf("markets", "docs", "results", "items").firstNotNullOfOrNull { payload[it] as? JsonArray }
            else -> null
        }
        return list.orEmpty().filterIsInstance<JsonObject>()
    }

    private fun marketId(market: JsonObject): String? =
        market.text("id", "marketId", "marketID", "wwIdent")

    private fun postalOf(market: JsonObject): String {
        val city = ((market["contact"] as? JsonObject)?.get("address") as? JsonObject)?.get("city") as? JsonObject
        return city?.text("zipCode") ?: market.text("zipCode_keyword", "zipCode").orEmpty()
    }

    private fun marketUrl(market: JsonObject): String {
        val raw = market.text("url", "marketUrl", "detailUrl") ?: return MARKET_SEARCH_URL
        return when {
            raw.startsWith("http://") || raw.startsWith("https://") -> raw
            raw.startsWith("//") -> "https:$raw"
            raw.startsWith("/") -> "https://www.edeka.de$raw"
            else -> "https://www.edeka.de/$raw"
        }
    }

    // ------------------------------------------------------------------- offers

    internal fun parseOffers(payload: JsonElement, marketId: String, marketUrl: String, reference: LocalDate): ProviderResult {
        val root = payload as? JsonObject
        val docs = when (payload) {
            is JsonObject -> payload["docs"] as? JsonArray
            is JsonArray -> payload
            else -> null
        }.orEmpty().filterIsInstance<JsonObject>()

        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        docs.forEachIndexed { index, doc ->
            // EDEKA sends explicit nulls, so "first value that is really there" must
            // skip them rather than stop at the first present key.
            val start = dateOf(firstValue(doc["gueltig_von"], doc["validFrom"], root?.get("gueltig_von"), root?.get("validFrom")))
            val end = dateOf(firstValue(doc["gueltig_bis"], doc["validUntil"], root?.get("gueltig_bis"), root?.get("validUntil")))
            if ((start != null && reference < start) || (end != null && reference > end)) return@forEachIndexed

            val title = clean(doc.text("titel")) ?: return@forEachIndexed
            val price = ProviderParsing.price(doc.text("preis"))?.takeIf { it > 0 } ?: return@forEachIndexed
            val rawId = doc.text("angebotid", "externeid") ?: index.toString()
            val (basePrice, baseUnit) = baseOf(doc.text("basicPrice"))
            val productId = "edeka-product-$marketId-$rawId"

            products += ProductEntity(productId, title, normalizedKey = slug(title))
            offers += OfferEntity(
                id = "$id:$marketId:$rawId",
                retailerId = id,
                productId = productId,
                externalId = "$marketId:$rawId",
                priceCents = (price * 100).roundToInt(),
                basePriceCents = basePrice,
                baseUnit = baseUnit,
                validFrom = start?.toString(),
                validUntil = end?.toString(),
                sourceUrl = marketUrl,
                imageUrl = imageOf(doc),
                cachedAt = now(),
            )
        }
        return ProviderResult(products.distinctBy { it.id }, offers.distinctBy { it.id }, storeId = marketId)
    }

    private fun imageOf(doc: JsonObject): String? = listOf("bild_app", "bild_web130", "bild_web90")
        .mapNotNull { doc.text(it) }
        .map {
            when {
                it.startsWith("//") -> "https:$it"
                it.startsWith("/") -> "https://www.edeka.de$it"
                else -> it
            }
        }
        .firstOrNull { it.startsWith("https://") }

    /** "1 kg = 2,98" style unit price texts. */
    private fun baseOf(text: String?): Pair<Int?, String?> {
        val match = BASE_PRICE.find(text.orEmpty()) ?: return null to null
        val price = ProviderParsing.price(match.groupValues[3]) ?: return null to null
        val amount = match.groupValues[1].ifBlank { "1" }
        val unit = match.groupValues[2].lowercase()
        return (price * 100).roundToInt() to if (amount == "1") unit else "$amount $unit"
    }

    private fun firstValue(vararg values: JsonElement?): JsonElement? = values.firstOrNull { it != null && it !is JsonNull }

    private fun dateOf(value: JsonElement?): LocalDate? {
        val primitive = value as? JsonPrimitive ?: return null
        if (primitive is JsonNull) return null
        primitive.content.toDoubleOrNull()?.let { number ->
            val millis = if (number > 10_000_000_000.0) number.toLong() else (number * 1000).toLong()
            return Instant.ofEpochMilli(millis).atZone(BERLIN).toLocalDate()
        }
        return runCatching { LocalDate.parse(primitive.content.take(10)) }.getOrNull()
    }

    private fun referenceDate(week: OfferWeek): LocalDate {
        val current = today().let { if (it.dayOfWeek == DayOfWeek.SUNDAY) it.plusDays(1) else it }
        return if (week == OfferWeek.NEXT) current.plusDays(7) else current
    }

    private fun clean(value: String?): String? = value?.replace(Regex("\\s+"), " ")?.trim()?.takeIf { it.isNotBlank() }

    private fun slug(value: String): String = value.lowercase().replace("[^a-z0-9]+".toRegex(), "-").trim('-')

    private fun JsonObject.text(vararg keys: String): String? = keys.asSequence()
        .mapNotNull { key -> (this[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull?.trim() }
        .firstOrNull { it.isNotBlank() }

    companion object {
        const val MAX_MARKET_CANDIDATES = 6
        const val POSTAL_PARAMETER = "korbuino_plz"
        const val CHALLENGE_PAGE = "https://www.edeka.de/marktsuche.jsp"
        private const val MARKET_SEARCH_URL = CHALLENGE_PAGE
        private const val USER_AGENT =
            "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36"
        private val BERLIN: ZoneId = ZoneId.of("Europe/Berlin")
        private val POSTAL = Regex("^\\d{5}$")
        private val BASE_PRICE = Regex("(\\d+)?\\s*(kg|g|l|ml)\\s*=\\s*([\\d.,]+)", RegexOption.IGNORE_CASE)
    }
}
