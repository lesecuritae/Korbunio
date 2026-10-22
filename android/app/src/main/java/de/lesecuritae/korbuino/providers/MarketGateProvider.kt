package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import org.jsoup.Jsoup

/**
 * Only asks [inner] for offers when the retailer has a store for the postal
 * code, like the Korbuino server does. Without one the result is empty, so the
 * retailer is not shown for that postal code instead of listing offers that do
 * not apply there.
 */
class MarketGateProvider(
    private val inner: RetailerProvider,
    private val confirmsAbsence: Boolean = true,
    private val hasMarket: suspend (String) -> Boolean,
) : RetailerProvider {
    override val id: String = inner.id
    override val displayName: String = inner.displayName
    override val challengeUrl: String? get() = inner.challengeUrl

    override suspend fun fetch(request: RetailerRequest): ProviderResult =
        if (hasMarket(request.postalCode)) inner.fetch(request)
        else ProviderResult(emptyList(), emptyList(), noLocalMarket = confirmsAbsence)
}

/** HOL'AB! lists its stores per postal code; an offer list is only relevant near one. */
class HolabMarkets(private val http: OkHttpClient, private val baseUrl: String = "https://holab.de") {
    suspend fun hasMarket(postalCode: String): Boolean = withContext(Dispatchers.IO) {
        val url = baseUrl.toHttpUrl().newBuilder().addPathSegment("maerkte").addQueryParameter("q", postalCode).build()
        val html = http.newCall(Request.Builder().url(url).header("Accept", "text/html").build()).execute().use { response ->
            check(response.isSuccessful) { "HOL'AB! Marktsuche HTTP ${response.code}" }
            response.body?.string().orEmpty()
        }
        Jsoup.parse(html).select("li.store").any { store ->
            store.selectFirst("a[href*=/maerkte/]") != null && postalCode in store.text()
        }
    }
}
