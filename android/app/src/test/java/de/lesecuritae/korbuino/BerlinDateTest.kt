package de.lesecuritae.korbuino

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class BerlinDateTest {
    @Test fun utcInstantAtBerlinMidnightMapsToNextBerlinDay() {
        assertEquals("2026-10-25", BerlinDate.toLocalDate("2026-10-24T22:00:00Z"))
        assertEquals("2026-09-07", BerlinDate.toLocalDate("2026-09-06T22:00:00.000+0000"))
        assertEquals("2026-10-25", BerlinDate.toLocalDate("2026-10-25T00:00:00+02:00"))
    }

    @Test fun winterTimeBoundaryIs23Z() {
        assertEquals("2026-11-02", BerlinDate.toLocalDate("2026-11-01T23:00:00Z"))
    }

    @Test fun eveningStaysOnSameDay() {
        assertEquals("2026-09-12", BerlinDate.toLocalDate("2026-09-12T20:00:00Z"))
    }

    @Test fun plainDatesPassThrough() {
        assertEquals("2026-10-24", BerlinDate.toLocalDate("2026-10-24"))
    }

    @Test fun blankAndGarbageGiveNull() {
        assertNull(BerlinDate.toLocalDate(null))
        assertNull(BerlinDate.toLocalDate("  "))
        assertNull(BerlinDate.toLocalDate("abc"))
        assertNull(BerlinDate.toLocalDate("2026-13-45"))
    }
}
