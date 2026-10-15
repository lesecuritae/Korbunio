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
import okhttp3.OkHttpClient
import okhttp3.Request
import java.math.BigDecimal
import java.math.RoundingMode
import java.net.URI
import java.text.Normalizer
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.util.Locale

/**
 * Kaufland's weekly offers with the prices of the store's region.
 *
 * Kaufland prices differ by region (the same cheese costs 1.59 in Sachsen and 1.79 in
 * Essen). The offer overview renders for the store named in the `x-aem-variant` cookie,
 * so the store must match the requested postal code. An explicit market is
 * validated against the public store details before requesting regional prices.
 */
class KauflandProvider(
    private val http: OkHttpClient = OkHttpClient(),
    private val baseUrl: String = "https://filiale.kaufland.de",
    private val now: () -> Instant = Instant::now,
) : RetailerProvider {
    override val id = "kaufland"
    override val displayName = "Kaufland"
    override val challengeUrl: String get() = overviewUrl

    private val overviewUrl get() = "$baseUrl/angebote/uebersicht.html?kloffer-week=current"
    private val json = Json { ignoreUnknownKeys = true }
    private val berlin = ZoneId.of("Europe/Berlin")
    private val storeCache = java.util.concurrent.ConcurrentHashMap<String, String>()
    @Volatile private var sitemapCache: Pair<Long, List<Pair<String, String>>>? = null
    private data class DateWindow(val from: LocalDate, val until: LocalDate) {
        fun overlaps(other: DateWindow): Boolean = !from.isAfter(other.until) && !until.isBefore(other.from)
    }
    private fun weekWindow(today: LocalDate, week: OfferWeek): DateWindow {
        val sunday = today.with(java.time.temporal.TemporalAdjusters.nextOrSame(java.time.DayOfWeek.SUNDAY))
        return if (week == OfferWeek.NEXT) DateWindow(sunday.plusDays(1), sunday.plusDays(7)) else DateWindow(today, sunday)
    }
    private fun dates(obj: JsonObject): DateWindow? = runCatching {
        val from = LocalDate.parse(text(obj, "dateFrom"))
        val until = LocalDate.parse(text(obj, "dateTo"))
        val salesFrom = text(obj, "salesFrom")?.let { LocalDate.parse(it) } ?: from
        val salesTo = text(obj, "salesTo")?.let { LocalDate.parse(it) } ?: until
        DateWindow(maxOf(from, salesFrom), minOf(until, salesTo))
    }.getOrNull()?.takeIf { !it.from.isAfter(it.until) }

    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(Regex("^\\d{5}$").matches(request.postalCode)) { "Ungültige PLZ" }
        val city = request.citySlug?.trim().orEmpty()
        val explicit = request.marketId?.trim()?.takeIf { it.isNotBlank() }
        val store = if (explicit != null) {
            require(Regex("DE\\d+").matches(explicit)) { "Ungültige Kaufland-Filiale" }
            check(storePostalCode(explicit) == request.postalCode) { "Kaufland-Filiale passt nicht zur PLZ" }
            explicit
        } else {
            check(city.isNotBlank()) { "Für die regionalen Kaufland-Preise wird die Stadt benötigt" }
            findStore(request.postalCode, city) ?: error("Keine Kaufland-Filiale für die PLZ gefunden")
        }
        val today = now().atZone(berlin).toLocalDate()
        val window = weekWindow(today, request.week)
        val available = availableArticles(store, window)
        val url = "$baseUrl/angebote/uebersicht.html?kloffer-week=${if (request.week == OfferWeek.NEXT) "next" else "current"}"
        val page = get(url, cookie = "x-aem-variant=$store")
        val result = parseWindow(page, available, window, url)
        if (request.week == OfferWeek.CURRENT) {
            check(result.offers.size >= MIN_OFFERS) { "Kaufland-Angebote für $store lieferten nur ${result.offers.size} Treffer" }
        }
        result.copy(storeId = store)
    }

    // ---- store lookup ------------------------------------------------------------

    private fun findStore(postalCode: String, city: String): String? {
        val key = "$baseUrl|$postalCode|${city.lowercase(Locale.GERMAN)}"
        storeCache[key]?.let { return it }
        val words = slugWords(city)
        if (words.isEmpty()) return null
        val candidates = storeIds().filter { (slug, _) -> slugWords(slug).containsAll(words) }.map { it.second }
        val store = candidates.take(MAX_CANDIDATES).firstOrNull { storePostalCode(it) == postalCode }
        if (store != null) storeCache[key] = store
        return store
    }

    /** (slug, "DE1234") of every store in the sitemap; the sitemap is large, so it is kept for a day. */
    private fun storeIds(): List<Pair<String, String>> {
        val cached = sitemapCache
        if (cached != null && now().toEpochMilli() - cached.first < DAY_MS) return cached.second
        val xml = get("$baseUrl/.sitemap.xml")
        val stores = STORE_URL.findAll(xml).map { it.groupValues[1] to "DE" + it.groupValues[2] }.distinctBy { it.second }.toList()
        check(stores.isNotEmpty()) { "Kaufland-Filialverzeichnis ist leer" }
        sitemapCache = now().toEpochMilli() to stores
        return stores
    }

    private fun storePostalCode(store: String): String? = runCatching {
        json.parseToJsonElement(get("$baseUrl/.klstorebygeo.storeName=$store.json", cookie = "x-aem-variant=$store")).jsonObject
            .get("pc")?.jsonPrimitive?.content
    }.getOrNull()

    // ---- offers ------------------------------------------------------------------

    private fun availableArticles(store: String, window: DateWindow): Map<String, List<DateWindow>> {
        val list = json.parseToJsonElement(get("$baseUrl/.kloffers.storeName=$store.json", cookie = "x-aem-variant=$store")) as? JsonArray
            ?: error("Kaufland-Verfügbarkeitsdaten haben ein unerwartetes Format")
        return list.mapNotNull { it as? JsonObject }.mapNotNull { item ->
            val interval = dates(item)?.takeIf { it.overlaps(window) } ?: return@mapNotNull null
            text(item, "klNr")?.let { it to interval }
        }.groupBy({ it.first }, { it.second })
    }

    internal fun parse(page: String, available: Set<String>, today: LocalDate): ProviderResult {
        val window = DateWindow(today, today)
        return parseWindow(page, available.associateWith { listOf(window) }, window, overviewUrl)
    }

    private fun parseWindow(page: String, available: Map<String, List<DateWindow>>, window: DateWindow, sourceUrl: String): ProviderResult {
        val start = page.indexOf(MARKER)
        check(start >= 0) { "Kaufland-Angebotsseite enthält keine strukturierten Angebotsdaten" }
        val end = objectEnd(page, start)
        check(end > start) { "Kaufland-Angebotsdaten sind unvollständig" }
        val cycles = json.parseToJsonElement(page.substring(start, end)).jsonObject["props"]?.jsonObject
            ?.get("offerData")?.jsonObject?.get("cycles")?.jsonArray
            ?: error("Kaufland-Angebotsdaten haben ein unerwartetes Format")

        val seen = HashSet<String>()
        val products = linkedMapOf<String, ProductEntity>()
        val offers = linkedMapOf<String, OfferEntity>()
        // The later cycle holds the Card XTRA variants of the same offer IDs; going through it
        // first keeps the member price while the shelf price stays the regular price.
        for (cycle in cycles.reversed()) {
            val categories = (cycle as? JsonObject)?.get("categories") as? JsonArray ?: continue
            for (category in categories.mapNotNull { it as? JsonObject }) {
                val categoryName = text(category, "displayName") ?: "Kaufland Filialangebote"
                for (raw in (category["offers"] as? JsonArray).orEmpty().mapNotNull { it as? JsonObject }) {
                    val klNr = text(raw, "klNr") ?: continue
                    if (klNr !in available) continue
                    val rawWindow = dates(raw)?.takeIf { it.overlaps(window) } ?: continue
                    val from = rawWindow.from.toString()
                    val until = rawWindow.until.toString()
                    if (available[klNr].orEmpty().none { availability ->
                        val intersect = DateWindow(maxOf(rawWindow.from, window.from), minOf(rawWindow.until, window.until))
                        availability.overlaps(intersect)
                    }) continue
                    val offerId = text(raw, "offerId") ?: continue
                    if (offerId in seen) continue
                    val title = text(raw, "title").orEmpty()
                    val subtitle = text(raw, "subtitle").orEmpty()
                    val name = "$title $subtitle".trim().replace(Regex("\\s+"), " ")
                    val price = cents(text(raw, "formattedPrice") ?: text(raw, "price")) ?: continue
                    if (name.isBlank() || price <= 0) continue
                    seen.add(offerId)
                    val loyalty = cents(text(raw, "loyaltyFormattedPrice")?.replace(Regex("[^\\d,.-]"), ""))
                        ?.takeIf { it in 1 until price }
                    val messages = (raw["bbyMessage"] as? JsonArray).orEmpty()
                        .mapNotNull { (it as? kotlinx.serialization.json.JsonPrimitive)?.content }
                    // Verified public bbyMessage shape: ["3 Stück", "entspr. pro Stück 1.00"].
                    // bonusbuy alone also identifies Card prices and is not quantity evidence.
                    val bundleQuantity = messages.firstOrNull()?.let { MULTI_BUY_COUNT.matchEntire(it.trim()) }
                        ?.groupValues?.get(1)?.toIntOrNull()?.takeIf { it > 1 }
                    val restriction = text(raw, "detailTitle")?.takeIf {
                        Regex("card|karte|coupon|kupon|aktivier|mitglied|xtra|\\bapp\\b", RegexOption.IGNORE_CASE).containsMatchIn(it)
                    }
                    val bundleCondition = (messages + listOfNotNull(restriction)).joinToString(" · ")
                    val requiresCard = messages.isNotEmpty() && restriction?.let {
                        Regex("card|karte|xtra", RegexOption.IGNORE_CASE).containsMatchIn(it)
                    } == true
                    val (baseCents, baseUnit) = basePrice(text(raw, "formattedBasePrice") ?: text(raw, "basePrice"))
                    val productId = "kaufland-product-" + normalize(name)
                    products[productId] = ProductEntity(productId, name, if (subtitle.isNotBlank()) title else "", normalize(name))
                    offers[offerId] = OfferEntity(
                        id = "kaufland:$offerId",
                        retailerId = id,
                        productId = productId,
                        categoryId = categoryName,
                        externalId = offerId,
                        priceCents = price,
                        basePriceCents = baseCents,
                        baseUnit = baseUnit,
                        validFrom = from,
                        validUntil = until,
                        sourceUrl = sourceUrl,
                        imageUrl = image(text(raw, "listImage")),
                        loyaltyProgram = if (loyalty != null || requiresCard) "kaufland_xtra" else null,
                        loyaltyLabel = if (loyalty != null) "Kaufland Card XTRA" else null,
                        loyaltyPriceCents = loyalty,
                        cachedAt = now().toEpochMilli(),
                        multiBuyQuantity = bundleQuantity,
                        multiBuyTotalCents = price.takeIf { messages.isNotEmpty() },
                        multiBuyCondition = bundleCondition.takeIf { messages.isNotEmpty() },
                        // bbyNo identifies an action, not proof that different articles may mix.
                        multiBuyMixGroup = null,
                        singlePriceCents = null,
                        packSize = PACK_SIZE.find(text(raw, "unit").orEmpty())?.let { "${it.groupValues[1]} ${it.groupValues[2].lowercase(Locale.ROOT)}" },
                    )
                }
            }
        }
        return ProviderResult(products.values.toList(), offers.values.toList())
    }

    // ---- helpers -----------------------------------------------------------------

    private fun get(url: String, cookie: String? = null): String {
        val builder = Request.Builder().url(url)
            .header("Accept", "text/html,application/json;q=0.9,*/*;q=0.8")
            .header("Accept-Language", "de-DE,de;q=0.9")
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36")
        if (cookie != null) builder.header("Cookie", cookie)
        http.newCall(builder.build()).execute().use { response ->
            check(response.isSuccessful) { "Kaufland HTTP ${response.code}" }
            return response.body?.string().orEmpty()
        }
    }

    private fun text(obj: JsonObject, key: String): String? =
        (obj[key] as? kotlinx.serialization.json.JsonPrimitive)?.content?.trim()?.ifBlank { null }

    /** "1.59" or "1,59" -> 159 */
    private fun cents(value: String?): Int? =
        value?.trim()?.replace(',', '.')?.toBigDecimalOrNull()?.movePointRight(2)?.setScale(0, RoundingMode.HALF_UP)?.toInt()

    /** "(1 kg = 7.95 - 10.60)" -> 795 cents per kg; a range takes its lower end. */
    private fun basePrice(value: String?): Pair<Int?, String?> {
        val match = BASE_PRICE.find(value.orEmpty()) ?: return null to null
        val unit = match.groupValues[1].lowercase(Locale.ROOT).replace(" ", "")
        val amount = match.groupValues[2].replace(',', '.').let { BigDecimal(it) }
        return amount.movePointRight(2).setScale(0, RoundingMode.HALF_UP).toInt() to unit
    }

    private fun image(url: String?): String? {
        if (url.isNullOrBlank()) return null
        return runCatching { URI(baseUrl).resolve(url).toString() }.getOrNull()?.takeIf { it.startsWith("http") }
    }

    /** End index of the JSON object that starts at [start], honouring strings and escapes. */
    private fun objectEnd(text: String, start: Int): Int {
        var depth = 0
        var inString = false
        var escaped = false
        for (i in start until text.length) {
            val c = text[i]
            if (inString) {
                when {
                    escaped -> escaped = false
                    c == '\\' -> escaped = true
                    c == '"' -> inString = false
                }
            } else when (c) {
                '"' -> inString = true
                '{' -> depth++
                '}' -> if (--depth == 0) return i + 1
            }
        }
        return -1
    }

    private fun slugWords(value: String): Set<String> = Normalizer.normalize(
        value.lowercase(Locale.GERMAN).replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"),
        Normalizer.Form.NFKD,
    ).replace("\\p{M}".toRegex(), "").split(Regex("[^a-z0-9]+")).filter { it.isNotBlank() }.toSet()

    private fun normalize(value: String): String = Normalizer.normalize(
        value.lowercase(Locale.GERMAN),
        Normalizer.Form.NFKD,
    ).replace("\\p{M}".toRegex(), "").replace("[^a-z0-9]+".toRegex(), "-").trim('-')

    private companion object {
        const val MARKER = "{\"component\":\"OfferTemplate\""
        const val MIN_OFFERS = 100
        const val MAX_CANDIDATES = 10
        const val DAY_MS = 24L * 60 * 60 * 1000
        val STORE_URL = Regex("<loc>[^<]*/service/filiale/([^<]*?)-(\\d+)\\.html</loc>")
        val MULTI_BUY_COUNT = Regex("(\\d+)\\s+Stück", RegexOption.IGNORE_CASE)
        val PACK_SIZE = Regex("(\\d+(?:[.,]\\d+)?)[\\s-]*(kg|ml|g|l)\\b", RegexOption.IGNORE_CASE)
        val BASE_PRICE = Regex("1\\s*(kg|l|100\\s*g|100\\s*ml|st|m)\\s*=\\s*(\\d+[.,]\\d+)", RegexOption.IGNORE_CASE)
    }
}
