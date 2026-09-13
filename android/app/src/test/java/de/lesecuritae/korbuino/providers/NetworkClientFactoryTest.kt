package de.lesecuritae.korbuino.providers

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NetworkClientFactoryTest {
    @Test fun `uses platform TLS transport on oldest supported Android versions`() {
        assertFalse(NetworkClientFactory.supportsCronetTransport(26))
        assertFalse(NetworkClientFactory.supportsCronetTransport(28))
    }

    @Test fun `uses Chromium transport on modern Android versions`() {
        assertTrue(NetworkClientFactory.supportsCronetTransport(29))
        assertTrue(NetworkClientFactory.supportsCronetTransport(35))
    }
}
