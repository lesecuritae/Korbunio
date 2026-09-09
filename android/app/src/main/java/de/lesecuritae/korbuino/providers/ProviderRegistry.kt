package de.lesecuritae.korbuino.providers

/** Explicit registry prevents retailer logic from leaking into Compose. */
class ProviderRegistry(private val providers: List<RetailerProvider>) {
    constructor(rewe: RetailerProvider, globus: RetailerProvider) : this(listOf(rewe, globus))
    fun all(): List<RetailerProvider> = providers
    fun byId(id: String): RetailerProvider? = all().firstOrNull { it.id == id }
}
