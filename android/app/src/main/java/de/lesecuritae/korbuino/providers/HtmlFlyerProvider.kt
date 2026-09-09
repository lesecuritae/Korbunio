package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.jsoup.Jsoup
import java.text.Normalizer
import java.util.Locale

/**
 * Direct provider for retailers exposing public offer/flyer HTML. It is
 * intentionally conservative: a card is accepted only when both a name and a
 * parseable EUR price are present. No private app endpoint or TLS bypass is
 * used, and the source URL is retained for every offer.
 */
class HtmlFlyerProvider(
    override val id: String,
    override val displayName: String,
    private val offersUrl: String,
    private val http: OkHttpClient = OkHttpClient(),
) : RetailerProvider {
    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(Regex("^\\d{5}$").matches(request.postalCode)) { "Ungültige PLZ" }
        val call = Request.Builder().url(offersUrl)
            .header("Accept", "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8")
            .header("Accept-Language", "de-DE,de;q=0.9")
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36")
            .build()
        http.newCall(call).execute().use { response ->
            check(response.isSuccessful) { "$displayName HTTP ${response.code}" }
            parse(response.body?.string().orEmpty())
        }
    }

    private fun parse(html: String): ProviderResult {
        val doc = Jsoup.parse(html, offersUrl)
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        val cards = doc.select(
            "[data-product], [data-testid*=product], .offer, .offer-card, .product-card, " +
                ".product-tile, .kloffer, article, li[class*=offer], li[class*=product]",
        )
        cards.forEachIndexed { index, card ->
            val name = card.select(
                "[data-product-name], [data-testid*=name], .product-name, .offer-name, " +
                    ".title, h2, h3, h4",
            ).firstOrNull()?.text()?.trim().orEmpty()
            val text = card.select("[data-price], [data-testid*=price], .price, .offer-price, .product-price")
                .firstOrNull()?.text()?.replace('\u00a0', ' ') ?: card.text().removePrefix(name)
            val price = Regex("(?<!\\d)(\\d{1,4}[,.]\\d{2})\\s*€?").find(text)
                ?.groupValues?.get(1)?.replace(".", "")?.replace(',', '.')?.toDoubleOrNull()
                ?: return@forEachIndexed
            if (name.isBlank() || name.length > 240) return@forEachIndexed
            val external = card.attr("data-product-id").ifBlank { card.attr("data-id") }
                .ifBlank { "$index-${normalize(name)}" }
            val productId = "$id-product-${normalize(name)}"
            val image = card.select("img[src], img[data-src]").firstOrNull()?.let {
                it.attr("abs:src").ifBlank { it.attr("abs:data-src") }
            }
            products += ProductEntity(productId, name, normalizedKey = normalize(name))
            offers += OfferEntity(
                id = "$id:$external", retailerId = id, productId = productId,
                externalId = external, priceCents = (price * 100).toInt(),
                sourceUrl = offersUrl, imageUrl = image, cachedAt = System.currentTimeMillis(),
            )
        }
        return ProviderResult(products.distinctBy { it.id }, offers.distinctBy { it.id })
    }

    private fun normalize(value: String): String = Normalizer.normalize(value.lowercase(Locale.GERMAN), Normalizer.Form.NFKD)
        .replace("\\p{M}".toRegex(), "").replace("[^a-z0-9]+".toRegex(), "-").trim('-')
}
