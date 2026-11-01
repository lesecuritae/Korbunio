package de.lesecuritae.korbuino.images

import de.lesecuritae.korbuino.images.ImageSubstituteIndex.Donor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ImageSubstituteIndexTest {
    private fun donor(retailer: String, name: String, url: String = "https://img.example/$retailer.jpg", brand: String = "") =
        Donor(retailer, retailer.uppercase(), name, brand, url, "https://$retailer.example/")

    @Test fun sameArticleOtherRetailerExactPackFirst() {
        val index = ImageSubstituteIndex(listOf(
            donor("rewe", "Red Bull Energy Drink 4 x 250 ml"),
            donor("mueller", "Red Bull Energy Drink 250 ml"),
            donor("lidl", "Red Bull Energy Drink 250 ml"),
        ))
        val found = index.candidates("kaufland", "RED BULL Energy Drink 250 ml", "")
        assertEquals(listOf("https://img.example/lidl.jpg", "https://img.example/mueller.jpg", "https://img.example/rewe.jpg"), found.map { it.url })
        assertTrue(found[0].note.startsWith("Bild von LIDL")); assertTrue(found[2].note.startsWith("Ersatzbild von REWE"))
        assertEquals("https://lidl.example/", found[0].referer)
    }

    @Test fun neverTheSameRetailerAndNeverAnotherVariantOrBrand() {
        val index = ImageSubstituteIndex(listOf(
            donor("rewe", "Monster Energy Ultra Zero 500 ml"),
            donor("lidl", "Rockstar Energy Drink 500 ml"),
            donor("penny", "Monster Energy Drink 500 ml"),
        ))
        assertEquals(emptyList<ImageFallback>(), index.candidates("netto", "Monster Energy Zero Sugar 500 ml", ""))
        assertEquals(listOf("https://img.example/penny.jpg"), index.candidates("netto", "Monster Energy Drink 500 ml", "").map { it.url })
        assertEquals(emptyList<ImageFallback>(), index.candidates("penny", "Monster Energy Drink 500 ml", ""))
    }

    @Test fun donorsWithoutPictureAreIgnoredAndLimitIsRespected() {
        val index = ImageSubstituteIndex(listOf(donor("rewe", "Cola 1 l", url = ""), donor("a", "Cola 1 l"), donor("b", "Cola 1 l"), donor("c", "Cola 1 l"), donor("d", "Cola 1 l")))
        assertEquals(3, index.candidates("x", "Cola 1 l", "").size)
        assertTrue(index.candidates("x", "Cola 1 l", "").none { it.url.isBlank() })
    }
}
