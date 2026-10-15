package de.lesecuritae.korbuino

import de.lesecuritae.korbuino.data.OfferEntity
import org.junit.Assert.*
import org.junit.Test

class OfferPricingTest {
    private val bundle = OfferEntity("em", "kaufland", "em", externalId = "em", priceCents = 300,
        sourceUrl = "https://example.org", cachedAt = 0, multiBuyQuantity = 3, multiBuyTotalCents = 300,
        packSize = "75 g", multiBuyCondition = "3 für 3 €")

    @Test fun bundleNeedsCompleteQuantitiesUnlessSinglePriceIsVerified() {
        for (q in listOf(1, 2, 4)) {
            val quote = OfferPricing.quote(bundle, q)
            assertNull(quote.totalCents)
            assertEquals(q % 3, quote.unpricedQuantity)
            assertEquals(q / 3 * 300, quote.knownTotalCents)
        }
        assertEquals(300, OfferPricing.quote(bundle, 3).totalCents)
        assertEquals(600, OfferPricing.quote(bundle, 6).totalCents)
        assertEquals(450, OfferPricing.quote(bundle.copy(singlePriceCents = 150), 4).totalCents)
        assertNull(OfferPricing.quote(bundle, 1).unitPriceCents)
    }

    @Test fun regularPricesMultiplyPacksAndOnlySelectedDirectBenefitsReducePrice() {
        val normal = bundle.copy(multiBuyQuantity = null, multiBuyTotalCents = null, priceCents = 150,
            loyaltyBenefitsJson = """[{"program_id":"app","kind":"direct_price","value":1.2},{"program_id":"app","kind":"cashback","value":0.5}]""")
        assertEquals(300, OfferPricing.quote(normal, 2).totalCents)
        assertEquals(240, OfferPricing.quote(normal, 2, setOf("app")).totalCents)
    }

    @Test fun conditionalBundlesRequireKnownSelectedMembershipAndNeverAssumeCouponActivation() {
        val card = bundle.copy(multiBuyCondition = "3 für 3 € mit Kaufland Card", loyaltyProgram = "kaufland_xtra")
        assertNull(OfferPricing.quote(card, 3).totalCents)
        assertNull(OfferPricing.quote(card.copy(loyaltyProgram = null), 3, setOf("kaufland_xtra")).totalCents)
        assertEquals(300, OfferPricing.quote(card, 3, setOf("kaufland_xtra")).totalCents)
        val coupon = card.copy(multiBuyCondition = "3 für 3 € mit aktiviertem App-Coupon")
        assertNull(OfferPricing.quote(coupon, 3, setOf("kaufland_xtra")).totalCents)
    }

    @Test fun matchingRecognizesTheCompoundWithoutMatchingOtherBrands() {
        val em = OfferDisplay(bundle, "Dr. C. Soldan Em-eukal")
        val competitor = OfferDisplay(bundle.copy(id = "ricola"), "Ricola Kräuterbonbons")
        for (name in listOf("Em-eukal", "Em Eukal", "Emeukal")) {
            assertEquals(listOf(em), OfferMatcher.matches(name, listOf(em, competitor)))
        }
    }
}
