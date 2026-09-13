package de.lesecuritae.korbuino.providers

import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ProviderImportPolicyTest {
    @Test fun `accepts a plausible current Lidl prospect`() {
        assertNull(ProviderImportPolicy.rejectionReason("marktguru-lidl", 398, 0))
    }

    @Test fun `rejects a complete Lidl shop-sized import`() {
        assertTrue(ProviderImportPolicy.rejectionReason("marktguru-lidl", 814, 0)!!.contains("Plausibilitätsgrenze"))
    }

    @Test fun `rejects an unexplained surge and preserves server aggregation`() {
        assertTrue(ProviderImportPolicy.rejectionReason("marktguru-lidl", 400, 100)!!.contains("letzten gültigen Stand"))
        assertNull(ProviderImportPolicy.rejectionReason("server", 1800, 500))
    }
}
