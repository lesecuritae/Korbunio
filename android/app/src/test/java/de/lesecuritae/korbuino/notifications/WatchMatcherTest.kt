package de.lesecuritae.korbuino.notifications

import de.lesecuritae.korbuino.data.*
import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate

class WatchMatcherTest {
    private val day = LocalDate.parse("2026-12-31")
    private val watch = FavoriteEntity("stable-watch", 0, query = "Coca-Cola", maxPriceCents = 150)
    private val product = ProductEntity("p", "Coca Cola Zero 1l", normalizedKey = "coca-cola-zero")
    private val offer = OfferEntity("o", "rewe", "p", externalId = "o", priceCents = 149,
        validFrom = "2026-12-28", validUntil = "2027-01-03", sourceUrl = "https://example.org", cachedAt = 0)
    private fun matches(w: FavoriteEntity = watch, p: ProductEntity = product, o: OfferEntity = offer) = WatchMatcher.matches(w,p,o,"12345",day)

    @Test fun punctuationAndTokensAreSafe() {
        assertTrue(matches())
        assertFalse(matches(p = product.copy(name = "Pepsi Cola")))
        assertFalse(matches(p = product.copy(name = "Cocacola Wettbewerber")))
    }
    @Test fun filtersCashPriceRetailerPostalAndWeek() {
        assertFalse(matches(o = offer.copy(priceCents = 200, loyaltyCashbackCents = 100)))
        assertFalse(matches(w = watch.copy(preferredRetailerIdsJson = "[\"aldi-nord\"]")))
        assertFalse(matches(w = watch.copy(postalCode = "99999")))
        assertFalse(matches(w = watch.copy(includeCurrentWeek = false, includeNextWeek = false)))
        assertFalse(matches(o = offer.copy(validUntil = "2026-12-30")))
        assertFalse(matches(o = offer.copy(validFrom = null)))
        assertTrue(matches(w = watch.copy(includeCurrentWeek = false), o = offer.copy(validFrom = "2027-01-04", validUntil = "2027-01-10")))
    }
    @Test fun receiptSurvivesIdAndWeekLabelChurnButChangesForPriceOrValidity() {
        val key = WatchMatcher.receiptKey(watch,product,offer)
        assertEquals(key, WatchMatcher.receiptKey(watch.copy(includeNextWeek = false), product.copy(id = "new"), offer.copy(id = "new", externalId = "new")))
        assertNotEquals(key,WatchMatcher.receiptKey(watch,product,offer.copy(priceCents = 150)))
        assertNotEquals(key,WatchMatcher.receiptKey(watch,product,offer.copy(validUntil = "2027-01-04")))
    }
    @Test fun retainsMoreThanFiveMatches() {
        assertEquals(9, (1..9).map { offer.copy(retailerId = "retailer$it") }.count { matches(o=it) })
    }
    @Test fun emEukalAliasDoesNotMatchCompetitor() {
        val w = watch.copy(query="Em-eukal")
        assertTrue(matches(w=w,p=product.copy(name="Emeukal Hustenbonbons")))
        assertTrue(matches(w=w,p=product.copy(name="Em Eukal Hustenbonbons")))
        assertFalse(matches(w=w,p=product.copy(name="Ricola Hustenbonbons")))
    }
    @Test fun directMemberPriceRequiresSelectedProgramAndCashbackCannotQualify() {
        val member = offer.copy(priceCents=200,loyaltyProgram="member",loyaltyPriceCents=100,loyaltyCashbackCents=90)
        assertFalse(matches(o=member))
        assertTrue(WatchMatcher.matches(watch,product,member,"12345",day,setOf("member")))
        assertFalse(WatchMatcher.matches(watch,product,member.copy(loyaltyPriceCents=null),"12345",day,setOf("member")))
    }
    @Test fun bundleThresholdUsesRequiredCashPayment() {
        val bundle = offer.copy(multiBuyQuantity = 3, multiBuyTotalCents = 300, priceCents = 100)
        assertFalse(matches(o = bundle))
        assertTrue(matches(w = watch.copy(maxPriceCents = 300), o = bundle))
    }
}
