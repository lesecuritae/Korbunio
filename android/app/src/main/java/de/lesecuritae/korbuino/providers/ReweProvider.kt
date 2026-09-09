package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import java.text.Normalizer
import java.time.LocalDate
import java.time.temporal.TemporalAdjusters
import java.util.Locale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.jsoup.Jsoup
import java.net.URI

/**
 * Native REWE provider. It deliberately consumes the public offer pages used
 * by the web site; it does not depend on the private mobile-app API or on a
 * Korbuino server. Cronet can replace the OkHttp transport later without
 * changing this parser/provider contract.
 */
class ReweProvider(
    private val http: OkHttpClient = OkHttpClient(),
    private val baseUrl: String = "https://www.rewe.de",
    private val fallback: RetailerProvider? = null,
) : RetailerProvider {
    override val id = "rewe"
    override val displayName = "REWE"
    override val challengeUrl: String get() = baseUrl

    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(Regex("^\\d{5}$").matches(request.postalCode)) { "Ungültige PLZ" }
        val direct = runCatching { fetchPublic(request) }
        val primary = direct.getOrNull()
        // REWE can return a successfully rendered first page with only a
        // small visible subset. Prefer the regional, paginated source in that
        // case so Android does not silently present just the first ten offers.
        if (primary != null && primary.offers.size > 10) return@withContext primary
        val regional = runCatching { fallback?.fetch(request) }
            .getOrNull()
            ?.let { result ->
                // Keep the logical retailer stable when the regional source
                // is used. Otherwise the UI would expose an implementation
                // detail ("marktguru-rewe") as a second retailer.
                result.copy(offers = result.offers.map { it.copy(retailerId = id) })
            }
        when {
            regional != null && (primary == null || regional.offers.size > primary.offers.size) -> regional
            primary != null -> primary
            else -> throw (direct.exceptionOrNull() ?: error("REWE-Angebote konnten nicht geladen werden"))
        }
    }

    private fun fetchPublic(request: RetailerRequest): ProviderResult {
        val city = request.citySlug?.trim()?.lowercase(Locale.GERMAN)?.replace(" ", "-")
            ?: error("Für die direkte REWE-Marktsuche wird zusätzlich die Stadt benötigt")
        val marketPage = get("$baseUrl/marktsuche/$city/")
        val market = findMarket(marketPage, request.postalCode, request.marketId)
            ?: error("Kein REWE-Markt für ${request.postalCode} gefunden")
        val url = market.url + if (request.week == OfferWeek.NEXT) "?week=next" else ""
        val page = get(url)
        val parsed = parseOffers(page, market.id, url)
        if (parsed.offers.isEmpty()) error("Keine auswertbaren REWE-Angebote gefunden")
        return parsed
    }

    private fun get(url: String): String {
        val req = Request.Builder()
            .url(url)
            .header("Accept", "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8")
            .header("Accept-Language", "de-DE,de;q=0.9")
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36")
            .build()
        http.newCall(req).execute().use { response ->
            check(response.isSuccessful) { "REWE HTTP ${response.code}" }
            return response.body?.string().orEmpty()
        }
    }

    private data class Market(val id: String, val url: String)

    private fun findMarket(html: String, postalCode: String, selectedId: String?): Market? {
        val doc = Jsoup.parse(html)
        val regex = Regex("/angebote/[^/]+/(\\d+)/[^/?#]+/?")
        return doc.select("a[href*='/angebote/']").asSequence()
            .mapNotNull { node ->
                val href = node.attr("href").let { if (it.startsWith("http")) it else "$baseUrl$it" }
                val match = regex.find(href) ?: return@mapNotNull null
                val text = node.parent()?.parent()?.text().orEmpty() + " " + node.text()
                if (!text.contains(postalCode)) return@mapNotNull null
                Market(match.groupValues[1], href)
            }
            .distinctBy { it.id }
            .firstOrNull { selectedId == null || it.id == selectedId }
    }

    private fun parseOffers(html: String, marketId: String, marketUrl: String): ProviderResult {
        val doc = Jsoup.parse(html)
        val from = LocalDate.now().with(TemporalAdjusters.previousOrSame(java.time.DayOfWeek.MONDAY))
        val until = from.plusDays(6)
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        doc.select(".cor-offer-renderer-tile").forEachIndexed { index, card ->
            val name = card.select(".cor-offer-information__title").text().trim()
            val priceText = card.select(".cor-offer-price__tag-price").text()
            val price = Regex("(\\d{1,4}[,.]\\d{1,2})").find(priceText)?.groupValues?.get(1)
                ?.replace(',', '.')?.toDoubleOrNull() ?: return@forEachIndexed
            if (name.isBlank()) return@forEachIndexed
            val productId = "rewe-product-" + normalize(name)
            products += ProductEntity(productId, name, normalizedKey = normalize(name))
            offers += OfferEntity(
                id = "rewe:$marketId:$index",
                retailerId = id,
                productId = productId,
                externalId = "$marketId:$index",
                priceCents = (price * 100).toInt(),
                validFrom = from.toString(),
                validUntil = until.toString(),
                sourceUrl = marketUrl,
                imageUrl = imageUrl(card, marketUrl),
                cachedAt = System.currentTimeMillis(),
            )
        }
        return ProviderResult(products.distinctBy { it.id }, offers)
    }

    private fun imageUrl(card: org.jsoup.nodes.Element, pageUrl: String): String? {
        val attributes = listOf("data-lazy-src", "data-original", "data-srcset", "srcset", "data-src", "src")
        return attributes.asSequence().mapNotNull { attribute ->
            card.select("img[$attribute]").firstOrNull()?.attr(attribute)?.split(',')?.asSequence()
                ?.map { it.trim().substringBefore(' ').trim() }
                ?.filter(String::isNotBlank)
                ?.lastOrNull()
                ?.let { raw -> runCatching { URI(pageUrl).resolve(raw).toString() }.getOrNull() }
        }.firstOrNull { it.startsWith("http://") || it.startsWith("https://") }
    }

    private fun normalize(value: String): String = Normalizer.normalize(value.lowercase(Locale.GERMAN), Normalizer.Form.NFKD)
        .replace("\\p{M}".toRegex(), "")
        .replace("[^a-z0-9]+".toRegex(), "-")
        .trim('-')
}
