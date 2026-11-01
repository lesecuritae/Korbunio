package de.lesecuritae.korbuino.images

import de.lesecuritae.korbuino.images.ImageMatch.Match
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ImageMatchTest {
    private fun m(a: String, b: String, ba: String = "", bb: String = "") = ImageMatch.matchArticle(a, b, ba, bb)

    @Test fun sameArticleOtherWordingOrPack() {
        assertEquals(Match.EXACT, m("Monster Energy Drink 500 ml", "Monster Energy Energy Drink 500 ml"))
        assertEquals(Match.SUBSTITUTE, m("RED BULL Energy Drink oder Erfrischungsgetränk 250–330 ml", "RED BULL Energy Drink 250 ml"))
        assertEquals(Match.SUBSTITUTE, m("Booster Energy Drink 330 ml", "Booster Energy Drink 2 × 330 ml"))
        assertEquals(Match.SUBSTITUTE, m("Coca-Cola 4 x 0,25 l", "Coca Cola 0,5 l"))
        assertEquals(Match.EXACT, m("Hell Energy 250 ml", "HELL ENERGY Dose 250 ml"))
        assertEquals(Match.EXACT, m("Rockstar Energy-Drink 500 ml", "Rockstar Energy Drink 0,5 l"))
        assertEquals(Match.EXACT, m("Müller Milch 1 l", "Mueller Milch 1 L"))
        assertEquals(Match.EXACT, m("Rauch Eistee Pfirsich 4×250 ml", "Rauch Eistee Pfirsich 4x250ml"))
    }

    @Test fun unknownPackIsNeverExact() {
        assertEquals(Match.SUBSTITUTE, m("Pfanner Eistee 2 l", "Pfanner Eistee"))
        assertEquals(Match.SUBSTITUTE, m("Hell Energy", "HELL Energy Dose"))
    }

    @Test fun differentVariantBrandOrFlavourIsNotASubstitute() {
        assertNull(m("Monster Energy Drink 500 ml", "Monster Energy Ultra Zero 500 ml"))
        assertNull(m("Coca-Cola 1 l", "Coca-Cola Zero 1 l"))
        assertNull(m("Coca-Cola 1 l", "Coca-Cola ohne Zucker 1 l"))
        assertNull(m("Red Bull Energy Drink 250 ml", "Red Bull Energy Drink Sugarfree 250 ml"))
        assertNull(m("Monster Energy Drink 500 ml", "Rockstar Energy Drink 500 ml"))
        assertNull(m("Booster Energy Drink 330 ml", "Booster Energy Mango 330 ml"))
        assertNull(m("Lorenz Monster Munch Original 75 g", "Monster Energy Drink 500 ml"))
        assertNull(m("Energy Drink 250 ml", "Hell Energy 250 ml"))
        assertNull(m("", "Monster Energy Drink"))
    }

    @Test fun reviewedFalsePositivesStayRejected() {
        assertNull(m("Becks 0,5 l", "Becks 0,0 0,5 l"))
        assertNull(m("Coca-Cola 1 l", "Coca-Cola 0,0 1 l"))
        assertNull(m("Vitamin C Brause 20 St", "Vitamin D Brause 20 St"))
        assertNull(m("7 Up 1 l", "Up 1 l"))
        assertNull(m("Hohes C 1 l", "Hohes 1 l"))
    }

    @Test fun brandIsPartOfTheIdentity() {
        assertEquals(Match.EXACT, m("Ultra Zero 0,5 l", "Monster Ultra Zero 0,5 l", ba = "Monster"))
        assertNull(m("Ultra Zero 0,5 l", "Ultra Zero 0,5 l", ba = "Monster", bb = "Rockstar"))
    }

    @Test fun packSignatureMatchesTheServer() {
        assertEquals("500", ImageMatch.packSignature("Cola 0,5 l"))
        assertEquals("500", ImageMatch.packSignature("Cola 500 ml"))
        assertEquals("4x250", ImageMatch.packSignature("Cola 4 x 0,25 l"))
        assertEquals("12x330", ImageMatch.packSignature("12 x 0,33 l"))
        assertEquals("", ImageMatch.packSignature("Cola"))
    }
}
