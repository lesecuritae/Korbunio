package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity

/**
 * One retailer whose offers are spread over several public pages (for example Müller's department "Aktionen" pages).
 * Failing pages are skipped as long as at least one page works; if every page fails, the first failure is reported
 * so browser handoff and diagnostics keep working.
 */
class CombinedPagesProvider(
    override val id: String,
    override val displayName: String,
    private val pages: List<RetailerProvider>,
) : RetailerProvider {
    init { require(pages.isNotEmpty()) }

    override val challengeUrl: String? get() = pages.first().challengeUrl

    override suspend fun fetch(request: RetailerRequest): ProviderResult {
        val results = fetchProviderBatch(pages, request, maxConcurrent = 2)
        val successes = results.mapNotNull { it.second.getOrNull() }
        if (successes.isEmpty()) {
            throw results.firstNotNullOf { it.second.exceptionOrNull() }
        }
        val products: List<ProductEntity> = successes.flatMap { it.products }.distinctBy { it.id }
        val offers: List<OfferEntity> = successes.flatMap { it.offers }.distinctBy { it.id }
        return ProviderResult(products, offers)
    }
}

/** Müller departments whose public "Aktionen" pages list priced offers. */
object MuellerPages {
    val DEPARTMENTS = listOf("drogerie", "haushalt", "schreibwaren", "spielwaren")
}
