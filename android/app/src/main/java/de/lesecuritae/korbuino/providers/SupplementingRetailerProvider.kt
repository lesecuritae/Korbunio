package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import java.util.Locale
import kotlinx.coroutines.CancellationException

/** Complements a filled catalogue; failures remain visible without discarding primary data. */
class SupplementingRetailerProvider(
    private val primary: RetailerProvider,
    private val supplement: RetailerProvider,
) : RetailerProvider {
    override val id = primary.id
    override val displayName = primary.displayName
    override val challengeUrl get() = primary.challengeUrl

    override suspend fun fetch(request: RetailerRequest): ProviderResult {
        suspend fun attempt(provider: RetailerProvider): Result<ProviderResult> = try {
            val result = provider.fetch(request)
            check(result.offers.all { it.retailerId == id }) { "Quelle liefert falschen Händler" }
            check(result.offers.all { offer -> result.products.any { it.id == offer.productId } }) { "Angebot ohne Produkt" }
            Result.success(result)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Exception) { Result.failure(error) }
        val firstAttempt = attempt(primary)
        val first = firstAttempt.getOrNull()
        if (first?.noLocalMarket == true) return first
        val secondAttempt = attempt(supplement)
        val second = secondAttempt.getOrElse { error ->
            if (first == null) throw firstAttempt.exceptionOrNull()!!
            return first.copy(preserveMissingOffers = true, sourceWarnings = first.sourceWarnings +
                "Ergänzende Quelle fehlgeschlagen (${error.javaClass.simpleName}): ${error.message.orEmpty().take(160)}")
        }
        check(second.offers.all { it.retailerId == id }) { "Ergänzende Quelle liefert falschen Händler" }
        val products = linkedMapOf<String, ProductEntity>()
        ((first?.products ?: emptyList()) + second.products).forEach { products.putIfAbsent(it.id, it) }
        fun text(value: String) = value.lowercase(Locale.ROOT).replace(Regex("[^\\p{L}\\p{N}]+"), " ").trim()
        fun key(offer: OfferEntity): List<Any?> {
            val product: ProductEntity = products[offer.productId] ?: error("Angebot ohne Produkt")
            return listOf(offer.retailerId, text(product.name), text(product.brand),
                offer.priceCents, offer.packSize?.let(::text), offer.validFrom, offer.validUntil,
                text(offer.description), offer.loyaltyProgram, offer.loyaltyPriceCents,
                offer.loyaltyBenefitsJson, offer.multiBuyQuantity, offer.multiBuyTotalCents, offer.depositCents)
        }
        val offers = ((first?.offers ?: emptyList()) + second.offers).distinctBy(::key)
        val used = offers.map { it.productId }.toSet()
        return ProviderResult(products.values.filter { it.id in used }, offers,
            storeId = first?.storeId ?: second.storeId,
            preserveMissingOffers = first == null || first.preserveMissingOffers || second.preserveMissingOffers,
            sourceWarnings = (first?.sourceWarnings ?: listOf("Primärquelle fehlgeschlagen")) + second.sourceWarnings)
    }
}
