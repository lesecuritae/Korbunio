package de.lesecuritae.korbuino

import de.lesecuritae.korbuino.data.OfferEntity
import org.junit.Assert.assertEquals
import org.junit.Test

class OfferMatcherTest {
    private fun offer(id: String, name: String, cents: Int) = OfferDisplay(
        offer = OfferEntity(
            id = id, retailerId = "rewe", productId = id, externalId = id,
            priceCents = cents, sourceUrl = "https://example.org", cachedAt = 0L,
        ),
        productName = name,
    )

    @Test
    fun findsByWordIgnoringCaseAndSortsByPrice() {
        val offers = listOf(offer("1", "Nutella Nuss-Nougat-Creme 450 g", 349), offer("2", "Nutella B-ready", 199), offer("3", "Butter", 149))
        assertEquals(listOf("2", "1"), OfferMatcher.matches("nutella", offers).map { it.offer.id })
    }

    @Test
    fun ignoresAccentsAndSharpS() {
        assertEquals(1, OfferMatcher.matches("susser senf", listOf(offer("1", "Süßer Senf mittelscharf", 99))).size)
    }

    @Test
    fun requiresEveryWord() {
        assertEquals(0, OfferMatcher.matches("nutella brot", listOf(offer("1", "Nutella B-ready", 199))).size)
    }

    @Test
    fun spacingAndHyphenVariantsOfOneWordMatchEachOther() {
        val offers = listOf(offer("1", "Monster Energy Drink", 99), offer("2", "Rockstar Energy-Drink", 88), offer("3", "Energydrink Classic", 77))
        assertEquals(listOf("3", "2", "1"), OfferMatcher.matches("energydrink", offers).map { it.offer.id })
        assertEquals(listOf("3", "2", "1"), OfferMatcher.matches("Energy Drink", offers).map { it.offer.id })
    }

    @Test
    fun shortCompactQueryDoesNotJoinAcrossWords() {
        assertEquals(0, OfferMatcher.matches("abc d", listOf(offer("1", "Ab Cd", 99))).size)
    }

    @Test
    fun brandIsSearchedButNotInTitle() {
        val withBrand = offer("1", "Ultra Zero", 99).copy(brand = "Monster Energy")
        assertEquals(1, OfferMatcher.matches("monster", listOf(withBrand)).size)
        assertEquals(1, OfferMatcher.matches("energy", listOf(withBrand)).size)
        assertEquals(0, OfferMatcher.matches("monster", listOf(offer("2", "Ultra Zero", 99))).size)
    }

    @Test
    fun dateRule() {
        val t = "2026-10-30"
        assertEquals(true, OfferMatcher.isShown("2026-10-24", "2026-10-30", t, false))
        assertEquals(false, OfferMatcher.isShown("2026-10-24", "2026-10-29", t, false))
        assertEquals(true, OfferMatcher.isShown("2026-10-30", "2026-11-05", t, false))
        assertEquals(false, OfferMatcher.isShown("2026-10-31", "2026-11-05", t, false))
        assertEquals(true, OfferMatcher.isShown("2026-10-31", "2026-11-05", t, true))
        assertEquals(false, OfferMatcher.isShown("2026-10-30", "2026-11-05", t, true))
        assertEquals(true, OfferMatcher.isShown(null, "", t, false))
        assertEquals(true, OfferMatcher.isShown("2026-10-01T00:00:00Z", "2026-10-30T21:59:59Z", t, false))
    }

    @Test
    fun dateRuleUsesBerlinDaysForUtcInstants() {
        val today = "2026-10-25"
        // 2026-10-24T22:00Z is Berlin midnight 25.10.: starts today, and as an end date it is still valid today.
        assertEquals(true, OfferMatcher.isShown("2026-10-24T22:00:00Z", null, today, false))
        assertEquals(true, OfferMatcher.isShown(null, "2026-10-25T21:59:00Z", today, false))
        assertEquals(false, OfferMatcher.isShown(null, "2026-10-24T21:59:00Z", today, false))
        // DST ends on 25.10.2026: Berlin midnight of 26.10. is 23:00 UTC.
        assertEquals(false, OfferMatcher.isShown("2026-10-25T23:00:00Z", null, today, false))
        assertEquals(true, OfferMatcher.isShown("2026-10-25T22:00:00Z", null, today, false))
    }

    @Test
    fun unparseableDatesAreNotShown() {
        assertEquals(false, OfferMatcher.isShown("abc", null, "2026-10-25", false))
        assertEquals(false, OfferMatcher.isShown(null, "abc", "2026-10-25", false))
    }

    @Test
    fun blankQueryMatchesNothing() {
        assertEquals(0, OfferMatcher.matches("  ", listOf(offer("1", "Butter", 149))).size)
    }

    @Test
    fun formatsPrice() {
        assertEquals("3,05 €", OfferMatcher.formatPrice(305))
    }
}
