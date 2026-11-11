package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonArray
import okhttp3.HttpUrl.Companion.toHttpUrl
import java.time.ZoneId
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
    private val regionalViewer: Boolean = false,
    private val viewerBaseUrl: String = "https://content-viewer-be.kaufda.de",
    private val geocodeUrl: String = "https://nominatim.openstreetmap.org/search",
    private val publisherViewer: Boolean = false,

) : RetailerProvider {
    private val json = Json { ignoreUnknownKeys = true }
    private val sourceUrl get() = "$baseUrl/Geschaefte/$publisherSlug"
    override val challengeUrl: String get() = sourceUrl

    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(request.postalCode.matches(Regex("^\\d{5}$"))) { "Ungültige PLZ" }
        val html = read(sourceUrl)
        check(!(regionalViewer && publisherViewer)) { "KaufDA: widersprüchlicher Prospektmodus" }
        if (regionalViewer || publisherViewer) fetchRegionalViewer(html, request) else parse(html, request.week)
    }

    private fun parse(html: String, week: OfferWeek): ProviderResult {
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
            if (!selected(validFrom, validUntil, week)) return@forEachIndexed
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
                validFrom = de.lesecuritae.korbuino.BerlinDate.toLocalDate(validFrom.toString()),
                validUntil = de.lesecuritae.korbuino.BerlinDate.toLocalDate(validUntil.toString()),
                sourceUrl = sourceUrl,
                imageUrl = image,
                description = item.text("description").orEmpty(),
                packSize = ProviderParsing.packSize("$name ${item.text("description").orEmpty()}"),
                cachedAt = System.currentTimeMillis(),
            )
        }
        return ProviderResult(products.values.toList(), offers.values.toList())
    }

    private fun selected(start: Instant, end: Instant, week: OfferWeek): Boolean {
        val zone = ZoneId.of("Europe/Berlin")
        return offerWeekContains(start.atZone(zone).toLocalDate(), end.atZone(zone).toLocalDate(), week,
            now().atZone(zone).toLocalDate())
    }

    private fun read(url: String, maximum: Long = 3_000_000): String = http.newCall(
        Request.Builder().url(url).header("Accept", "text/html,application/json")
            .header("User-Agent", "Korbuino (+https://github.com/lesecuritae/Korbunio)").build(),
    ).execute().use { response ->
        check(response.isSuccessful) { "KaufDA HTTP ${response.code}" }
        val source = response.body?.source() ?: error("KaufDA Antwort fehlt")
        check(!source.request(maximum + 1)) { "KaufDA Antwort überschreitet Größenlimit" }
        source.readUtf8()
    }

    private fun fetchRegionalViewer(home: String, request: RetailerRequest): ProviderResult {
        // Resolve the actual postal area; a caller-supplied city alone is no regional proof.
        val geo = geocodeUrl.toHttpUrl().newBuilder().addQueryParameter("postalcode", request.postalCode)
            .addQueryParameter("country", "Germany").addQueryParameter("format", "jsonv2")
            .addQueryParameter("addressdetails", "1").addQueryParameter("limit", "1").build()
        val location = json.parseToJsonElement(read(geo.toString())).jsonArray.firstOrNull()?.jsonObject
            ?: error("KaufDA Ort nicht bestätigt")
        val address = location["address"]?.jsonObject ?: error("KaufDA Ort fehlt")
        val lat = location.text("lat")?.toDoubleOrNull()?.takeIf { it in -90.0..90.0 } ?: error("KaufDA Breite fehlt")
        val lon = location.text("lon")?.toDoubleOrNull()?.takeIf { it in -180.0..180.0 } ?: error("KaufDA Länge fehlt")
        val city = sequenceOf("city", "town", "municipality", "village").mapNotNull { address.text(it) }.firstOrNull()
            ?: error("KaufDA Ort fehlt")
        fun cityKey(value: String) = value.lowercase(Locale.GERMAN).replace("ä", "ae").replace("ö", "oe")
            .replace("ü", "ue").replace("ß", "ss")
        val publisherRoutes = mutableSetOf<String>()
        val candidates = Jsoup.parse(home, sourceUrl).select("a[href]").mapNotNull { link ->
            val url = runCatching { link.absUrl("href").toHttpUrl() }.getOrNull() ?: return@mapNotNull null
            val parts = url.pathSegments
            val requested = cityKey(city).replace(" ", "-")
            if (url.host == baseUrl.toHttpUrl().host && url.scheme == baseUrl.toHttpUrl().scheme && parts.size == 3 &&
                parts[1].equals(publisherSlug, true) && parts[2].matches(Regex("p-r\\d+"))) publisherRoutes += parts[2]
            if (url.host == baseUrl.toHttpUrl().host && url.scheme == baseUrl.toHttpUrl().scheme && parts.size == 3 &&
                (cityKey(parts[0]) == requested || cityKey(parts[0]).startsWith(requested + "-")) &&
                parts[1].equals(publisherSlug, true) && parts[2].matches(Regex("p-r\\d+")))
                url.newBuilder().query(null).fragment(null).build().toString() to (cityKey(parts[0]) == requested) else null
        }.distinctBy { it.first }.toMutableList()
        if (candidates.isEmpty() && publisherRoutes.size == 1) {
            // Routing alias only; the linked page's own coordinates still have
            // to match before any brochure is accepted.
            val aliases = mapOf("oldenburg" to listOf("Oldenburg-Oldb"))
            aliases[cityKey(city).replace(" ", "-")].orEmpty().forEach { alias ->
                val url = baseUrl.toHttpUrl().newBuilder().addPathSegment(alias).addPathSegment(publisherSlug).addPathSegment(publisherRoutes.single()).build()
                candidates += url.toString() to false
            }
        }
        var regionalUrl = sourceUrl
        var regionalHtml = home
        if (!publisherViewer) {
            val exact = candidates.filter { it.second }
            check(candidates.isNotEmpty()) { "KaufDA: kein bestätigter Ortsprospekt für $city" }
            check(exact.isNotEmpty() || candidates.size <= 4) { "KaufDA: Ortsnamen mehrdeutig" }
            val verified = (exact.ifEmpty { candidates }).mapNotNull { candidate ->
                val page = read(candidate.first)
                if (exact.isEmpty()) {
                    val body = Jsoup.parse(page, candidate.first).selectFirst("script#__NEXT_DATA__")?.data()
                    val info = body?.let { runCatching { json.parseToJsonElement(it).jsonObject["props"]?.jsonObject?.get("pageProps")?.jsonObject?.get("pageInformation")?.jsonObject }.getOrNull() }
                    val place = (info?.get("location") ?: info?.get("city")) as? JsonObject
                    val otherLat = place?.text("lat")?.toDoubleOrNull()?.takeIf { it in -90.0..90.0 } ?: return@mapNotNull null
                    val otherLon = place.text("lng")?.toDoubleOrNull()?.takeIf { it in -180.0..180.0 } ?: return@mapNotNull null
                    val dlat = Math.toRadians(otherLat - lat); val dlon = Math.toRadians(otherLon - lon)
                    val a = kotlin.math.sin(dlat / 2) * kotlin.math.sin(dlat / 2) + kotlin.math.cos(Math.toRadians(lat)) * kotlin.math.cos(Math.toRadians(otherLat)) * kotlin.math.sin(dlon / 2) * kotlin.math.sin(dlon / 2)
                    if (6371 * 2 * kotlin.math.asin(kotlin.math.sqrt(a.coerceIn(0.0, 1.0))) > 5) return@mapNotNull null
                }
                candidate.first to page
            }
            check(verified.size == 1) { "KaufDA: kein eindeutiger Ortsnachweis für $city" }
            regionalUrl = verified.single().first; regionalHtml = verified.single().second
        }
        val doc = Jsoup.parse(regionalHtml, regionalUrl)
        val payload = doc.selectFirst("script#__NEXT_DATA__")?.data() ?: error("KaufDA Prospektdaten fehlen")
        val groups = json.parseToJsonElement(payload).jsonObject["props"]?.jsonObject
            ?.get("pageProps")?.jsonObject?.get("pageInformation")?.jsonObject?.get("brochures")?.jsonObject
            ?: error("KaufDA Prospektformat unbekannt")
        val ids = selectedBrochures(groups, request.week)
        check(ids.isNotEmpty()) { "KaufDA: kein regionaler Prospekt verfügbar" }
        val products = linkedMapOf<String, ProductEntity>()
        val offers = linkedMapOf<String, OfferEntity>()
        ids.forEach { brochure ->
            val url = "$viewerBaseUrl/v1/brochures/$brochure/pages?partner=kaufda_web&lat=$lat&lng=$lon"
            val pages = json.parseToJsonElement(read(url, 6_000_000)).jsonObject["contents"] as? JsonArray
                ?: error("KaufDA Prospektseitenformat unbekannt")
            pages.forEach { page ->
                (page.jsonObject["offers"] as? JsonArray).orEmpty().forEach entryLoop@{ entry ->
                    val content = entry.jsonObject["content"]?.jsonObject ?: return@entryLoop
                    if (content.text("type") != "offer") return@entryLoop
                    val external = content.text("id") ?: return@entryLoop
                    val validity = (content["publicationProfiles"] as? JsonArray)?.firstOrNull()?.jsonObject
                        ?.get("validity")?.jsonObject ?: return@entryLoop
                    val from = validity.instant("startDate") ?: return@entryLoop
                    val until = validity.instant("endDate") ?: return@entryLoop
                    if (!selected(from, until, request.week)) return@entryLoop
                    val rawProducts = content["products"] as? JsonArray ?: error("KaufDA Produktliste unbekannt")
                    rawProducts.forEachIndexed { index, raw ->
                        val product = raw.jsonObject
                        val title = product.text("name") ?: return@forEachIndexed
                        val pricing = viewerPrices(content, product, rawProducts.size) ?: return@forEachIndexed
                        val price = pricing.first
                        val benefit = pricing.second?.takeIf { it < price }
                        val brand = product.text("brandName").orEmpty()
                        val name = if (brand.isBlank() || title.contains(brand, true)) title else "$brand $title"
                        var description = (product["description"] as? JsonArray).orEmpty()
                            .mapNotNull { it.jsonObject.text("paragraph") }.joinToString(" · ")
                        val leaf = (product["categoryPaths"] as? JsonArray)?.lastOrNull()?.jsonObject?.text("name").orEmpty()
                        val titleKey = normalize(title).replace("-", "")
                        val leafKey = normalize(leaf).replace("-", "")
                        if (titleKey.isNotEmpty() && leafKey.startsWith(titleKey) && leafKey != titleKey) {
                            description += " · Quellkategorie: $leaf"
                        }
                        val productId = "$id-product-${normalize(name)}"
                        val image = ((product["images"] as? JsonArray)?.firstOrNull()?.jsonObject?.text("url") ?: content.text("image"))?.takeIf { runCatching { it.toHttpUrl().host == "content-media.bonial.biz" }.getOrDefault(false) }
                        products[productId] = ProductEntity(productId, name, brand, normalize(name))
                        val key = "$external:$index"
                        offers[key] = OfferEntity(id = "$id:kaufda:$key", retailerId = id, productId = productId,
                            externalId = "kaufda:$key", priceCents = BigDecimal.valueOf(price).movePointRight(2)
                                .setScale(0, RoundingMode.HALF_UP).intValueExact(),
                            validFrom = from.atZone(ZoneId.of("Europe/Berlin")).toLocalDate().toString(),
                            validUntil = until.atZone(ZoneId.of("Europe/Berlin")).toLocalDate().toString(),
                            sourceUrl = regionalUrl, imageUrl = image, description = description,
                            loyaltyProgram = if (benefit != null) when (publisherName) { "Lidl" -> "lidl_plus"; "Müller" -> "mueller_blueten"; else -> null } else null,
                            loyaltyLabel = if (benefit != null) when (publisherName) { "Lidl" -> "Lidl Plus"; "Müller" -> "Müller App"; else -> null } else null,
                            loyaltyPriceCents = benefit?.let(ProviderParsing::cents),
                            packSize = ProviderParsing.packSize("$name $description"), cachedAt = System.currentTimeMillis())
                    }
                }
            }
        }
        check(!publisherViewer || offers.isNotEmpty()) { "KaufDA: keine datierten Händlerangebote für die Zielwoche" }
        return ProviderResult(products.values.toList(), offers.values.toList(), sourceWarnings = if (publisherViewer)
            listOf("$displayName: datierter Händlerprospekt; Filialgeltung und lokaler Bestand nicht bestätigt.") else emptyList())
    }

    private fun selectedBrochures(groups: JsonObject, week: OfferWeek): List<String> {
        val candidates = linkedMapOf<String, JsonObject>()
        for (group in listOf("viewer", "publisher")) {
            val rows = groups[group] ?: continue
            check(rows is JsonArray) { "KaufDA Prospektliste unbekannt" }
            rows.forEach { raw ->
                val entry = raw as? JsonObject ?: return@forEach
                val publisher = entry["publisher"] as? JsonObject ?: return@forEach
                if (publisher.text("type") !in listOf(null, "RETAILER") || !publisher.text("name").equals(publisherName, true)) return@forEach
                entry.text("id")?.takeIf { it.matches(Regex("\\d{6,12}")) }?.let { candidates.putIfAbsent(it, entry) }
            }
        }
        val zone = ZoneId.of("Europe/Berlin")
        var reference = now().atZone(zone).toLocalDate()
        if (reference.dayOfWeek == java.time.DayOfWeek.SUNDAY) reference = reference.plusDays(1)
        if (week == OfferWeek.NEXT) reference = reference.plusWeeks(1)
        val weekEnd = reference.plusDays((7 - reference.dayOfWeek.value).toLong())
        val active = linkedMapOf<String, Pair<java.time.LocalDate, java.time.LocalDate>>()
        val undated = mutableListOf<String>()
        candidates.forEach { (id, entry) ->
            val start = entry.instant("validFrom")?.atZone(zone)?.toLocalDate()
            val end = entry.instant("validUntil")?.atZone(zone)?.toLocalDate()
            if (start == null && end == null && entry.text("validFrom").isNullOrBlank() && entry.text("validUntil").isNullOrBlank()) undated += id
            else {
                check(start != null && end != null && start <= end) { "KaufDA Prospektgültigkeit unbekannt oder widersprüchlich" }
                if (start <= weekEnd && reference <= end) active[id] = start to end
            }
        }
        val weekly = active.filterValues { it.second <= weekEnd }
        val selected = if (weekly.isNotEmpty()) weekly.keys.toList()
            else if (active.isNotEmpty()) {
                val latest = active.values.maxOf { it.first }
                active.filterValues { it.first == latest }.keys.toList()
            } else undated
        check(selected.size <= 6) { "KaufDA Prospektlimit überschritten; Auswahl unvollständig" }
        return selected
    }

    private fun viewerPrices(content: JsonObject, product: JsonObject, productCount: Int): Pair<Double, Double?>? {
        var deals = (content["deals"] as? JsonArray).orEmpty().map { it.jsonObject }
        fun key(value: String) = normalize(value).replace("-", "")
        if (productCount > 1) {
            val title = key(product.text("name").orEmpty())
            val brand = key(product.text("brandName").orEmpty())
            val exact = deals.filter { key(it.text("description").orEmpty()) in setOf(title, brand + title) }
            if (exact.isNotEmpty()) deals = exact
            else if (deals.groupBy { it.text("type") }.values.any { group ->
                    group.map { it["min"]?.jsonPrimitive?.doubleOrNull }.distinct().size > 1 }) return null
        }
        fun value(d: JsonObject): Double? {
            if (d.text("currencyCode") !in listOf(null, "EUR")) return null
            val min = d["min"]?.jsonPrimitive?.doubleOrNull?.takeIf { it > 0 && it.isFinite() } ?: return null
            if (d["max"] != null && d["max"]?.jsonPrimitive?.doubleOrNull != min) return null
            return min
        }
        fun conditions(d: JsonObject): String? {
            val raw = d["conditions"] ?: return ""
            if (raw !is JsonArray) return null
            return raw.joinToString(" ") { it.jsonObject.values.joinToString(" ") { v -> v.jsonPrimitive.content } }.trim().lowercase(Locale.GERMAN)
        }
        val memberConditions = when (publisherName) {
            "Lidl" -> setOf("mit lidl plus")
            "Müller" -> setOf("mit der müller app", "mit müller app", "im preis in der app", "m app")
            else -> emptySet()
        }
        val memberValues = deals.mapNotNull { d ->
            if (d.text("type") in listOf("SALES_PRICE", "SPECIAL_PRICE") && conditions(d) in memberConditions) value(d) else null
        }.distinct()
        val member = memberValues.singleOrNull()
        val cash = deals.mapNotNull { d ->
            if (d.text("type") in listOf("SALES_PRICE", "SPECIAL_PRICE") &&
                conditions(d) in listOf("", "auch online", "auch online erhältlich", "ohne app", "ohne lidl plus")) value(d) else null
        }.distinct()
        if (cash.size > 1) return null
        val normal = if (member != null) deals.mapNotNull { d ->
            if (d.text("type") == "REGULAR_PRICE" && conditions(d) == "") value(d) else null
        }.distinct().singleOrNull() else null
        return (cash.singleOrNull() ?: normal ?: return null) to member
    }

    private fun JsonObject.text(key: String): String? = this[key]?.takeUnless { it is JsonNull }?.jsonPrimitive?.content?.trim()?.ifBlank { null }

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
