package de.lesecuritae.korbuino.providers

import okhttp3.OkHttpClient
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ProviderRegistryTest {
    @Test fun `default registry restores Aldi Nord and excludes Combi`() {
        val ids = ProviderRegistry.default(OkHttpClient()).all().map { it.id }.toSet()
        assertTrue("ALDI Nord must remain selectable", "aldi-nord" in ids)
        assertFalse("Combi is not a Korbunio retailer", "marktguru-combi" in ids)
    }
}
