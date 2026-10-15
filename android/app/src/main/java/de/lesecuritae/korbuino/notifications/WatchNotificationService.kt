package de.lesecuritae.korbuino.notifications

import de.lesecuritae.korbuino.data.*
import de.lesecuritae.korbuino.OfferPricing
import de.lesecuritae.korbuino.LoyaltyBenefits
import de.lesecuritae.korbuino.security.SecureStore
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import java.security.MessageDigest
import java.text.Normalizer
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.TemporalAdjusters
import java.util.Locale
import java.util.UUID

object WatchMatcher {
    fun normalize(text: String): String = Normalizer.normalize(text.lowercase(Locale.ROOT), Normalizer.Form.NFKD)
        .replace("\\p{M}".toRegex(), "").replace("[^a-z0-9]+".toRegex(), " ").replace("\\bem\\s+eukal\\b".toRegex(), "emeukal").trim()

    fun matches(watch: FavoriteEntity, product: ProductEntity, offer: OfferEntity, postalCode: String, today: LocalDate, selectedPrograms: Set<String> = emptySet()): Boolean {
        if (watch.postalCode.isNotBlank() && watch.postalCode != postalCode) return false
        val query = normalize(watch.query)
        if (query.isBlank()) return false
        val tokens = normalize("${product.brand} ${product.name}").split(' ').toSet()
        if (!query.split(' ').all(tokens::contains)) return false
        val retailers = runCatching { Json.parseToJsonElement(watch.preferredRetailerIdsJson).jsonArray.map { it.jsonPrimitive.content } }.getOrElse { return false }
        if (retailers.isNotEmpty() && offer.retailerId !in retailers) return false
        // Cashback is credit, never a reduction of the cash price.
        val cashPrice = OfferPricing.quote(offer, (offer.multiBuyQuantity ?: 1).coerceAtLeast(1), selectedPrograms).totalCents ?: return false
        if (watch.maxPriceCents != null && cashPrice > watch.maxPriceCents) return false
        val from = offer.validFrom?.let { runCatching { LocalDate.parse(it) }.getOrNull() } ?: return false
        val until = offer.validUntil?.let { runCatching { LocalDate.parse(it) }.getOrNull() } ?: return false
        if (until < today || until < from) return false
        val monday = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
        val next = monday.plusWeeks(1)
        return (watch.includeCurrentWeek && from < next && until >= today) ||
            (watch.includeNextWeek && from < next.plusWeeks(1) && until >= next)
    }

    fun receiptKey(watch: FavoriteEntity, product: ProductEntity, offer: OfferEntity, selectedPrograms: Set<String> = emptySet()): String {
        val fields = listOf(watch.productId, normalize(product.name), offer.retailerId,
            OfferPricing.quote(offer, (offer.multiBuyQuantity ?: 1).coerceAtLeast(1), selectedPrograms).totalCents.toString(), offer.validFrom.orEmpty(), offer.validUntil.orEmpty(),
            offer.multiBuyQuantity.toString(), offer.multiBuyTotalCents.toString(), offer.multiBuyCondition.orEmpty(), offer.packSize.orEmpty(),
            runCatching { java.net.URI(offer.sourceUrl).let { "${it.host}${it.path}" } }.getOrDefault(""))
        val value = fields.joinToString("") { "${it.length}:$it" }
        return MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    }
}

data class EvaluationResult(val submitted: Int = 0, val failed: Int = 0)

class WatchNotificationService(
    private val database: KorbuinoDatabase,
    private val secureStore: SecureStore,
    http: OkHttpClient = OkHttpClient(),
) {
    private val sender = NtfySender(http)
    suspend fun evaluate(postalCode: String): EvaluationResult {
        val settings = secureStore.loadNtfySettings()
        if (!settings.enabled || settings.topicUrl.isBlank()) return EvaluationResult()
        val watches = database.favoriteDao().all().filter { it.notificationsEnabled }
        if (watches.isEmpty()) return EvaluationResult()
        val selectedPrograms = secureStore.get("loyalty_programs").orEmpty().split(',').filter(String::isNotBlank).toSet()
        val products = database.productDao().all().associateBy { it.id }
        val today = LocalDate.now(ZoneId.of("Europe/Berlin"))
        var submitted = 0
        var failed = 0
        for (offer in database.offerDao().all()) {
            val product = products[offer.productId] ?: continue
            for (watch in watches) {
                if (!WatchMatcher.matches(watch, product, offer, postalCode, today, selectedPrograms)) continue
                val key = WatchMatcher.receiptKey(watch, product, offer, selectedPrograms)
                val owner = UUID.randomUUID().toString()
                val dao = database.watchNotificationDao()
                if (!dao.claim(key, owner, System.currentTimeMillis())) continue
                val amount = OfferPricing.quote(offer, (offer.multiBuyQuantity ?: 1).coerceAtLeast(1), selectedPrograms).totalCents ?: continue
                val price = String.format(Locale.GERMANY, "%.2f €", amount / 100.0)
                val condition = if ((offer.multiBuyQuantity ?: 0) > 1) {
                    val unit = String.format(Locale.GERMANY, "%.2f €", amount / 100.0 / offer.multiBuyQuantity!!)
                    " (${offer.multiBuyQuantity} Stück, Mindestmenge ${offer.multiBuyQuantity}; $unit je Stück bei Abnahme dieser Menge; ${offer.multiBuyCondition.orEmpty()})"
                } else ""
                val member = if ((offer.multiBuyQuantity ?: 0) <= 1 && amount < offer.priceCents) " (nur mit ausgewähltem Kundenprogramm)" else ""
                val credit = LoyaltyBenefits.forOffer(offer).filter { it.kind == "cashback" && it.programId in selectedPrograms }
                    .joinToString("; ") { "${it.cents / 100.0} € Guthaben nach Einkauf, kein Sofortrabatt" }
                    .let { if (it.isBlank()) "" else "\n$it" }
                val pack = offer.packSize?.let { " – $it" }.orEmpty()
                val validity = if (offer.validFrom!! > today.toString()) "Ab ${offer.validFrom} bis ${offer.validUntil}" else "Gültig ${offer.validFrom} bis ${offer.validUntil}"
                val result = sender.send(settings, "${product.name}$pack – $price$condition$member bei ${offer.retailerId}\n$validity$credit")
                if (result.submitted) {
                    dao.submitted(key, owner, System.currentTimeMillis())
                    submitted++
                } else {
                    // Three durable attempts maximum, with a delay between refreshes.
                    dao.failed(key, owner, if (result.retryable) System.currentTimeMillis() + 300_000 else Long.MAX_VALUE)
                    failed++
                }
            }
        }
        return EvaluationResult(submitted, failed)
    }
}
