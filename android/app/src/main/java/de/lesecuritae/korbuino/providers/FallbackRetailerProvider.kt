package de.lesecuritae.korbuino.providers

/**
 * Keeps the official source first and uses the existing regional catalogue
 * only when the official source cannot provide offers. Source and image URLs
 * from the regional response remain attached to every offer.
 */
class FallbackRetailerProvider(
    private val primary: RetailerProvider,
    private val fallback: RetailerProvider,
    private val surfacePrimaryFailureWhenFallbackEmpty: Boolean = false,
) : RetailerProvider {
    override val id: String = primary.id
    override val displayName: String = primary.displayName
    override val challengeUrl: String? get() = primary.challengeUrl

    override suspend fun fetch(request: RetailerRequest): ProviderResult {
        val directAttempt = runCatching { primary.fetch(request) }
        val direct = directAttempt.getOrNull()
        if (direct != null && direct.offers.isNotEmpty()) return direct
        val regionalAttempt = runCatching { fallback.fetch(request) }
        val regional = regionalAttempt.getOrElse { fallbackError ->
            // An empty result still proves that the primary source is
            // reachable. A secondary transport failure must not turn that
            // valid state into a false retailer outage.
            if (direct != null) return direct
            throw fallbackError
        }
        if (regional.offers.isEmpty() && surfacePrimaryFailureWhenFallbackEmpty) {
            directAttempt.exceptionOrNull()?.let { throw it }
        }
        return regional.copy(
            offers = regional.offers.map { offer ->
                offer.copy(id = "$id:${offer.externalId}", retailerId = id)
            },
        )
    }
}
