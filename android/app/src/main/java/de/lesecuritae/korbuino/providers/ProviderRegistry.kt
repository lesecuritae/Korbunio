package de.lesecuritae.korbuino.providers

/** Explicit registry prevents retailer logic from leaking into Compose. */
class ProviderRegistry(private val rewe: RetailerProvider) {
    fun all(): List<RetailerProvider> = listOf(rewe)
    fun byId(id: String): RetailerProvider? = all().firstOrNull { it.id == id }
}
