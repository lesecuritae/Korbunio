package de.lesecuritae.korbuino.update

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateServiceTest {
    @Test fun `only newer release is offered`() {
        assertTrue(UpdateService.isNewerVersion("0.1.21", "0.1.20"))
        assertTrue(UpdateService.isNewerVersion("v1.0.0", "0.9.9"))
        assertFalse(UpdateService.isNewerVersion("0.1.20", "0.1.20"))
        assertFalse(UpdateService.isNewerVersion("0.1.2", "0.1.10"))
    }
}
