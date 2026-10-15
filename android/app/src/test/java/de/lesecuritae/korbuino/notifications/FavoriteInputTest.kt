package de.lesecuritae.korbuino.notifications

import de.lesecuritae.korbuino.favoritePriceCents
import de.lesecuritae.korbuino.favoritePriceError
import org.junit.Assert.*
import org.junit.Test

class FavoriteInputTest {
    @Test fun optionalMaxPriceUsesExactCents() {
        assertNull(favoritePriceCents(""))
        assertNull(favoritePriceError(""))
        assertEquals(149,favoritePriceCents("1,49"))
        assertEquals(110,favoritePriceCents("1.1"))
        assertEquals(300,favoritePriceCents("3"))
        listOf("0","-1","1,999","1e3","NaN","9999999999999999999","1,2.3").forEach {
            assertNotNull("Expected error for $it",favoritePriceError(it))
        }
    }
    @Test fun settingsValidationAllowsEmptyDisabledAndRejectsNonHttpsBeforeSaving() {
        assertNull(NtfySender.validationError(NtfySettings()))
        assertNotNull(NtfySender.validationError(NtfySettings(true)))
        assertNotNull(NtfySender.validationError(NtfySettings(false,"http://example.org/topic")))
        assertNull(NtfySender.validationError(NtfySettings(true,"https://example.org/topic","token")))
        assertNotNull(NtfySender.validationError(NtfySettings(true,"https://example.org/topic","bad\ntoken")))
    }
}
