package de.lesecuritae.korbuino

import android.app.Application
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ShoppingListRow
import org.junit.Rule
import org.junit.Test

/** Exercises the production shopping screen in a finite, enlarged-font viewport. */
class ShoppingListScrollTest {
    @get:Rule val compose = createComposeRule()

    @Test fun longShoppingListReachesLastItemAfterExpandingAnOffer() {
        val application = ApplicationProvider.getApplicationContext<Application>()
        val viewModel = MainViewModel(application)
        val rows = (0 until 80).map { index ->
            ShoppingListRow("item-$index", "Artikel%03d".format(index), 2, false,
                itemId = "position-$index", retailerId = "rewe", offerId = "offer-$index")
        }
        val offers = rows.mapIndexed { index, row ->
            OfferDisplay(OfferEntity("offer-$index", "rewe", row.productId, externalId = "$index",
                priceCents = 129, sourceUrl = "https://example.org/test", cachedAt = 0), row.name)
        }
        compose.setContent {
            val density = LocalDensity.current.density
            CompositionLocalProvider(LocalDensity provides Density(density, fontScale = 1.5f)) {
                MaterialTheme {
                    Box(Modifier.width(360.dp).height(420.dp)) {
                        ShoppingListOverview(MainUiState(shoppingItems = rows, offers = offers), viewModel)
                    }
                }
            }
        }
        compose.onNodeWithTag("shopping-list").performScrollToNode(hasText("Im Angebot?"))
        compose.onAllNodesWithText("Im Angebot?").onFirst()
            .performSemanticsAction(SemanticsActions.OnClick) { it() }
        compose.onNodeWithTag("shopping-list").performScrollToNode(hasText("Artikel079"))
        compose.onAllNodesWithText("Artikel079").onFirst().assertIsDisplayed()
    }
}
