package de.lesecuritae.korbuino

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

/** Exercise the platform ICU implementation, rather than only the desktop JVM. */
@RunWith(AndroidJUnit4::class)
class ProductGroupsAndroidTest {
    @Test fun unicodeNormalizationAndProductBoundaries() {
        assertEquals("äpfel öl süß", ProductGroups.normalizeForMatching("  ÄPFEL\u00a0&\tÖL -- Süß! "))
        assertEquals("cola 123", ProductGroups.normalizeForMatching("ＣＯＬＡ １２３"))
        assertEquals("𐐨\u0f33", ProductGroups.normalizeForMatching("𐐀\u0f33"))
        assertEquals("Getränke", ProductGroups.of(null, "ＣＯＬＡ 🥤 light"))
        assertEquals(ProductGroups.OTHER, ProductGroups.of(null, "𐐀cola"))
        ProductGroups.ORDER.forEach { group ->
            assertEquals(group, ProductGroups.of("  $group\t", null))
        }
    }

    @Test fun repeatedOfferBatchesOnMainThread() {
        val offers = listOf(
            Triple("Prospektseite 23", "Etwas Unbestimmtes", ProductGroups.OTHER),
            Triple("Getränke", "Cola Zero 1,25 l", "Getränke"),
            Triple("Backwaren", "Kerrygold Butter", "Molkereiprodukte & Eier"),
            Triple("Tiefkühlkost", "Pizza", "Tiefkühl / Eis & Dessert"),
            Triple("Obst & Gemüse", "Bio Äpfel", "Obst & Gemüse"),
            Triple("Haushalt", "WC Reiniger", "Haushalt & Reinigung"),
            Triple("Garten", "Blumenerde", "Wohnen, Freizeit & Non-Food"),
            Triple("Bier", "Pils Kasten", "Getränke"),
        )
        val failure = AtomicReference<Throwable?>()
        // Yield between batches like successive offer updates, including the
        // unknown-category path that used to compile the separator many times.
        repeat(20) {
            if (failure.get() != null) return@repeat
            InstrumentationRegistry.getInstrumentation().runOnMainSync {
                try {
                    repeat(125) {
                        offers.forEach { (category, product, expected) ->
                            assertEquals(expected, ProductGroups.of(category, product))
                        }
                    }
                } catch (error: Throwable) {
                    failure.compareAndSet(null, error)
                }
            }
        }
        failure.get()?.let { throw it }
    }
}
