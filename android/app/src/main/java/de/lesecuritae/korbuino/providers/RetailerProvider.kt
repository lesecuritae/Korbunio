package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity

data class RetailerRequest(
    val postalCode: String,
    val citySlug: String? = null,
    val marketId: String? = null,
    val week: OfferWeek = OfferWeek.CURRENT,
)
enum class OfferWeek { CURRENT, NEXT }
data class ProviderResult(val products: List<ProductEntity>, val offers: List<OfferEntity>, val storeId: String? = null)

interface RetailerProvider {
    val id: String
    val displayName: String
    /** Optional first-party page used for a user-mediated anti-bot challenge. */
    val challengeUrl: String? get() = null
    suspend fun fetch(request: RetailerRequest): ProviderResult
}
