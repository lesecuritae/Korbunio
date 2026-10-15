package de.lesecuritae.korbuino

import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ShoppingListRow
import java.time.LocalDate
import org.junit.Assert.*
import org.junit.Test

class ShoppingPositionsTest {
    private val today = LocalDate.of(2026, 10, 15)
    private val offer = OfferEntity("milk", "rewe", "milk", externalId = "milk", priceCents = 99,
        depositCents = 25, sourceUrl = "https://example.org", cachedAt = 0,
        loyaltyCashbackCents = 10, loyaltyProgram = "app")
    private fun display(value: OfferEntity = offer) = OfferDisplay(value, "Milch")
    private fun row(id: String = "one", retailer: String = "rewe", offerId: String? = "milk", quantity: Int = 2) =
        ShoppingListRow("milk", "Milch", quantity, false, "keep note", id, retailer, offerId)

    @Test fun keepsDistinctRetailerPositionsAndPackQuantities() {
        val aldi = offer.copy(id = "aldi", retailerId = "aldi", priceCents = 95)
        val plan = ShoppingPlan.buildRows(listOf(row(), row("two", "aldi", "aldi", 3)), listOf(display(), display(aldi)), setOf("app"), today)
        assertEquals(listOf("one", "two"), plan.positions.map { it.itemId })
        assertEquals(483, plan.actualTotalCents)
        assertEquals(50, plan.positions.first().depositCents)
        assertEquals(20, plan.positions.first().cashbackCents)
        assertNull(plan.positions.first().basePriceCents)
        assertEquals(setOf("rewe", "aldi"), plan.actualStores.toSet())
    }

    @Test fun expiredFutureOrDisappearedSelectionHasNoInventedTotal() {
        for (value in listOf(offer.copy(validUntil = "2026-10-14"), offer.copy(validFrom = "2026-10-16"))) {
            val plan = ShoppingPlan.buildRows(listOf(row()), listOf(display(value)), emptySet(), today)
            assertNull(plan.actualTotalCents)
            assertNull(plan.positions.single().chosenOffer)
        }
        val replacement = display(offer.copy(id = "replacement"))
        val plan = ShoppingPlan.buildRows(listOf(row()), listOf(replacement), emptySet(), today)
        assertNull(plan.actualTotalCents)
        assertEquals(replacement, plan.positions.single().suggestedOffer)
    }

    @Test fun consolidationPricesTheSameQuantitiesAndPositions() {
        val aldi = offer.copy(id = "aldi", retailerId = "aldi", priceCents = 95)
        val plan = ShoppingPlan.buildRows(listOf(row("one"), row("two", quantity = 3)), listOf(display(), display(aldi)), emptySet(), today)
        assertEquals(475, plan.cheapestTotalCents)
        assertEquals(2, plan.matchedCount)
    }

    @Test fun manualWishHasSuggestionsWithoutClaimingAnActualPurchase() {
        val plan = ShoppingPlan.buildRows(listOf(ShoppingListRow("wish", "Milch", 2, false)), listOf(display()), emptySet(), today)
        assertNull(plan.actualTotalCents)
        assertNull(plan.positions.single().chosenOffer)
        assertNotNull(plan.positions.single().suggestedOffer)
        assertTrue(plan.actualStores.isEmpty())
        assertEquals(198, plan.suggestedTotalCents)
    }

    @Test fun incompleteBundleIsUnknownAndSeparatePositionsDoNotPoolQuantities() {
        val bundle = offer.copy(multiBuyQuantity = 3, multiBuyTotalCents = 300, priceCents = 300)
        val plan = ShoppingPlan.buildRows(listOf(row(quantity = 1), row("two", quantity = 2)), listOf(display(bundle)), emptySet(), today)
        assertNull(plan.actualTotalCents)
        assertEquals(listOf(1, 2), plan.positions.map { it.quote?.unpricedQuantity })
    }
}
