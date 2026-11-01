package de.lesecuritae.korbuino.images

import java.math.BigDecimal
import java.text.Normalizer

/**
 * Same-article test for borrowing a product image from another retailer. Kotlin port of the server's
 * `supermarkt/image_match.py` (keep both in sync): titles reduce to their distinguishing words (brand + variant);
 * pack sizes and filler words are dropped. A different brand, flavour or Zero/regular variant is never a match.
 */
object ImageMatch {
    enum class Match { EXACT, SUBSTITUTE }

    private val generic = setOf(
        "energy", "drink", "drinks", "getraenk", "getraenke", "erfrischungsgetraenk", "erfrischungsgetraenke", "dose", "dosen",
        "einweg", "mehrweg", "flasche", "flaschen", "pet", "pack", "packung", "stuck", "stk", "st", "oder", "und", "mit", "ohne_pfand",
        "versch", "verschiedene", "sorten", "sorte", "je", "der", "die", "das", "von", "im", "in", "aus", "zzgl", "pfand", "ca", "original_preis",
    )
    private val pack = Regex(
        "(?:\\d+(?:[.,]\\d+)?\\s*[–-]\\s*)?(?:\\d+\\s*[x×]\\s*)?\\d+(?:[.,]\\d+)?\\s*(?:ml|cl|l|ltr|liter|g|gr|kg|mg|stk|st|x)\\b|\\b\\d+\\s*[x×]\\s*\\d+(?:[.,]\\d+)?",
        RegexOption.IGNORE_CASE,
    )
    private val amount = Regex("(?:(\\d+)\\s*[x×]\\s*)?(\\d+(?:[.,]\\d+)?)\\s*(ml|cl|l|ltr|liter|g|gr|kg|mg)\\b")
    private val factor = mapOf("ml" to 1.0, "cl" to 10.0, "l" to 1000.0, "ltr" to 1000.0, "liter" to 1000.0, "g" to 1.0, "gr" to 1.0, "kg" to 1000.0, "mg" to 0.001)

    private fun fold(text: String): String {
        val replaced = text.lowercase().replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
        return Normalizer.normalize(replaced, Normalizer.Form.NFKD).replace(Regex("\\p{M}+"), "")
    }

    fun packSignature(title: String): String =
        amount.findAll(fold(title)).map { match ->
            val count = match.groupValues[1]
            val value = BigDecimal.valueOf(Math.round(match.groupValues[2].replace(',', '.').toDouble() * factor.getValue(match.groupValues[3]) * 1000) / 1000.0)
            (if (count.isNotEmpty()) "${count}x" else "") + value.stripTrailingZeros().toPlainString()
        }.sorted().toList().joinToString("|")

    fun identityTokens(title: String, brand: String = ""): Set<String> =
        Regex("[a-z0-9]+").findAll(pack.replace(fold("$brand $title"), " ")).map { it.value }.filter { it !in generic }.toSet()

    fun matchArticle(title: String, otherTitle: String, brand: String = "", otherBrand: String = ""): Match? {
        val mine = identityTokens(title, brand)
        val theirs = identityTokens(otherTitle, otherBrand)
        if (mine.isEmpty() || theirs.isEmpty() || mine != theirs) return null
        val first = packSignature(title)
        return if (first.isNotEmpty() && first == packSignature(otherTitle)) Match.EXACT else Match.SUBSTITUTE
    }
}

/** A picture of the same article at another retailer, with a short label that says where it comes from. */
data class ImageFallback(val url: String, val referer: String, val note: String)

/**
 * Index of offers that have their own picture, keyed by article identity, so every offer finds its look-alikes in
 * O(1) instead of comparing all pairs (offer lists reach thousands of rows).
 */
class ImageSubstituteIndex(donors: List<Donor>) {
    data class Donor(val retailerId: String, val retailerName: String, val name: String, val brand: String, val imageUrl: String, val sourceUrl: String)

    private class Entry(val donor: Donor, val pack: String)

    private val byIdentity = HashMap<Set<String>, MutableList<Entry>>()

    init {
        donors.filter { it.imageUrl.isNotBlank() }.forEach { donor ->
            val identity = ImageMatch.identityTokens(donor.name, donor.brand)
            if (identity.isNotEmpty()) byIdentity.getOrPut(identity) { mutableListOf() }.add(Entry(donor, ImageMatch.packSignature(donor.name)))
        }
    }

    /** Up to [limit] pictures of the same article at other retailers, same pack first; never another variant or brand. */
    fun candidates(retailerId: String, name: String, brand: String, limit: Int = 3): List<ImageFallback> {
        val identity = ImageMatch.identityTokens(name, brand)
        val pack = ImageMatch.packSignature(name)
        return byIdentity[identity].orEmpty()
            .filter { it.donor.retailerId != retailerId }
            .map { it to (pack.isNotEmpty() && pack == it.pack) }
            .sortedWith(compareBy({ !it.second }, { it.first.donor.retailerId }))
            .distinctBy { it.first.donor.imageUrl }
            .take(limit)
            .map { (entry, exact) ->
                val from = entry.donor.retailerName
                ImageFallback(entry.donor.imageUrl, entry.donor.sourceUrl, if (exact) "Bild von $from (gleicher Artikel)" else "Ersatzbild von $from (Packung abweichend)")
            }
    }
}
