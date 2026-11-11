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
/** Match the shared backend week boundary, including the Sunday handover. */
internal fun offerWeekContains(from: java.time.LocalDate, until: java.time.LocalDate, week: OfferWeek, today: java.time.LocalDate): Boolean {
    val day = if (today.dayOfWeek == java.time.DayOfWeek.SUNDAY) today.plusDays(1) else today
    val next = day.with(java.time.temporal.TemporalAdjusters.previousOrSame(java.time.DayOfWeek.MONDAY)).plusWeeks(1)
    return from <= until && if (week == OfferWeek.NEXT) from < next.plusWeeks(1) && until >= next
        else from < next && until >= day
}

data class ProviderResult(
    val products: List<ProductEntity>, val offers: List<OfferEntity>, val storeId: String? = null,
    val noLocalMarket: Boolean = false,
    val unavailableRetailerIds: List<String> = emptyList(),
    val sourceWarnings: List<String> = emptyList(),
    val paginationComplete: Boolean = false,
    val preserveMissingOffers: Boolean = false,
    val preserveRetailerIds: List<String> = emptyList(),
) {
    init {
        require(!noLocalMarket || (products.isEmpty() && offers.isEmpty()))
        require(offers.none { it.retailerId in unavailableRetailerIds })
    }
    fun unavailableRetailers(providerId: String): List<String> =
        unavailableRetailerIds + if (noLocalMarket) listOf(providerId) else emptyList()

    fun preservedRetailers(providerId: String): List<String> = if (!preserveMissingOffers) emptyList()
        else preserveRetailerIds.ifEmpty { listOf(providerId) + offers.map { it.retailerId } }.distinct()
}

object ProviderImportPolicy {
    fun rejectionReason(providerId: String, result: ProviderResult, previousCount: Int = 0): String? =
        if (result.noLocalMarket) null else rejectionReason(providerId, result.offers.size, if (result.paginationComplete) 0 else previousCount)

    private val maximumCurrentOffers = mapOf(
        "aldi-nord" to 700,
        "aldi-sued" to 300,
        // Two independently published regional catalogues can exceed 800;
        // keep a finite guard without rejecting the verified supplementary range.
        "marktguru-lidl" to 1200,
        "marktguru-penny" to 350,
        "netto-marken" to 500,
        // Verified regional assortments can exceed 600 when week-start and
        // monthly promotions overlap (Konstanz: 629, Leipzig-Reudnitz: 618).
        // Each Kaufland fetch targets one store and filters by date and local
        // article availability. This is not a combined all-retailer limit.
        "kaufland" to 800,
        "dm" to 2000,
        "mueller" to 20000,
        "globus" to 900,
        "rossmann" to 500,
        "holab" to 150,
        "marktguru-famila-nordwest" to 500,
        "marktguru-combi" to 500,
        "aktiv-irma" to 300,
    )

    /** Reject clearly implausible imports before they can replace offline data. */
    fun rejectionReason(providerId: String, count: Int, previousCount: Int = 0): String? {
        // Server mode returns the already consolidated multi-retailer result;
        // per-provider limits therefore do not apply to it.
        if (providerId == "server" || providerId == "korbuino-server") return null
        if (count <= 0) return "keine aktuell gültigen Angebote"
        val maximum = maximumCurrentOffers[providerId] ?: 750
        if (count > maximum) return "$count Angebote überschreiten die Plausibilitätsgrenze $maximum"
        // The former first-page-only Müller count is not a valid catalogue-size baseline.
        if (providerId != "mueller" && previousCount in 20..maximum && count > previousCount * 3 && count - previousCount > 150) {
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
