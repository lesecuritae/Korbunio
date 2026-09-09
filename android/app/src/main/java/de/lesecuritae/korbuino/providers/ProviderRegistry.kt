package de.lesecuritae.korbuino.providers

/** Explicit registry prevents retailer logic from leaking into Compose. */
class ProviderRegistry(private val providers: List<RetailerProvider>) {
    constructor(rewe: RetailerProvider, globus: RetailerProvider) : this(listOf(rewe, globus))
    fun all(): List<RetailerProvider> = providers
    fun byId(id: String): RetailerProvider? = all().firstOrNull { it.id == id }

    companion object {
        fun default(http: okhttp3.OkHttpClient): ProviderRegistry = ProviderRegistry(
            listOf(
                ReweProvider(http, fallback = MarktguruProvider("REWE", http)),
                GlobusProvider(http),
                HtmlFlyerProvider("aldi-nord", "ALDI Nord", "https://www.aldi-nord.de/angebote.html", http),
                HtmlFlyerProvider("aldi-sued", "ALDI Süd", "https://www.aldi-sued.de/angebote", http),
                HtmlFlyerProvider("kaufland", "Kaufland", "https://filiale.kaufland.de/angebote/uebersicht.html?kloffer-week=current", http),
                HtmlFlyerProvider("rossmann", "Rossmann", "https://www.rossmann.de/de/angebote/m/angebote/", http),
                HtmlFlyerProvider("mueller", "Müller", "https://www.mueller.de/c/online-angebote/", http),
                HtmlFlyerProvider("holab", "HOL'AB!", "https://holab.de/angebote", http),
                HtmlFlyerProvider("netto-schwarz", "Netto mit Hund", "https://netto.de/angebote/", http),
                HtmlFlyerProvider("netto-marken", "Netto Marken-Discount", "https://www.netto-online.de/angebote/", http),
                DmProvider(http),
                MarktguruProvider("Combi", http),
                MarktguruProvider("famila Nordwest", http),
                MarktguruProvider("Lidl", http),
                MarktguruProvider("PENNY", http),
            ),
        )
    }
}
