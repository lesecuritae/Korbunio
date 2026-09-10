package de.lesecuritae.korbuino.providers

/**
 * Keeps the official source first and uses the existing regional catalogue
 * only when the official source cannot provide offers. Source and image URLs
 * from the regional response remain attached to every offer.
 */
class FallbackRetailerProvider(
    private val primary: RetailerProvider,
    private val fallback: RetailerProvider,
) : RetailerProvider {
    override val id: String = primary.id
    override val displayName: String = primary.displayName
    override val challengeUrl: String? get() = primary.challengeUrl

    override suspend fun fetch(request: RetailerRequest): ProviderResult {
        val direct = runCatching { primary.fetch(request) }.getOrNull()
        if (direct != null && direct.offers.isNotEmpty()) return direct
        val regional = fallback.fetch(request)
        return regional.copy(
            offers = regional.offers.map { offer ->
                offer.copy(id = "$id:${offer.externalId}", retailerId = id)
            },
        )
    }
}
