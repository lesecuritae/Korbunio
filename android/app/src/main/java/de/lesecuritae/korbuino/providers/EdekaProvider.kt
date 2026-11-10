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
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
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
    private val publicBaseUrl: String = "https://www.edeka.de",
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
            val legacy = runCatching { parseOffers(getJson(offersUrl.toString()), marketId, marketUrl(market), reference) }
            val result = legacy.getOrNull()
            val actualUrl = marketUrl(market)
            val parsed = runCatching { actualUrl.toHttpUrl() }.getOrNull()
            val base = publicBaseUrl.toHttpUrl()
            if (parsed != null && parsed.host == base.host && parsed.scheme == base.scheme &&
                (parsed.encodedPath.startsWith("/eh/") || parsed.encodedPath.startsWith("/maerkte/"))) {
                try {
                    val page = org.jsoup.Jsoup.parse(getHtml(actualUrl), actualUrl)
                    val links = page.select("a[href]").mapNotNull { a ->
                        runCatching { a.absUrl("href").toHttpUrl() }.getOrNull()?.takeIf {
                            it.host == base.host && it.scheme == base.scheme && it.encodedPath.matches(Regex("""/maerkte/\d+/angebote/?""")) && it.query == null
                        }?.newBuilder()?.fragment(null)?.build()?.toString()?.trimEnd('/')
                    }.distinct()
                    check(links.size == 1) { "EDEKA: kein eindeutiger Angebotslink des gewählten Marktes" }
                    val source = links.single() + "/"
                    val modern = parseOffers(EdekaHtmlOffers.parse(getHtml(source), source), marketId, source, reference)
                    if (modern.offers.isNotEmpty()) return if (result != null) preserveOfferIds(result, modern) else modern
                } catch (failure: Exception) {
                    if (failure is kotlinx.coroutines.CancellationException) throw failure
                    if (result != null && result.offers.isNotEmpty()) return result.copy(sourceWarnings = listOf("EDEKA: öffentliche Marktanzeige nicht abgeglichen; API-Angebote beibehalten (${failure.javaClass.simpleName})."), preserveMissingOffers = true)
                    problems += "Markt $marketId: ${failure.message}"
                }
            }
            if (result != null && result.offers.isNotEmpty()) return result
            legacy.exceptionOrNull()?.let { failure ->
                if (failure is kotlinx.coroutines.CancellationException) throw failure
                // Only a successful selected-market page can replace a denied API.
                if (failure.message.orEmpty().contains("HTTP 403") || failure.message.orEmpty().contains("HTTP 429")) throw failure
                problems += "Markt $marketId: ${failure.message}"
            }
            if (result != null) problems += "Markt $marketId: keine preislich verwertbaren Angebote"
        }
        error(
            "EDEKA: ${candidates.size} Märkte in der Nähe von $postalCode geprüft, " +
                "keiner lieferte Angebote mit Preisen (${problems.take(3).joinToString("; ")})",
        )
    }

    internal fun preserveOfferIds(previous: ProviderResult, current: ProviderResult): ProviderResult {
        val oldProducts = previous.products.associateBy { it.id }
        val newProducts = current.products.associateBy { it.id }
        fun key(o: OfferEntity, products: Map<String, ProductEntity>): List<Any?> = listOf(
            o.retailerId, products[o.productId]?.name?.trim()?.lowercase(), o.priceCents, o.packSize,
            o.description.trim().lowercase(), o.validFrom, o.validUntil)
        val oldGroups = previous.offers.groupBy { key(it, oldProducts) }
        val newGroups = current.offers.groupBy { key(it, newProducts) }
        val products = linkedMapOf<String, ProductEntity>()
        val offers = current.offers.map { offer ->
            val identity = key(offer, newProducts)
            val old = oldGroups[identity]?.singleOrNull()?.takeIf { newGroups[identity]?.size == 1 }
            val product = newProducts.getValue(offer.productId)
            if (old == null) {
                products[product.id] = product
                offer
            } else {
                products[old.productId] = product.copy(id = old.productId)
                offer.copy(id = old.id, externalId = old.externalId, productId = old.productId,
                    basePriceCents = offer.basePriceCents ?: old.basePriceCents,
                    baseUnit = offer.baseUnit ?: old.baseUnit, imageUrl = offer.imageUrl ?: old.imageUrl)
            }
        }
        return current.copy(products = products.values.toList(), offers = offers)
    }

    private fun getHtml(url: String): String = http.newCall(Request.Builder().url(url)
        .header("Accept", "text/html").header("User-Agent", USER_AGENT).build()).execute().use { response ->
        check(response.isSuccessful) { "EDEKA Marktseite HTTP ${response.code}" }
        val base = publicBaseUrl.toHttpUrl()
        val final = response.request.url
        check(final.host == base.host && final.scheme == base.scheme) { "EDEKA: fremder Ursprung der Marktseite" }
        val requested = url.toHttpUrl()
        if (requested.encodedPath.matches(Regex("""/maerkte/\d+/angebote/?"""))) {
            check(final.encodedPath.trimEnd('/') == requested.encodedPath.trimEnd('/')) { "EDEKA: Angebotsseite verweist auf anderen Markt" }
        }
        val body = response.body?.source() ?: error("EDEKA Marktseite fehlt")
        check(!body.request(5_000_001)) { "EDEKA Marktseite zu groß" }
        body.readUtf8()
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

            val gtins = (doc["gtins"] as? JsonArray).orEmpty().mapNotNull { it.jsonPrimitive.contentOrNull }.distinct()
            products += ProductEntity(productId, title, normalizedKey = slug(title), gtin = gtins.singleOrNull())
            val member = ProviderParsing.price(doc.text("edeka_app_preis"))?.takeIf { it > 0 && it < price }
            offers += OfferEntity(
                id = "$id:$marketId:$rawId",
                retailerId = id,
                productId = productId,
                externalId = "$marketId:$rawId",
                priceCents = ProviderParsing.cents(price),
                loyaltyProgram = member?.let { "edeka_app" }, loyaltyLabel = member?.let { "EDEKA App" },
                loyaltyPriceCents = member?.let(ProviderParsing::cents),
                depositCents = ProviderParsing.depositCents(clean(doc.text("beschreibung")).orEmpty()),
                basePriceCents = basePrice,
                baseUnit = baseUnit,
                validFrom = start?.toString(),
                validUntil = end?.toString(),
                sourceUrl = marketUrl,
                imageUrl = imageOf(doc),
                description = clean(doc.text("beschreibung")).orEmpty(),
                packSize = doc.text("pack_size") ?: ProviderParsing.packSize("$title ${clean(doc.text("beschreibung")).orEmpty()}"),
                multiBuyQuantity = doc["multi_buy_quantity"]?.jsonPrimitive?.intOrNull,
                multiBuyTotalCents = doc["multi_buy_total_cents"]?.jsonPrimitive?.intOrNull,
                singlePriceCents = doc["single_price_cents"]?.jsonPrimitive?.intOrNull,
                multiBuyCondition = doc.text("multi_buy_condition"),
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
