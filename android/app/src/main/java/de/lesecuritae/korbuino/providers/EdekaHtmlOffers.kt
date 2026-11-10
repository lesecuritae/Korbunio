package de.lesecuritae.korbuino.providers

import de.lesecuritae.korbuino.BerlinDate
import kotlinx.serialization.json.*
import org.jsoup.Jsoup
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/** Public server-rendered offers of the selected market; never a global product search. */
internal object EdekaHtmlOffers {
    private val json = Json { ignoreUnknownKeys = true }
    private val period = Regex("""Gültig\s+vom\s+(\d{2}\.\d{2}\.\d{4})\s+bis\s+zum\s+(\d{2}\.\d{2}\.\d{4})""", RegexOption.IGNORE_CASE)
    private val cash = Regex("""^(?:Festpreis|Rabattierter Preis)\s+von\s+(\d+[.,]\d{2})\s*€""", RegexOption.IGNORE_CASE)
    private val app = Regex("""^App Preis\s+von\s+(\d+[.,]\d{2})\s*€""", RegexOption.IGNORE_CASE)
    private val date = DateTimeFormatter.ofPattern("dd.MM.uuuu")

    fun parse(html: String, sourceUrl: String): JsonObject {
        val page = Jsoup.parse(html, sourceUrl)
        val periods = period.findAll(page.text()).map { it.groupValues[1] to it.groupValues[2] }.distinct().toList()
        check(periods.size == 1) { "EDEKA: kein eindeutiger öffentlicher Marktzeitraum" }
        val start = LocalDate.parse(periods.single().first, date)
        val end = LocalDate.parse(periods.single().second, date)
        check(start <= end) { "EDEKA: widersprüchlicher Prospektzeitraum" }
        val docs = page.select("dialog[id^=dialog-angebot-][data-tracking-event]").mapNotNull { dialog ->
            val event = json.parseToJsonElement(dialog.attr("data-tracking-event")).jsonArray
            val item = event[1].jsonObject
            if (event[0].jsonPrimitive.content != "view_promotion" || item["promotion_type"]?.jsonPrimitive?.content != "OFFER") return@mapNotNull null
            val id = item["promotion_id"]?.jsonPrimitive?.contentOrNull
            val name = item["promotion_item_name"]?.jsonPrimitive?.contentOrNull?.trim()
            val until = item["promotion_item_expiration_date"]?.jsonPrimitive?.contentOrNull?.let(BerlinDate::toLocalDate)?.let(LocalDate::parse)
            check(!id.isNullOrBlank() && !name.isNullOrBlank() && until != null && until >= start) { "EDEKA: unvollständige öffentliche Angebotsmetadaten" }
            val labels = dialog.select("span.sr-only").map { it.text().trim() }
            val prices = labels.mapNotNull { cash.find(it)?.groupValues?.get(1)?.let(ProviderParsing::price) }.distinct()
            val members = labels.mapNotNull { app.find(it)?.groupValues?.get(1)?.let(ProviderParsing::price) }.distinct()
            check(prices.size == 1 && prices.single() > 0 && members.size <= 1) { "EDEKA: öffentlicher Kassenpreis nicht eindeutig" }
            val description = dialog.selectFirst("p.line-clmap-2")?.text().orEmpty()
            val image = dialog.select("img[src]").firstOrNull { it.absUrl("src").startsWith("https://offer-images.api.edeka/") && !it.attr("src").contains("LOG_") }?.absUrl("src")
            val bundle = Regex("""(\d{1,3})\s*Stück\s*,\s*Preis\s+beim\s+Kauf\s+von\s+1\s*Stück\s*:\s*€?\s*(\d+[.,]\d{2})""", RegexOption.IGNORE_CASE).find(description)
            val quantity = bundle?.groupValues?.get(1)?.toIntOrNull()?.takeIf { it > 1 }
            check(quantity == null || members.isEmpty()) { "EDEKA: Mehrkauf mit App-Preis nicht eindeutig kombiniert" }
            buildJsonObject {
                put("angebotid", id); put("titel", name); put("preis", prices.single() / (quantity ?: 1))
                if (quantity != null) {
                    put("multi_buy_quantity", quantity); put("multi_buy_total_cents", ProviderParsing.cents(prices.single()))
                    put("single_price_cents", ProviderParsing.cents(ProviderParsing.price(bundle!!.groupValues[2])!!))
                    put("pack_size", "1 Stück"); put("multi_buy_condition", "$quantity Stück zum veröffentlichten Gesamtpreis")
                }
                put("beschreibung", description); put("gueltig_von", start.toString()); put("gueltig_bis", minOf(end, until).toString())
                image?.let { put("bild_web130", it) }
                members.singleOrNull()?.takeIf { it > 0 && it < prices.single() }?.let { put("edeka_app_preis", it) }
                put("gtins", JsonArray((item["promotion_item_included_products"] as? JsonArray).orEmpty().filter {
                    val text = it.jsonPrimitive.contentOrNull.orEmpty()
                    text.length in setOf(8, 12, 13, 14) && text.all(Char::isDigit)
                }))
            }
        }
        check(docs.isNotEmpty()) { "EDEKA: keine öffentlichen Angebotsdialoge" }
        return buildJsonObject { put("gueltig_von", start.toString()); put("gueltig_bis", end.toString()); put("docs", JsonArray(docs)) }
    }
}
