package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withTimeoutOrNull
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** Interactive offer loading only: stock never changes offers, prices or import acceptance. */
internal class StockEnrichingProvider(
    private val source: RetailerProvider,
    private val rossmann: suspend (String, List<String>) -> List<StockProduct> = { postal, dans -> RossmannStockClient.shared.check(postal, dans) },
    private val dm: suspend (String, List<String>) -> List<StockProduct> = { postal, dans -> DmStockClient.shared.check(postal, dans) },
) : RetailerProvider {
    override val id get() = source.id
    override val displayName get() = source.displayName
    override val challengeUrl get() = source.challengeUrl

    override suspend fun fetch(request: RetailerRequest): ProviderResult {
        val result = source.fetch(request)
        val summaries = result.stockSummaries.toMutableMap()
        for (offer in result.offers) {
            if (offer.retailerId in setOf("dm", "rossmann", "Rossmann"))
                summaries.putIfAbsent(offer.id, "Bestand unbekannt: Artikelzuordnung nicht belegt.")
        }
        for ((retailer, length) in listOf("Rossmann" to 6, "dm" to 7)) {
            val candidates = result.stockReferences.filter { (offerId, ref) ->
                result.offers.any { it.id == offerId } && ref.retailer == retailer && Regex("[0-9]{$length}").matches(ref.dan)
            }
            val dans = result.offers.sortedBy { it.priceCents }.mapNotNull { candidates[it.id]?.dan }.distinct().take(5)
            if (dans.isEmpty()) continue
            val reply = try {
                (withTimeoutOrNull(20_000) { (if (retailer == "dm") dm else rossmann)(request.postalCode, dans) }
                    ?: dans.map { StockProduct(it, error = "Zeitlimit für Bestandsabruf; Angebote bleiben erhalten") }).associateBy { it.dan }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { dans.associateWith { StockProduct(it, error = error.message ?: "Bestandsabruf fehlgeschlagen") } }
            for ((offerId, ref) in candidates) {
                summaries[offerId] = if (ref.dan !in dans) "Bestand nicht geprüft: Abfragelimit (fünf Artikel je Händler); kein Nullbestand."
                    else reply[ref.dan]?.let(::stockSummary) ?: "Bestand unbekannt: keine passende Artikelantwort."
            }
        }
        return result.copy(stockSummaries = summaries)
    }
}

internal fun stockSummary(product: StockProduct): String {
    product.error?.let { return "Bestand unbekannt: $it" }
    val checked = runCatching { DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm:ss")
        .withZone(ZoneId.of("Europe/Berlin")).format(Instant.parse(product.checkedAt)) }.getOrDefault(product.checkedAt)
    val lines = product.stores.take(3).map { store ->
        val value = when {
            store.status == "NUR_ONLINE" -> "nur online, nicht im Filialsortiment"
            store.inStock == false -> "nicht verfügbar"
            store.inStock == true && store.minimum != null -> "${if (store.exact) "" else "mindestens "}${store.minimum} Stück"
            store.inStock == true -> "verfügbar, Menge unbekannt"
            else -> "Bestand unbekannt"
        }
        "${store.postalCode} ${store.city}, ${store.street}: $value"
    }.ifEmpty { listOf("Keine bestätigten Filialdaten; das bedeutet nicht ausverkauft.") }
    return "Bestand jetzt ($checked${if (product.fromCache) ", zwischengespeichert" else ""}):\n" + lines.joinToString("\n") +
        "\nBuchbestand, keine Reservierung oder Garantie für Regalware."
}
