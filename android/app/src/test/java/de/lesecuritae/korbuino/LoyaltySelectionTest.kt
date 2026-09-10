package de.lesecuritae.korbuino

import de.lesecuritae.korbuino.data.OfferEntity
import org.junit.Assert.assertEquals
import org.junit.Test

class LoyaltySelectionTest {
    private val offer = OfferEntity(
        id = "offer",
        retailerId = "netto-marken",
        productId = "product",
        externalId = "external",
        priceCents = 99,
        sourceUrl = "https://example.invalid/offer",
        loyaltyProgram = "netto_plus",
        loyaltyLabel = "Netto Plus App",
        loyaltyPriceCents = 79,
        cachedAt = 1L,
    )

    @Test fun `unselected program keeps public offer price`() {
        assertEquals(99, effectivePriceCents(offer, emptySet()))
    }

    @Test fun `selected program applies lower explicit member price`() {
        assertEquals(79, effectivePriceCents(offer, setOf("netto_plus")))
    }

    @Test fun `member price can never make the offer more expensive`() {
        assertEquals(
            99,
            effectivePriceCents(offer.copy(loyaltyPriceCents = 129), setOf("netto_plus")),
        )
    }
}
