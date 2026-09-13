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

object ProviderImportPolicy {
    private val maximumCurrentOffers = mapOf(
        "aldi-nord" to 350,
        "aldi-sued" to 300,
        "marktguru-lidl" to 500,
        "marktguru-penny" to 350,
        "netto-marken" to 500,
        "kaufland" to 600,
        "dm" to 600,
        "globus" to 600,
        "rossmann" to 300,
        "holab" to 150,
        "marktguru-famila-nordwest" to 500,
    )

    /** Reject clearly implausible imports before they can replace offline data. */
    fun rejectionReason(providerId: String, count: Int, previousCount: Int = 0): String? {
        // Server mode returns the already consolidated multi-retailer result;
        // per-provider limits therefore do not apply to it.
        if (providerId == "server") return null
        if (count <= 0) return "keine aktuell gültigen Angebote"
        val maximum = maximumCurrentOffers[providerId] ?: 750
        if (count > maximum) return "$count Angebote überschreiten die Plausibilitätsgrenze $maximum"
        if (previousCount in 20..maximum && count > previousCount * 3 && count - previousCount > 150) {
            return "$count Angebote weichen ungewöhnlich stark vom letzten gültigen Stand $previousCount ab"
        }
        return null
    }
}

interface RetailerProvider {
    val id: String
    val displayName: String
    /** Optional first-party page used for a user-mediated anti-bot challenge. */
    val challengeUrl: String? get() = null
    suspend fun fetch(request: RetailerRequest): ProviderResult
}
