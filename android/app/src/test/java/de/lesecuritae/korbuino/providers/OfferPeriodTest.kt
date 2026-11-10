package de.lesecuritae.korbuino.providers

import java.time.LocalDate
import org.junit.Assert.*
import org.junit.Test

class OfferPeriodTest {
    @Test fun `current Thursday expiry and Sunday to Monday agree with backend`() {
        val from = LocalDate.parse("2026-11-12")
        val until = LocalDate.parse("2026-11-14")
        assertTrue(offerWeekContains(from, until, OfferWeek.CURRENT, LocalDate.parse("2026-11-09")))
        assertFalse(offerWeekContains(from, until, OfferWeek.NEXT, LocalDate.parse("2026-11-09")))
        assertFalse(offerWeekContains(from, until, OfferWeek.CURRENT, LocalDate.parse("2026-11-15")))
        assertTrue(offerWeekContains(LocalDate.parse("2026-11-16"), LocalDate.parse("2026-11-21"), OfferWeek.CURRENT, LocalDate.parse("2026-11-15")))
        assertFalse(offerWeekContains(until, from, OfferWeek.CURRENT, LocalDate.parse("2026-11-09")))
    }

    @Test fun `decimal prices never lose a cent through floating point truncation`() {
        assertEquals(115, ProviderParsing.cents(1.15))
        assertEquals(113, ProviderParsing.cents(1.13))
        assertEquals(399, ProviderParsing.cents(3.99))
        assertTrue(runCatching { ProviderParsing.cents(Double.NaN) }.isFailure)
        assertTrue(runCatching { ProviderParsing.cents(Double.POSITIVE_INFINITY) }.isFailure)
    }
}
