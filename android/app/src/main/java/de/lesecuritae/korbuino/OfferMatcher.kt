package de.lesecuritae.korbuino

import java.text.Normalizer

/** Finds the loaded offers that belong to a shopping-list entry such as "Nutella". */
object OfferMatcher {
    /**
     * Offers whose name contains every word of [query], cheapest first. Case,
     * accents and ß are ignored, so "nutella" finds "Nutella Nuss-Nougat-Creme".
     */
    fun matches(query: String, offers: List<OfferDisplay>): List<OfferDisplay> {
        val words = normalize(query).split(' ').filter { it.length >= 2 }
        if (words.isEmpty()) return emptyList()
        return offers
            .filter { offer ->
                val haystack = normalize(offer.productName)
                words.all { it in haystack }
            }
            .sortedBy { it.offer.priceCents }
    }

    fun formatPrice(cents: Int): String = "${cents / 100},${(cents % 100).toString().padStart(2, '0')} €"

    private fun normalize(value: String): String =
        Normalizer.normalize(value.lowercase().replace("ß", "ss"), Normalizer.Form.NFD)
            .replace("\\p{M}+".toRegex(), "")
            .replace("[^a-z0-9]+".toRegex(), " ")
            .replace("\\bem\\s+eukal\\b".toRegex(), "emeukal")
            .trim()
}
