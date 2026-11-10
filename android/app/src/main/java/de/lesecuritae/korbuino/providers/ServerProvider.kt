package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.LoyaltyBenefits
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.put
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

/**
 * Self-hosted Korbuino API. Without [retailerName] it returns the server's
 * consolidated result for every retailer (server mode). With it, it asks the
 * server for that one retailer, whose offers are stored under [localId]; the
 * server fetches with curl_cffi, so it gets through where the app is blocked.
 */
class ServerProvider(
    private val baseUrl: String,
    private val token: String,
    private val http: OkHttpClient,
    private val retailerName: String? = null,
    private val localId: String? = null,
) : RetailerProvider {
    override val id = localId ?: "korbuino-server"
    override val displayName = retailerName ?: "Korbuino Server"
    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(request.postalCode.matches(Regex("^\\d{5}$"))) { "Ungültige PLZ" }
        val offerItems = mutableListOf<JsonObject>()
        val unavailableNames = mutableSetOf<String>()
        val unavailableIdsByName = mapOf("ALDI Nord" to "aldi-nord", "ALDI Süd" to "aldi-sued", "aktiv & irma" to "aktiv-irma", "Globus" to "globus", "trinkgut" to "trinkgut")
        val incomplete = mutableSetOf<String>()
        val warnings = mutableSetOf<String>()
        val seen = mutableSetOf<String>()
        var page = 1
        var pageCount = 1
        var declaredPageCount: Int? = null
        do {
            val body = buildJsonObject {
                put("postal_code", request.postalCode)
                put("refresh", page == 1)
                put("offer_week", if (request.week == OfferWeek.NEXT) "next" else "current")
                // Lets the app load product images itself, like for its own offers. Older servers ignore it.
                put("include_image_urls", true)
                putJsonArray("retailers") { retailerName?.let { add(JsonPrimitive(it)) } }
                // Page through the complete result in both server and fallback modes.
                put("view", "all")
                put("page", page)
                put("page_size", 100)
            }.toString()
            val requestBuilder = Request.Builder().url(baseUrl.trimEnd('/') + "/api/v1/compare")
                .header("Accept", "application/json")
                .post(body.toRequestBody("application/json".toMediaType()))
            if (token.isNotBlank()) requestBuilder.header("Authorization", "Bearer $token")
            val root = json.parseToJsonElement(
                http.newCall(requestBuilder.build()).execute().use { response ->
                    check(response.isSuccessful) { "Korbuino Server HTTP ${response.code}" }
                    response.body?.string().orEmpty()
                },
            ).jsonObject
            val resultRoot = if (root["offers"]?.jsonArray?.isNotEmpty() == true) root else fetchResult(root)
            check(resultRoot["offers"] is kotlinx.serialization.json.JsonArray) { "Korbuino: unbekanntes Angebotsformat" }
            resultRoot["incomplete_retailers"]?.jsonArray.orEmpty().forEach { value ->
                (value as? JsonPrimitive)?.takeIf { it.isString }?.content?.let { incomplete += it }
            }
            resultRoot["warnings"]?.jsonArray.orEmpty().forEach { value ->
                (value as? JsonPrimitive)?.takeIf { it.isString }?.content?.let { warnings += it }
            }
            resultRoot["unavailable_retailers"]?.jsonArray.orEmpty().forEach { value ->
                val name = (value as? JsonPrimitive)?.takeIf { it.isString }?.content
                if (name in unavailableIdsByName) unavailableNames += name!!
            }
            pageCount = resultRoot.number("page_count")?.let {
                check(it.isFinite() && it % 1 == 0.0 && it in 1.0..200.0) { "Korbuino: ungültige oder zu große Seitenzahl" }; it.toInt()
            } ?: 1
            check(declaredPageCount == null || pageCount == declaredPageCount) { "Korbuino: Seitenzahl während des Imports verändert" }
            declaredPageCount = pageCount
            resultRoot.number("page")?.let {
                check(it == page.toDouble()) { "Korbuino: falsche Angebotsseite geliefert" }
            }
            val items = resultRoot["offers"]!!.jsonArray.map { it.jsonObject }
            check(items.isNotEmpty() || (page == 1 && pageCount == 1)) { "Korbuino: erwartete Angebotsseite fehlt" }
            val ids = items.map { it.text("offer_id") ?: it.toString() }
            check(items.isEmpty() || ids.any { it !in seen }) { "Korbuino: Angebotsseite wird wiederholt" }
            seen.addAll(ids)
            offerItems.addAll(items)
            check(offerItems.size <= 20_000) { "Korbuino: Angebotslimit erreicht; Import nicht vollständig" }
            page++
        } while (page <= pageCount)
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        val ambiguousNames = offerItems.groupBy { it.text("product") ?: it.text("name") }.filterValues { rows ->
            rows.map { listOf(it.text("brand"), it.text("pack_size") ?: it.text("pack_signature") ?: it.text("pack"), it["product_gtins"]?.toString()) }.distinct().size > 1
        }.keys
        val hashCollisions = offerItems.mapNotNull { it.text("product") ?: it.text("name") }.distinct().groupBy { it.lowercase().hashCode() }.filterValues { it.size > 1 }.keys
        offerItems.forEachIndexed { index, item ->
            val name = item.text("product") ?: item.text("name") ?: return@forEachIndexed
            val price = item.number("regular_price") ?: item.number("price") ?: error("Korbuino: kein belegter Normalpreis")
            check(price.isFinite() && price > 0) { "Korbuino: ungültiger Normalpreis" }
            val benefits = LoyaltyBenefits.parse(item["benefits"]?.toString().orEmpty())
            val retailer = localId ?: item.text("retailer") ?: "Unbekannt"
            val external = item.text("offer_id") ?: "$index-${name.lowercase().hashCode()}"
            val productId = if (name in ambiguousNames || name.lowercase().hashCode() in hashCollisions) "server-product-$retailer-$external" else "server-product-${name.lowercase().hashCode()}"
            val gtins = item["product_gtins"]?.takeUnless { it is JsonNull }?.jsonArray.orEmpty().mapNotNull { (it as? JsonPrimitive)?.takeIf { v -> v.isString }?.content }
            products += ProductEntity(productId, name, brand = item.text("brand").orEmpty(), normalizedKey = productId, gtin = gtins.singleOrNull())
            val quantity = item.number("multi_buy_quantity")?.let {
                check(it.isFinite() && it % 1 == 0.0 && it in 2.0..10_000.0) { "Korbuino: ungültige Mehrkaufmenge" }; it.toInt()
            }
            val bundle = item.number("multi_buy_total_price")
            val minimum = item.number("minimum_quantity")
            check((quantity == null && (minimum == null || minimum <= 1)) || (quantity != null && bundle != null && bundle.isFinite() && bundle > 0)) { "Korbuino: unvollständiger Mehrkaufpreis" }
            offers += OfferEntity(
                id = "${localId ?: "server"}:$external", retailerId = retailer, productId = productId,
                externalId = external, priceCents = ProviderParsing.cents(price),
                depositCents = item.number("deposit")?.let(ProviderParsing::cents),
                multiBuyQuantity = quantity, multiBuyTotalCents = bundle?.let(ProviderParsing::cents),
                singlePriceCents = item.number("single_price")?.let(ProviderParsing::cents),
                multiBuyCondition = item.text("multi_buy_condition"), multiBuyMixGroup = item.text("multi_buy_mix_group"),
                validFrom = item.text("valid_from"), validUntil = item.text("valid_until"),
                loyaltyBenefitsJson = LoyaltyBenefits.encode(benefits),
                basePriceCents = item.number("base_price")?.let(ProviderParsing::cents), baseUnit = item.text("base_unit"),
                categoryId = item.text("category"), sourceUrl = item.text("source_url").orEmpty(),
                imageUrl = item.text("image_url")?.let { image ->
                    val parsed = image.toHttpUrlOrNull()
                    if (parsed != null && parsed.host.isNotBlank()) image
                    else baseUrl.trimEnd('/') + "/" + image.trimStart('/')
                }, cachedAt = System.currentTimeMillis(),
                description = item.text("description").orEmpty(),
                packSize = item.text("pack_size") ?: item.text("pack_signature") ?: item.text("pack"),
            )
        }
        val unavailableIds = unavailableNames.flatMap { name ->
            val directId = unavailableIdsByName.getValue(name)
            listOf(name, directId)
        }
        ProviderResult(products.distinctBy { it.id }, offers.distinctBy { it.id },
            noLocalMarket = retailerName in unavailableNames && offers.isEmpty(),
            unavailableRetailerIds = unavailableIds,
            preserveMissingOffers = if (retailerName == null) incomplete.isNotEmpty() else retailerName in incomplete,
            sourceWarnings = warnings.toList())
    }

    private fun fetchResult(compare: JsonObject): JsonObject {
        val resultUrl = compare.text("result_url") ?: return compare
        val parsed = resultUrl.toHttpUrlOrNull() ?: error("Korbuino: ungültige Ergebnisadresse")
        val trusted = baseUrl.toHttpUrlOrNull() ?: error("Korbuino: ungültige Serveradresse")
        check(parsed.host == trusted.host && parsed.port == trusted.port && parsed.scheme == trusted.scheme && parsed.username.isEmpty() && parsed.password.isEmpty()) { "Korbuino: Ergebnisadresse verweist auf einen anderen Server" }
        val path = if (parsed.encodedPath.startsWith("/api/v1/")) parsed.encodedPath
        else "/api/v1${parsed.encodedPath}"
        val url = parsed.newBuilder().encodedPath(path).build()
        val requestBuilder = Request.Builder().url(url).header("Accept", "application/json")
        if (token.isNotBlank()) requestBuilder.header("Authorization", "Bearer $token")
        return json.parseToJsonElement(
            http.newCall(requestBuilder.build()).execute().use { response ->
                check(response.isSuccessful) { "Korbuino Ergebnis HTTP ${response.code}" }
                response.body?.string().orEmpty()
            },
        ).jsonObject
    }

    private fun JsonObject.text(key: String): String? = runCatching { this[key]?.takeUnless { it is JsonNull }?.jsonPrimitive?.content?.trim() }.getOrNull()?.ifBlank { null }
    private fun JsonObject.number(key: String): Double? = ProviderParsing.price(text(key))
}
