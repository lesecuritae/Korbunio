package de.lesecuritae.korbuino

import android.content.Context
import android.graphics.Bitmap
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.core.app.ApplicationProvider
import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ShoppingListRow
import org.junit.After
import org.junit.Rule
import org.junit.Test
import java.io.File

/** Real local PNG decoding: no retailer/network availability is needed for these UI regressions. */
class ShoppingImagesUiTest {
    @get:Rule val compose = createComposeRule()
    private val images = mutableListOf<File>()

    private fun offer(id: String, name: String, retailer: String = "rewe"): OfferDisplay {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val file = File.createTempFile("shopping-image-", ".png", context.cacheDir).also { images += it }
        val bitmap = Bitmap.createBitmap(8, 8, Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(android.graphics.Color.GREEN)
        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        bitmap.recycle()
        return OfferDisplay(OfferEntity(id, retailer, "gouda", externalId = id, priceCents = 199,
            sourceUrl = "https://example.org", cachedAt = 0), name, imagePath = file.path)
    }

    @After fun cleanImages() { images.forEach { it.delete() } }

    @Test fun selectedPackAndExpandedAlternativesHaveTheirOwnImages() {
        val selected = offer("one", "Gouda Scheiben")
        val alternative = offer("two", "Gouda Stück", "penny")
        val row = ShoppingListRow("gouda", "Gouda", 1, false, itemId = "item", retailerId = "rewe", offerId = "one")
        compose.setContent { MaterialTheme {
            ShoppingListContent(MainUiState(shoppingItems = listOf(row), offers = listOf(selected, alternative)),
                mapOf("rewe" to "REWE", "penny" to "PENNY"))
        } }
        compose.onNodeWithTag("shopping-list").performScrollToNode(hasTestTag("shopping-item:item"))
        compose.waitUntil(10_000) { compose.onAllNodesWithContentDescription("Produktbild: Gouda Scheiben").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("shopping-image:item").onChildren().filter(hasContentDescription("Produktbild: Gouda Scheiben")).assertCountEquals(1)
        compose.onNodeWithTag("shopping-list").performScrollToNode(hasText("Im Angebot?"))
        compose.onNodeWithText("Im Angebot?").performClick()
        compose.onNodeWithTag("shopping-list").performScrollToNode(hasTestTag("shopping-match-image:item:two"))
        compose.waitUntil(10_000) { compose.onAllNodesWithContentDescription("Produktbild: Gouda Stück").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("shopping-match-image:item:two").assertIsDisplayed()
        compose.onNodeWithContentDescription("Produktbild: Gouda Stück").assertIsDisplayed()
    }

    @Test fun manualWishDoesNotBorrowAnUnselectedSimilarProductsPicture() {
        val match = offer("other", "Gouda Käsechips")
        val row = ShoppingListRow("gouda", "Gouda", 1, false, itemId = "manual")
        compose.setContent { MaterialTheme {
            ShoppingListContent(MainUiState(shoppingItems = listOf(row), offers = listOf(match)), emptyMap())
        } }
        compose.onNodeWithTag("shopping-list").performScrollToNode(hasTestTag("shopping-image:manual"))
        compose.onNodeWithContentDescription("Kein Produktbild verfügbar").assertIsDisplayed()
        compose.onAllNodesWithContentDescription("Produktbild: Gouda Käsechips").assertCountEquals(0)
        compose.onNodeWithTag("shopping-list").performScrollToNode(hasTestTag("shopping-remove:manual"))
        compose.onNodeWithTag("shopping-remove:manual").assertIsDisplayed()
    }

    @Test fun checkedItemKeepsItsExplicitlyAssignedPicture() {
        val selected = offer("one", "Gouda Scheiben")
        val row = ShoppingListRow("gouda", "Gouda", 1, true, itemId = "done", retailerId = "rewe", offerId = "one")
        compose.setContent { MaterialTheme {
            ShoppingListContent(MainUiState(shoppingItems = listOf(row), offers = listOf(selected)), mapOf("rewe" to "REWE"))
        } }
        compose.onNodeWithTag("shopping-list").performScrollToNode(hasTestTag("shopping-image:done"))
        compose.waitUntil(10_000) { compose.onAllNodesWithContentDescription("Produktbild: Gouda Scheiben").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithContentDescription("Produktbild: Gouda Scheiben").assertIsDisplayed()
    }
}
