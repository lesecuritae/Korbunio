package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CombinedPagesProviderTest {
    private val sample = checkNotNull(javaClass.classLoader!!.getResource("mueller-aktionen-sample.html")).readText()

    private fun page(department: String, html: String?) = HtmlFlyerProvider(
        "mueller", "Müller", "https://www.mueller.de/c/$department/aktionen/", OkHttpClient(),
        renderedHtmlProvider = { html },
    )

    @Test fun `real Müller Aktionen markup yields the listed products with prices`() = runTest {
        val offers = page("drogerie", sample).fetch(RetailerRequest("78467")).offers
        assertEquals(listOf(225, 235, 699), offers.map { it.priceCents }.sorted().let { listOf(it[0], it[1], it[2]) })
        assertTrue(offers.all { it.sourceUrl.contains("/c/drogerie/aktionen/") })
    }

    @Test fun `combines departments and drops duplicates`() = runTest {
        val combined = CombinedPagesProvider("mueller", "Müller", listOf(page("drogerie", sample), page("haushalt", sample)))
        assertEquals(3, combined.fetch(RetailerRequest("78467")).offers.size)
        assertEquals("https://www.mueller.de/c/drogerie/aktionen/", combined.challengeUrl)
    }

    @Test fun `one failing department does not hide the others`() = runTest {
        val broken = HtmlFlyerProvider("mueller", "Müller", "https://www.mueller.de/c/haushalt/aktionen/", OkHttpClient(), renderedHtmlProvider = { "<html><body>Navigation</body></html>" })
        val combined = CombinedPagesProvider("mueller", "Müller", listOf(page("drogerie", sample), broken))
        assertEquals(3, combined.fetch(RetailerRequest("78467")).offers.size)
    }

    @Test fun `all departments failing is reported`() = runTest {
        val empty = { d: String -> HtmlFlyerProvider("mueller", "Müller", "https://www.mueller.de/c/$d/aktionen/", OkHttpClient(), renderedHtmlProvider = { "<html><body>Navigation</body></html>" }) }
        val combined = CombinedPagesProvider("mueller", "Müller", listOf(empty("drogerie"), empty("haushalt")))
        try { combined.fetch(RetailerRequest("78467")); error("expected failure") } catch (e: IllegalStateException) { assertTrue(e.message.orEmpty().contains("dynamischen Angebote")) }
    }

    @Test fun `registry no longer uses the redirected online-angebote page`() {
        assertTrue(MuellerPages.DEPARTMENTS.size >= 4)
    }
}
