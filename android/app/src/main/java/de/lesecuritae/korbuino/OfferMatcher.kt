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
        // "energydrink", "Energy Drink" and "Energy-Drink" are one search, as in the server filter.
        val compactQuery = words.joinToString("")
        return offers
            .filter { offer ->
                val haystack = normalize("${offer.productName} ${offer.brand}")
                words.all { it in haystack } || (compactQuery.length >= 4 && compactQuery in haystack.replace(" ", ""))
            }
            .sortedBy { it.offer.priceCents }
    }

    /**
     * Current-offer rule of the list UI; [today] is a Europe/Berlin "yyyy-MM-dd". Dates may be plain or UTC instants
     * (converted to Berlin days). Blank = open-ended; an unparseable value is not shown (same rule as the shopping plan).
     */
    fun isShown(validFrom: String?, validUntil: String?, today: String, futureOnly: Boolean): Boolean {
        val from = BerlinDate.toLocalDate(validFrom)
        val until = BerlinDate.toLocalDate(validUntil)
        if (!validFrom.isNullOrBlank() && from == null) return false
        if (!validUntil.isNullOrBlank() && until == null) return false
        if (until != null && until < today) return false
        return if (futureOnly) from != null && from > today else from == null || from <= today
    }

    fun formatPrice(cents: Int): String = "${cents / 100},${(cents % 100).toString().padStart(2, '0')} €"

    private fun normalize(value: String): String =
        Normalizer.normalize(value.lowercase().replace("ß", "ss"), Normalizer.Form.NFD)
            .replace("\\p{M}+".toRegex(), "")
            .replace("[^a-z0-9]+".toRegex(), " ")
            .replace("\\bem\\s+eukal\\b".toRegex(), "emeukal")
            .trim()
}
