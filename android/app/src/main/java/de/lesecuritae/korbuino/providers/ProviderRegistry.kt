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
                FallbackRetailerProvider(GlobusProvider(http), MarktguruProvider("Globus", http)),
                AldiNordProvider(http),
                HtmlFlyerProvider(
                    "aldi-sued", "ALDI Süd", "https://www.aldi-sued.de/angebote", http,
                    renderedHtmlProvider = { RenderedPageStore.consume("https://www.aldi-sued.de/angebote") },
                ),
                // Regional prices first (needs the city); without it the default-region page and Marktguru.
                FallbackRetailerProvider(
                    KauflandProvider(http),
                    FallbackRetailerProvider(
                        HtmlFlyerProvider("kaufland", "Kaufland", "https://filiale.kaufland.de/angebote/uebersicht.html?kloffer-week=current", http),
                        MarktguruProvider("Kaufland", http),
                    ),
                ),
                FallbackRetailerProvider(
                    HtmlFlyerProvider(
                        "rossmann", "Rossmann", "https://www.rossmann.de/de/angebote/m/angebote/", http,
                        renderedHtmlProvider = { RenderedPageStore.consume("https://www.rossmann.de/de/angebote/m/angebote/") },
                    ),
                    FallbackRetailerProvider(
                        KaufdaRetailerProvider("rossmann", "Rossmann", "Rossmann", "Rossmann", http),
                        MarktguruProvider("Rossmann", http, providerId = "rossmann", providerDisplayName = "Rossmann"),
                    ),
                ),
                FallbackRetailerProvider(
                    HtmlFlyerProvider(
                        "mueller",
                        "Müller",
                        "https://www.mueller.de/c/online-angebote/",
                        http,
                        renderedHtmlProvider = MuellerRenderedPageStore::consume,
                    ),
                    FallbackRetailerProvider(
                        KaufdaRetailerProvider("mueller", "Müller", "Müller", "Mueller", http),
                        MarktguruProvider("Müller", http, providerId = "mueller", providerDisplayName = "Müller"),
                    ),
                ),
                FallbackRetailerProvider(
                    EdekaProvider(http),
                    FallbackRetailerProvider(
                        KaufdaRetailerProvider("edeka", "EDEKA", "EDEKA", "Edeka", http),
                        MarktguruProvider("EDEKA", http, providerId = "edeka", providerDisplayName = "EDEKA"),
                    ),
                    surfacePrimaryFailureWhenFallbackEmpty = true,
                ),
                MarketGateProvider(HtmlFlyerProvider("holab", "HOL'AB!", "https://holab.de/angebote", http), HolabMarkets(http)::hasMarket),
                // trinkgut has no public API the app can use. Marktguru lists its offers
                // per postal code and simply has none where no store is nearby, which
                // is the right answer there; KaufDA is the fallback.
                FallbackRetailerProvider(
                    MarktguruProvider("trinkgut", http, providerId = "trinkgut", providerDisplayName = "trinkgut"),
                    KaufdaRetailerProvider("trinkgut", "trinkgut", "trinkgut", "Trinkgut", http),
                ),
                FallbackRetailerProvider(
                    HtmlFlyerProvider("netto-schwarz", "Netto schwarz", "https://netto.de/angebote/", http),
                    MarktguruProvider("Netto mit dem Scottie", http),
                ),
                MarktguruProvider(
                    "Netto Marken-Discount",
                    http,
                    providerId = "netto-marken",
                    providerDisplayName = "Netto Marken-Discount",
                ),
                DmProvider(http),
                MarktguruProvider("famila Nordwest", http),
                MarktguruProvider("Combi", http),
                AktivIrmaProvider(http),
                MarktguruProvider("Lidl", http),
                MarktguruProvider("PENNY", http),
            ),
        )
    }
}
