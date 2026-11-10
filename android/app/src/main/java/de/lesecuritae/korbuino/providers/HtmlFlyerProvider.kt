package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.jsoup.Jsoup
import java.net.URI
import okhttp3.HttpUrl.Companion.toHttpUrl
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.JsonArray
import de.lesecuritae.korbuino.BerlinDate
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
    private val now: () -> java.time.LocalDate = { java.time.LocalDate.now(java.time.ZoneId.of("Europe/Berlin")) },
) : RetailerProvider {
    override val challengeUrl: String get() = offersUrl
    override suspend fun fetch(request: RetailerRequest): ProviderResult = withContext(Dispatchers.IO) {
        require(Regex("^\\d{5}$").matches(request.postalCode)) { "Ungültige PLZ" }
        val rendered = renderedHtmlProvider?.invoke()?.takeIf { it.isNotBlank() }
        val html = if (rendered != null) {
            rendered
        } else {
            val call = Request.Builder().url(offersUrl)
                .header("Accept", "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8")
                .header("Accept-Language", "de-DE,de;q=0.9")
                .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131 Mobile Safari/537.36")
                .build()
            http.newCall(call).execute().use { response ->
                check(response.isSuccessful) { "$displayName HTTP ${response.code}" }
                response.body?.string().orEmpty()
            }
        }
        val first = parse(html, request.week)
        val result = if (id == "mueller" && muellerListingIds(html).isNotEmpty()) remainingPages(html, first, request.week) else first
        if (id == "aldi-sued" && result.offers.isEmpty()) {
            // A 200 challenge/navigation page is not evidence of no local
            // store. Surface the failure so diagnostics and browser handoff
            // stay available instead of silently hiding the retailer.
            val blocked = listOf("captcha", "challenge", "access denied", "bot protection", "anti-bot")
                .any { html.contains(it, ignoreCase = true) }
            check(!blocked) { "ALDI Süd Anti-Bot-Seite: Browser-Bestätigung erforderlich" }
            error("ALDI Süd Angebotsformat nicht lesbar: keine Produktkarten gefunden")
        }
        if (id in setOf("mueller", "rossmann") && result.offers.isEmpty() && !(id == "mueller" && result.paginationComplete)) {
            val reason = if (id == "rossmann") "Rossmann Anti-Bot-Seite lieferte" else "Müller lieferte"
            throw IllegalStateException("$reason keine lesbaren dynamischen Angebote")
        }
        result
    }

    private fun parse(html: String, week: OfferWeek): ProviderResult {
        val doc = Jsoup.parse(html, offersUrl)
        if (id == "holab" && doc.select("data.offer__price").isNotEmpty()) return parseHolab(doc, week)
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        val cards = doc.select(
            "[data-product], [data-testid*=product], .offer, .offer-card, .product-card, " +
                ".product-tile, .kloffer, [aria-label^=\"product-\"], article, li[class*=offer], li[class*=product]",
        )
        cards.forEachIndexed { index, card ->
            if (id == "mueller" && card.select("[class*=product-badges__text]").none { it.text().trim().equals("Sale", ignoreCase = true) }) return@forEachIndexed
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
            } else if (id == "mueller") {
                card.selectFirst("[data-testid=plp-currentPrice-label]")?.text()?.let(ProviderParsing::price)
            } else if (id == "rossmann") {
                rossmannPrice(card) ?: parsePrice(text)
            } else parsePrice(text))
                ?: return@forEachIndexed
            if (name.isBlank() || name.length > 240) return@forEachIndexed
            val external = card.attr("data-product-id").ifBlank { card.selectFirst("[data-product-id]")?.attr("data-product-id").orEmpty() }.ifBlank { card.attr("data-id") }
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
                description = card.select(".product-description, .offer-description, .offer__subtitle, .offer__details, .product-tile__description, [class*=product-price__capacity]").text(),
                packSize = ProviderParsing.packSize("$name ${card.select(".product-description, .offer-description, .offer__details, .product-tile__description, [class*=product-price__capacity]").text()}"),
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

    private fun muellerListingIds(html: String): Set<String> = Jsoup.parse(html, offersUrl).select("article")
        .filter { it.selectFirst("[class*=product-tile__product-name]") != null && it.selectFirst("[data-testid=plp-currentPrice-label]") != null }
        .map { it.attr("data-product-id").ifBlank { it.selectFirst("[data-product-id]")?.attr("data-product-id").orEmpty() } }
        .filter { it.isNotBlank() }.toSet()

    private suspend fun remainingPages(initial: String, first: ProviderResult, week: OfferWeek): ProviderResult {
        val base = offersUrl.toHttpUrl()
        val products = first.products.associateBy { it.id }.toMutableMap()
        val offers = first.offers.associateBy { it.id }.toMutableMap()
        var html = initial
        val seenProducts = muellerListingIds(initial).toMutableSet()
        for (page in 1..200) {
            currentCoroutineContext().ensureActive()
            val links = Jsoup.parse(html, offersUrl).select("a[href]").mapNotNull { link ->
                val url = runCatching { link.absUrl("href").toHttpUrl() }.getOrNull() ?: return@mapNotNull null
                val number = url.queryParameter("page")?.toIntOrNull()
                if (url.host == base.host && url.scheme == base.scheme && url.encodedPath == base.encodedPath &&
                    url.queryParameterNames == setOf("page") && url.queryParameterValues("page").size == 1 && number != null) number to url else null
            }.toMap()
            if (page + 1 !in links && links.keys.none { it > page }) {
                return ProviderResult(products.values.toList(), offers.values.toList(), paginationComplete = true)
            }
            val attempt = runCatching {
                check(page < 200) { "Müller Seitenlimit erreicht" }
                val url = links[page + 1] ?: error("Müller Pagination überspringt eine Seite")
                html = http.newCall(Request.Builder().url(url).header("Accept", "text/html").build()).execute().use { response ->
                    check(response.isSuccessful) { "Müller HTTP ${response.code}" }
                    val source = response.body?.source() ?: error("Müller Antwort fehlt")
                    check(!source.request(4_000_001)) { "Müller Antwort zu groß" }
                    source.readUtf8()
                }
                val next = parse(html, week)
                val pageIds = muellerListingIds(html)
                check(pageIds.isNotEmpty()) { "Müller Folgeseite ohne Produktdaten" }
                check(pageIds.any { it !in seenProducts }) { "Müller wiederholt eine Seite" }
                seenProducts.addAll(pageIds)
                next.products.forEach { products[it.id] = it }
                next.offers.forEach { offers[it.id] = it }
            }
            attempt.exceptionOrNull()?.let { error ->
                if (error is CancellationException) throw error
                return ProviderResult(products.values.toList(), offers.values.toList(),
                    sourceWarnings = listOf("Müller Import unvollständig: ${error.message.orEmpty().take(200)}"), preserveMissingOffers = true)
            }
        }
        error("Müller Seitenlimit erreicht")
    }

    private fun parseHolab(doc: org.jsoup.nodes.Document, week: OfferWeek): ProviderResult {
        val periods = linkedMapOf<String, Pair<String?, String?>>()
        doc.select("script[type=application/ld+json]").forEach { script ->
            val root = runCatching { Json.parseToJsonElement(script.data()).jsonObject }.getOrNull() ?: return@forEach
            (root["@graph"] as? JsonArray).orEmpty().forEach { raw ->
                (raw.jsonObject["makesOffer"] as? JsonArray).orEmpty().forEach { item ->
                    val offer = item.jsonObject
                    val name = offer["name"]?.jsonPrimitive?.content ?: return@forEach
                    periods[normalize(name).replace("-", "")] =
                        BerlinDate.toLocalDate(offer["validFrom"]?.jsonPrimitive?.content) to
                            BerlinDate.toLocalDate(offer["validThrough"]?.jsonPrimitive?.content)
                }
            }
        }
        val globalRange = Regex("Unsere Angebote vom (\\d{2}\\.\\d{2}\\.\\d{4})\\s*-\\s*(\\d{2}\\.\\d{2}\\.\\d{4})", RegexOption.IGNORE_CASE)
            .find(doc.text())?.let { match ->
                val format = java.time.format.DateTimeFormatter.ofPattern("dd.MM.yyyy")
                runCatching { java.time.LocalDate.parse(match.groupValues[1], format).toString() to
                    java.time.LocalDate.parse(match.groupValues[2], format).toString() }.getOrNull()
            }
        val products = mutableListOf<ProductEntity>()
        val offers = mutableListOf<OfferEntity>()
        doc.select("li.offer, div.offer").forEachIndexed { index, card ->
            val name = card.select(".offer__title").text()
            val price = ProviderParsing.price(card.selectFirst("data.offer__price")?.attr("value")) ?: return@forEachIndexed
            if (name.isBlank()) return@forEachIndexed
            val key = normalize(name).replace("-", "")
            val period = periods[key] ?: globalRange ?: error("HOL’AB! Gültigkeit für Artikel fehlt")
            val from = period.first?.let(java.time.LocalDate::parse) ?: error("HOL’AB! Angebotsbeginn fehlt")
            val until = period.second?.let(java.time.LocalDate::parse) ?: error("HOL’AB! Angebotsende fehlt")
            if (!offerWeekContains(from, until, week, now())) return@forEachIndexed
            val description = card.select(".offer__subtitle, .offer__details").text()
            val condition = card.select(".price-tag__prefix").text()
            val minimum = Regex("ab\\s+(\\d{1,2})\\s+Kisten", RegexOption.IGNORE_CASE).find(condition)
                ?.groupValues?.get(1)?.toIntOrNull()?.takeIf { it > 1 }
            check(condition.isBlank() || condition.equals("Top-Angebot", true) || minimum != null) { "HOL’AB! unbekannte Preisbedingung" }
            val single = Regex("1\\s+Kiste\\s+(\\d+[,.]\\d{2})", RegexOption.IGNORE_CASE)
                .find(description)?.groupValues?.get(1)?.let(ProviderParsing::price)?.let(ProviderParsing::cents)
            val productId = "$id-product-${normalize(name)}"
            products += ProductEntity(productId, name, normalizedKey = normalize(name))
            offers += OfferEntity(id = "$id:$index:${normalize(name)}", retailerId = id, productId = productId,
                externalId = "$index:${normalize(name)}", priceCents = ProviderParsing.cents(price),
                validFrom = from.toString(), validUntil = until.toString(), sourceUrl = offersUrl,
                imageUrl = imageUrl(card), cachedAt = System.currentTimeMillis(), description = description,
                packSize = ProviderParsing.packSize(card.select(".offer__details").text()),
                multiBuyQuantity = minimum, multiBuyTotalCents = minimum?.let { ProviderParsing.cents(price * it) },
                singlePriceCents = single, multiBuyCondition = condition.takeIf { minimum != null })
        }
        return ProviderResult(products, offers)
    }

    private fun normalize(value: String): String = Normalizer.normalize(value.lowercase(Locale.GERMAN), Normalizer.Form.NFKD)
        .replace("\\p{M}".toRegex(), "").replace("[^a-z0-9]+".toRegex(), "-").trim('-')
}
