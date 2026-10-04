package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class AktivIrmaProviderTest {
    private lateinit var server: MockWebServer

    @Before fun setUp() { server = MockWebServer().also { it.start() } }
    @After fun tearDown() { server.shutdown() }

    // A faithful slice of https://www.aktiv-irma.de/angebote/: category tabs
    // (li.js-tabs-content) each carrying their own "… gültig vom … bis zum …"
    // label, with product cards whose price box sits inside the description
    // container (the real page bleeds the prices into that text).
    private val html = """
        <ul class="uk-list js-tabs-switcher">
          <li class="js-tabs-content fr-active">
            <h3>Tiefk&uuml;hlkost: Aktiv &amp; Irma g&uuml;ltig vom 05.10.2026 bis zum 10.10.2026</h3>
            <div class="uk-grid">
              <div class="fr-product">
                <div class="uk-card uk-card-primary fr-product-card">
                  <div class="fr-product-card-media">
                    <img src="/media/bild_produkt/frosta.psd" data-srcset="/media/bild_produkt/frosta.psd">
                  </div>
                  <div class="fr-product-card-body">
                    <h3 class="uk-card-title">Frosta Kleine Mahlzeit Fertiggerichte</h3>
                    <div class="product-description-container">
                      <p>versch. Sorten</p>
                      <p class="uk-text-small">500g (1kg=3,98)</p>
                      <div class="fr-price-box">
                        <span class="fr-price-statt">statt 2,99</span>
                        <span class="fr-price-angebot">1,99</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </li>
          <li class="js-tabs-content">
            <h3>Fleisch: Kramerhof g&uuml;ltig vom 05.10.2026 bis zum 07.10.2026</h3>
            <div class="uk-grid">
              <div class="fr-product">
                <div class="uk-card uk-card-primary fr-product-card">
                  <div class="fr-product-card-body">
                    <h3 class="uk-card-title">Schweinenacken</h3>
                    <div class="product-description-container">
                      <p>frisch aus der Region</p>
                      <p class="uk-text-small">(1kg=6,99)</p>
                      <div class="fr-price-box">
                        <span class="fr-price-statt">statt 8,99</span>
                        <span class="fr-price-angebot">6,99</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </li>
        </ul>
    """.trimIndent()

    @Test fun `parses weekly flyer offers with price validity and base price`() = runTest {
        server.enqueue(MockResponse().setBody(html).addHeader("Content-Type", "text/html; charset=utf-8"))
        val provider = AktivIrmaProvider(OkHttpClient(), server.url("/angebote/").toString())

        val result = provider.fetch(RetailerRequest(postalCode = "26121"))

        assertEquals(2, result.offers.size)
        val frosta = result.offers.first { it.productId.contains("frosta") }
        assertEquals("aktiv-irma", frosta.retailerId)
        assertEquals(199, frosta.priceCents)
        assertEquals(398, frosta.basePriceCents)
        assertEquals("kg", frosta.baseUnit)
        assertEquals("2026-10-05", frosta.validFrom)
        assertEquals("2026-10-10", frosta.validUntil)
        assertTrue(frosta.sourceUrl.contains("/angebote/"))

        // The partner-supplied Kramerhof tab keeps its own (shorter) validity.
        val schwein = result.offers.first { it.productId.contains("schweinenacken") }
        assertEquals(699, schwein.priceCents)
        assertEquals("2026-10-07", schwein.validUntil)
    }
}
