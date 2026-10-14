package de.lesecuritae.korbuino

import de.lesecuritae.korbuino.data.OfferEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ShoppingPlanTest {
    private fun offer(id: String, retailer: String, name: String, cents: Int) = OfferDisplay(
        offer = OfferEntity(
            id = id, retailerId = retailer, productId = id, externalId = id,
            priceCents = cents, sourceUrl = "https://example.org", cachedAt = 0L,
        ),
        productName = name,
    )

    private val milchUndButter = listOf(
        offer("1", "rewe", "Frische Milch 1l", 99),
        offer("2", "aldi", "Frische Milch 1l", 95),
        offer("3", "rewe", "Deutsche Markenbutter", 149),
        offer("4", "aldi", "Deutsche Markenbutter", 199),
    )

    @Test
    fun suggestsSkippingAShopWhenTheGapIsTiny() {
        val plan = ShoppingPlan.build(listOf("Milch", "Butter"), milchUndButter, emptySet())
        // Cheapest everywhere needs both shops (Milch at Aldi, Butter at REWE).
        assertEquals(2, plan.cheapestStores.size)
        assertEquals(99 + 95, 194)
        assertEquals(95 + 149, plan.cheapestTotalCents)
        assertEquals("rewe", plan.primaryStoreId)
        // Milch is only 4 ct dearer at REWE, so the Aldi trip can be skipped.
        assertEquals(listOf("Milch"), plan.consolidations.map { it.itemName })
        assertEquals(4, plan.consolidations.single().extraCents)
        assertEquals(1, plan.consolidatedStores.size)
        assertEquals(1, plan.savedTrips)
        assertEquals(4, plan.consolidationExtraCents)
    }

    @Test
    fun keepsTheSeparateShopWhenTheSavingIsWorthIt() {
        val offers = listOf(
            offer("1", "rewe", "Frische Milch 1l", 99),
            offer("2", "aldi", "Frische Milch 1l", 40),
            offer("3", "rewe", "Deutsche Markenbutter", 149),
            offer("4", "aldi", "Deutsche Markenbutter", 199),
        )
        val plan = ShoppingPlan.build(listOf("Milch", "Butter"), offers, emptySet())
        // Milch is 59 ct cheaper at Aldi: above the threshold, so no consolidation.
        assertTrue(plan.consolidations.isEmpty())
        assertEquals(0, plan.savedTrips)
        assertEquals(2, plan.cheapestStores.size)
    }

    @Test
    fun oneShopWhenEverythingIsCheapestThere() {
        val offers = listOf(
            offer("1", "aldi", "Frische Milch 1l", 95),
            offer("2", "aldi", "Deutsche Markenbutter", 149),
        )
        val plan = ShoppingPlan.build(listOf("Milch", "Butter"), offers, emptySet())
        assertEquals(listOf("aldi"), plan.cheapestStores)
        assertEquals(0, plan.savedTrips)
        assertTrue(plan.consolidations.isEmpty())
    }

    @Test
    fun listsItemsThatAreNotOnOffer() {
        val plan = ShoppingPlan.build(listOf("Milch", "Pizza"), milchUndButter, emptySet())
        assertEquals(listOf("Pizza"), plan.unmatchedItems)
        assertEquals(1, plan.matchedCount)
    }

    @Test
    fun emptyWhenNothingMatches() {
        val plan = ShoppingPlan.build(listOf("Pizza"), milchUndButter, emptySet())
        assertTrue(!plan.hasPlan)
        assertEquals(listOf("Pizza"), plan.unmatchedItems)
    }

    @Test
    fun countsEachShopOnceForDuplicateEntries() {
        val plan = ShoppingPlan.build(listOf("Milch", "milch", " Milch "), milchUndButter, emptySet())
        assertEquals(1, plan.matchedCount)
    }
}
