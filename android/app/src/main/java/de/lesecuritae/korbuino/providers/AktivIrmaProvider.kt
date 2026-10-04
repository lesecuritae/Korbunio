package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.jsoup.Jsoup
import java.math.BigDecimal
import java.math.RoundingMode
import java.net.URI
import java.text.Normalizer
import java.util.Locale

/**
 * aktiv & irma (regional around Oldenburg/Hude/Wardenburg) publishes its full
 * weekly flyer as server-rendered product cards grouped into category tabs
 * (`li.js-tabs-content`), each tab carrying its own validity window. Marktguru
 * has no aktiv & irma offer feed, so this first-party page is the source. This
 * mirrors the server-side `OfficialAktivIrmaSource`. No private endpoint or TLS
 * bypass is used and the source URL is kept on every offer.
 */
class AktivIrmaProvider(
    private val http: OkHttpClient = OkHttpClient(),
    private val offersUrl: String = OFFERS_URL,
) : RetailerProvider {
    override val id: String = "aktiv-irma"
    override val displayName: String = "aktiv & irma"

    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(Regex("^\\d{5}$").matches(request.postalCode)) { "Ungültige PLZ" }
        val call = Request.Builder().url(offersUrl)
            .header("Accept", "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8")
            .header("Accept-Language", "de-DE,de;q=0.9")
            .header("User-Agent", UA)
            .build()
        http.newCall(call).execute().use { response ->
            check(response.isSuccessful) { "$displayName HTTP ${response.code}" }
            parse(response.body?.string().orEmpty())
        }
    }

    internal fun parse(html: String): ProviderResult {
        val doc = Jsoup.parse(html, offersUrl)
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        var index = 0
        for (panel in doc.select("li.js-tabs-content")) {
            val label = panel.select("h2, h3, h4, div, span, a")
                .firstOrNull { it.text().contains("ltig vom", ignoreCase = true) }
                ?.text().orEmpty()
            val match = LABEL.find(label)
            val validFrom = isoDate(match?.groupValues?.get(3))
            val validUntil = isoDate(match?.groupValues?.get(4))
            for (card in panel.select(".fr-product-card")) {
                val name = card.selectFirst("h3.uk-card-title")?.text()?.trim().orEmpty()
                val price = ProviderParsing.price(card.selectFirst(".fr-price-angebot")?.text())
                if (name.isBlank() || name.length > 240 || price == null || price <= 0.0) continue
                // Description without the price nodes, which otherwise bleed into the text.
                val container = card.selectFirst(".product-description-container")?.clone()
                container?.select(".fr-price-box, .fr-price-angebot, .fr-price-statt, .fr-price-app, .fr-produktButton")?.remove()
                val description = container?.text()?.trim().orEmpty()
                val (baseCents, baseUnit) = basePrice(description)
                index += 1
                val key = normalize(name)
                val productId = "$id-product-$key"
                val external = "$index-$key"
                val image = card.selectFirst("img[data-srcset], img[src]")?.let { element ->
                    val raw = element.attr("data-srcset").ifBlank { element.attr("src") }
                    if (raw.isBlank()) null else runCatching { URI(offersUrl).resolve(raw).toString() }.getOrNull()
                }
                products += ProductEntity(productId, name, normalizedKey = key)
                offers += OfferEntity(
                    id = "$id:$external",
                    retailerId = id,
                    productId = productId,
                    externalId = external,
                    priceCents = cents(price),
                    basePriceCents = baseCents,
                    baseUnit = baseUnit,
                    validFrom = validFrom,
                    validUntil = validUntil,
                    sourceUrl = offersUrl,
                    imageUrl = image,
                    cachedAt = System.currentTimeMillis(),
                )
            }
        }
        return ProviderResult(products.distinctBy { it.id }, offers.distinctBy { it.id })
    }

    private fun basePrice(text: String): Pair<Int?, String?> {
        val match = BASE_PRICE.find(text) ?: return null to null
        val value = ProviderParsing.price(match.groupValues[2]) ?: return null to null
        val unit = match.groupValues[1].lowercase(Locale.GERMAN)
            .replace("kilogramm", "kg").replace("liter", "l").replace("stück", "stk")
        return cents(value) to unit
    }

    private fun cents(value: Double): Int =
        BigDecimal.valueOf(value).movePointRight(2).setScale(0, RoundingMode.HALF_UP).intValueExact()

    private fun isoDate(value: String?): String? {
        val match = value?.let { DATE.matchEntire(it.trim()) } ?: return null
        return "${match.groupValues[3]}-${match.groupValues[2]}-${match.groupValues[1]}"
    }

    private fun normalize(value: String): String =
        Normalizer.normalize(value, Normalizer.Form.NFKD)
            .replace(Regex("[^\\p{Alnum}]+"), "-")
            .lowercase(Locale.GERMAN)
            .trim('-')

    companion object {
        const val OFFERS_URL = "https://www.aktiv-irma.de/angebote/"
        private const val UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36"
        private val LABEL = Regex(
            "^(.+?):\\s*(.+?)\\s+g[uü]ltig\\s+vom\\s+(\\d{2}\\.\\d{2}\\.\\d{4})\\s+bis\\s+zum\\s+(\\d{2}\\.\\d{2}\\.\\d{4})",
            RegexOption.IGNORE_CASE,
        )
        private val DATE = Regex("(\\d{2})\\.(\\d{2})\\.(\\d{4})")
        private val BASE_PRICE = Regex(
            "(?:1\\s*)?(kg|kilogramm|l|liter|stück|stk)\\s*=\\s*(\\d+(?:[.,]\\d{1,2})?)",
            RegexOption.IGNORE_CASE,
        )
    }
}
