package de.lesecuritae.korbuino

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ShoppingListRow
import org.junit.Rule
import org.junit.Test

class ShoppingPositionsUiTest {
    @get:Rule val compose = createComposeRule()

    @Test fun retailerSubtotalUsesPacksAndLastRemoveCanBeUndone() {
        val row = ShoppingListRow("p", "Em-eukal", 3, false, itemId="one", retailerId="kaufland", offerId="bundle")
        val offer = OfferDisplay(OfferEntity("bundle","kaufland","p",externalId="bundle",priceCents=300,
            sourceUrl="https://example.org",cachedAt=0,multiBuyQuantity=3,multiBuyTotalCents=300),"Em-eukal")
        compose.setContent {
            var state by remember { mutableStateOf(MainUiState(shoppingItems=listOf(row),offers=listOf(offer))) }
            MaterialTheme {
                ShoppingListContent(state,mapOf("kaufland" to "Kaufland"),ShoppingActions(
                    remove = { state=state.copy(shoppingItems=emptyList(),removedShoppingItem=it) },
                    undo = { state=state.copy(shoppingItems=listOf(state.removedShoppingItem!!),removedShoppingItem=null) },
                ))
            }
        }
        compose.onNodeWithTag("shopping-list").performScrollToNode(hasTestTag("subtotal:kaufland"))
        compose.onNodeWithTag("subtotal:kaufland").assertTextContains("3,00", substring=true)
        compose.onNodeWithTag("shopping-list").performScrollToNode(hasTestTag("shopping-remove:one"))
        compose.onNodeWithTag("shopping-remove:one").performClick()
        compose.onNodeWithText("Noch keine Artikel in der Einkaufsliste.").assertExists()
        compose.onNodeWithTag("shopping-undo").performClick()
        compose.onNodeWithTag("shopping-list").performScrollToNode(hasText("Em-eukal",substring=true))
        compose.onNodeWithTag("shopping-item:one").assertExists()
    }
}
