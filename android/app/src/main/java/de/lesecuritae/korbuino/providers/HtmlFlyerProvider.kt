package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.jsoup.Jsoup
import java.net.URI
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
    private val renderedHtmlProvider: (() -> String?)? = null,
) : RetailerProvider {
    override val challengeUrl: String get() = offersUrl
    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(Regex("^\\d{5}$").matches(request.postalCode)) { "Ungültige PLZ" }
        val rendered = renderedHtmlProvider?.invoke()?.takeIf { it.isNotBlank() }
        val result = if (rendered != null) {
            parse(rendered)
        } else {
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
        if (id in setOf("mueller", "rossmann") && result.offers.isEmpty()) {
            val reason = if (id == "rossmann") "Rossmann Anti-Bot-Seite lieferte" else "Müller lieferte"
            throw IllegalStateException("$reason keine lesbaren dynamischen Angebote")
        }
        result
    }

    private fun parse(html: String): ProviderResult {
        val doc = Jsoup.parse(html, offersUrl)
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        val cards = doc.select(
            "[data-product], [data-testid*=product], .offer, .offer-card, .product-card, " +
                ".product-tile, .kloffer, [aria-label^=\"product-\"], article, li[class*=offer], li[class*=product]",
        )
        cards.forEachIndexed { index, card ->
            val name = card.attr("data-item-name").ifBlank { card.select(
                "[data-product-name], [data-testid*=name], .product-name, .offer-name, " +
                    "[data-test*=product-tile__name], [class*=product-tile__product-name], " +
                    ".product-tile__name, .title, h4, h2, h3",
            ).firstOrNull()?.text()?.trim().orEmpty() }
            val text = card.select("[data-price], [data-testid*=price], [data-test*=product-tile__price], " +
                "[class*=product-price__current], [class*=product-price__price], " +
                ".base-price--product-tile, .price, .offer-price, .product-price")
                .firstOrNull()?.text()?.replace('\u00a0', ' ') ?: card.text().removePrefix(name)
            val price = (if (id == "netto-marken") {
                card.selectFirst(".product__current-price strong")?.clone()?.apply {
                    select(".product__current-price--asterisk, .sr-only").remove()
                }?.text()?.let { raw ->
                    ProviderParsing.price(raw.replace(Regex("[.,][–—-]$"), ",00"))
                }
            } else if (id == "netto-schwarz") {
                splitPrice(card.selectFirst("h3")) ?: parsePrice(text)
            } else if (id == "rossmann") {
                rossmannPrice(card) ?: parsePrice(text)
            } else parsePrice(text))
                ?: return@forEachIndexed
            if (name.isBlank() || name.length > 240) return@forEachIndexed
            val external = card.attr("data-product-id").ifBlank { card.attr("data-id") }
                .ifBlank { card.attr("data-item-id") }
                .ifBlank { if (id == "netto-marken") card.selectFirst("[data-sku]")?.attr("data-sku").orEmpty() else "" }
                .ifBlank { "$index-${normalize(name)}" }
            val productId = "$id-product-${normalize(name)}"
            val image = imageUrl(card)
            products += ProductEntity(
                productId,
                name,
                brand = card.attr("data-item-brand"),
                normalizedKey = normalize(name),
                gtin = card.attr("data-item-ean").ifBlank { null },
            )
            offers += OfferEntity(
                id = "$id:$external", retailerId = id, productId = productId,
                externalId = external, priceCents = java.math.BigDecimal.valueOf(price).movePointRight(2).setScale(0, java.math.RoundingMode.HALF_UP).intValueExact(),
                sourceUrl = offersUrl, imageUrl = image, cachedAt = System.currentTimeMillis(),
            )
        }
        return ProviderResult(products.distinctBy { it.id }, offers.distinctBy { it.id })
    }

    private fun parsePrice(text: String): Double? {
        val token = Regex("(?<!\\d)(\\d{1,4}[,.]\\d{2})(?!\\d)").find(text)?.groupValues?.get(1) ?: return null
        // German pages use comma decimals; some ALDI pages expose the same
        // value with a dot. A dot-only token is therefore a decimal, while a
        // comma token may also contain dots as thousands separators.
        return if (token.contains(',')) {
            token.replace(".", "").replace(',', '.').toDoubleOrNull()
        } else {
            token.toDoubleOrNull()
        }
    }

    private fun splitPrice(node: org.jsoup.nodes.Element?): Double? {
        if (node == null) return null
        val euros = node.ownText().trim().removeSuffix(".").removeSuffix(",")
        val cents = node.children().firstNotNullOfOrNull { child ->
            child.text().trim().takeIf { it.matches(Regex("\\d{2}")) }
        }
        if (euros.matches(Regex("\\d{1,4}")) && cents != null) {
            return ProviderParsing.price("$euros.$cents")
        }
        val fragments = node.children().map { it.text().trim() }.filter(String::isNotBlank)
        if (fragments.size >= 2 && fragments[0].matches(Regex("\\d{1,4}")) && fragments[1].matches(Regex("\\d{2}"))) {
            return ProviderParsing.price("${fragments[0]}.${fragments[1]}")
        }
        val text = node.text()
        val compact = text.replace('\u00a0', ' ').trim()
        parsePrice(compact)?.let { return it }
        val parts = Regex("(?<!\\d)(\\d{1,4})\\s+(\\d{2})(?!\\d)").find(compact)
            ?: return null
        return ProviderParsing.price("${parts.groupValues[1]}.${parts.groupValues[2]}")
    }

    /** Rossmann exposes base prices before the sale price in DOM order. */
    private fun rossmannPrice(card: org.jsoup.nodes.Element): Double? {
        val priceBox = card.selectFirst("[data-testid=product-price]") ?: return null
        val accessiblePrice = priceBox.select(".sr-only").asSequence()
            .map { it.text().replace('\u00a0', ' ') }
            .firstOrNull { it.contains("Preis", ignoreCase = true) || it.contains("Price", ignoreCase = true) }
        parsePrice(accessiblePrice.orEmpty())?.let { return it }

        val visual = priceBox.selectFirst(".inline-flex") ?: return null
        return splitPrice(visual)
    }

    private fun imageUrl(card: org.jsoup.nodes.Element): String? {
        val attributes = listOf(
            "data-lazy-src", "data-original", "data-image", "data-zoom-image",
            "data-srcset", "srcset", "data-src", "src",
        )
        return attributes.asSequence().mapNotNull { attribute ->
            card.select("img[$attribute]").firstOrNull()?.let { image ->
                val raw = (if (attribute.endsWith("srcset")) image.attr(attribute).split(Regex(",\\s+(?=https?://|/)")).asSequence() else sequenceOf(image.attr(attribute)))
                    .map { it.trim().substringBefore(' ').trim() }
                    .filter(String::isNotBlank)
                    .lastOrNull()
                    ?: return@let null
                if (raw.startsWith("data:") || raw.startsWith("javascript:")) return@let null
                runCatching { URI(offersUrl).resolve(raw).toString() }.getOrNull()
            }
        }.firstOrNull { it.startsWith("http://") || it.startsWith("https://") }
    }

    private fun normalize(value: String): String = Normalizer.normalize(value.lowercase(Locale.GERMAN), Normalizer.Form.NFKD)
        .replace("\\p{M}".toRegex(), "").replace("[^a-z0-9]+".toRegex(), "-").trim('-')
}
