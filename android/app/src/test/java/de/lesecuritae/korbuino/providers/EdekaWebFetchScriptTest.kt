package de.lesecuritae.korbuino.providers

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EdekaWebFetchScriptTest {
    @Test fun `asks EDEKA's own services for the postal code and calls the bridge`() {
        val script = EdekaWebFetchScript.build("26188")
        assertTrue(script.contains("/api/marketsearch/markets?size=100&searchstring="))
        assertTrue(script.contains("/eh/service/eh/offers?marketId="))
        assertTrue(script.contains("KorbuinoEdeka.deliver(JSON.stringify(out))"))
        assertTrue(script.contains("})('26188');"))
        assertTrue(script.contains(".slice(0, ${EdekaWebFetchScript.MAX_MARKETS})"))
    }

    @Test fun `uses the same market limit as the provider`() {
        assertTrue(EdekaWebFetchScript.MAX_MARKETS == EdekaProvider.MAX_MARKET_CANDIDATES)
    }

    @Test fun `never lets anything but five digits into the script`() {
        listOf("", "1234", "123456", "26188'); alert(1); ('", "2618a").forEach { bad ->
            assertFalse("$bad must be rejected", runCatching { EdekaWebFetchScript.build(bad) }.isSuccess)
        }
    }
}
