package de.lesecuritae.korbuino.providers

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

class RenderedPageStoreTest {
    @Before fun reset() = RenderedPageStore.clear()

    @Test fun `rendered document is scoped to url and consumed once`() {
        val url = "https://www.aldi-sued.de/angebote"
        assertEquals(true, RenderedPageStore.publish(url, "<html>offers</html>"))
        assertNull(RenderedPageStore.consume("https://www.mueller.de/c/online-angebote/"))
        assertEquals("<html>offers</html>", RenderedPageStore.consume(url))
        assertNull(RenderedPageStore.consume(url))
    }
}
