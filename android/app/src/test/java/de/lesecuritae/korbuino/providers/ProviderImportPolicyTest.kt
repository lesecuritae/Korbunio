package de.lesecuritae.korbuino.providers

import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ProviderImportPolicyTest {
    @Test fun `accepts verified Kaufland week-start assortment above 600 offers`() {
        // Leipzig-Reudnitz (DE7923), 2026-10-06: 618 dated, locally available
        // offers, including 57 week-start offers. The old 600 cap rejected all.
        assertNull(ProviderImportPolicy.rejectionReason("kaufland", 618, 0))
        assertNull(ProviderImportPolicy.rejectionReason("kaufland", 618, 500))
        // Reported location: Konstanz 78467, DE1680. Includes Kohlrabi and
        // FAIRY in the week-start group; rejecting the batch hides both.
        assertNull(ProviderImportPolicy.rejectionReason("kaufland", 629, 0))
        assertNull(ProviderImportPolicy.rejectionReason("kaufland", 629, 500))
    }

    @Test fun `Kaufland still rejects oversized or unexplained imports`() {
        assertNull(ProviderImportPolicy.rejectionReason("kaufland", 800, 0))
        assertTrue(ProviderImportPolicy.rejectionReason("kaufland", 801, 0)!!.contains("Plausibilitätsgrenze"))
        assertTrue(ProviderImportPolicy.rejectionReason("kaufland", 618, 100)!!.contains("letzten gültigen Stand"))
    }

    @Test fun `accepts a plausible current Lidl prospect`() {
        assertNull(ProviderImportPolicy.rejectionReason("marktguru-lidl", 398, 0))
    }

    @Test fun `rejects a complete Lidl shop-sized import`() {
        assertTrue(ProviderImportPolicy.rejectionReason("marktguru-lidl", 814, 0)!!.contains("Plausibilitätsgrenze"))
    }

    @Test fun `rejects an unexplained surge and preserves server aggregation`() {
        assertTrue(ProviderImportPolicy.rejectionReason("marktguru-lidl", 400, 100)!!.contains("letzten gültigen Stand"))
        assertNull(ProviderImportPolicy.rejectionReason("server", 1800, 500))
        assertNull(ProviderImportPolicy.rejectionReason("korbuino-server", 10000, 500))
    }
}
