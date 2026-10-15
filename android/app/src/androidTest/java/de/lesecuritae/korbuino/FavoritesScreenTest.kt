package de.lesecuritae.korbuino

import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import de.lesecuritae.korbuino.data.FavoriteEntity
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import de.lesecuritae.korbuino.notifications.NtfySettings
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** Pure callback components: these tests never create a ViewModel or publish a message. */
class FavoritesScreenTest {
    @get:Rule val compose = createComposeRule()

    @Test fun favoriteCanBeSavedWithoutNotificationsAndInvalidPriceCannotSave() {
        var savedQuery: String? = null
        var savedNotifications: Boolean? = null
        var savedRetailers: Set<String>? = null
        compose.setContent {
            MaterialTheme {
                Box(Modifier.size(400.dp,720.dp)) {
                    FavoritesContent(MainUiState(postalCode="12345"),mapOf("rewe" to "REWE"),
                        onSave = { query, ids, _, _, _, notifications, _ ->
                            savedQuery=query; savedNotifications=notifications; savedRetailers=ids
                        }, onRemove = {})
                }
            }
        }
        compose.onNodeWithTag("favorite_add").performClick()
        compose.onNodeWithTag("favorite_query").performTextInput("Em-eukal")
        compose.onNodeWithTag("favorite_max_price").performTextInput("1,999")
        compose.onNodeWithTag("favorite_save").assertIsNotEnabled()
        compose.onNodeWithTag("favorite_max_price").performTextClearance()
        compose.onNodeWithTag("favorite_max_price").performTextInput("3,00")
        compose.onNodeWithTag("favorite_retailer_rewe").performClick()
        compose.onNodeWithTag("favorite_notifications").assertIsOff()
        compose.onNodeWithTag("favorite_save").performClick()
        compose.runOnIdle {
            assertEquals("Em-eukal",savedQuery)
            assertEquals(false,savedNotifications)
            assertEquals(setOf("rewe"),savedRetailers)
        }
    }

    @Test fun existingFavoriteCanBeEditedAndDeletedWithoutChangingIdentity() {
        var savedId: String? = null
        var savedQuery: String? = null
        var removed: String? = null
        val favorite=FavoriteEntity("stable",1,"Coca-Cola",postalCode="12345")
        compose.setContent {
            MaterialTheme {
                FavoritesContent(MainUiState(postalCode="12345",favorites=listOf(favorite)),mapOf("rewe" to "REWE"),
                    onSave={query,_,_,_,_,_,id -> savedQuery=query; savedId=id},onRemove={removed=it.productId})
            }
        }
        compose.onNodeWithTag("favorites_screen").performScrollToNode(hasTestTag("favorite_edit_stable"))
        compose.onNodeWithTag("favorite_edit_stable").performClick()
        compose.onNodeWithTag("favorite_query").performTextReplacement("Coca Cola Zero")
        compose.onNodeWithTag("favorite_save").performClick()
        compose.runOnIdle { assertEquals("stable",savedId); assertEquals("Coca Cola Zero",savedQuery) }
        compose.onNodeWithTag("favorite_delete_stable").performClick()
        compose.onNode(hasText("Löschen") and hasAnyAncestor(isDialog())).performClick()
        compose.runOnIdle { assertEquals("stable",removed) }
    }

    @Test fun ntfyInvalidUrlCannotSaveOrSendAndDisabledHasNoTestAction() {
        var saves=0
        var sends=0
        compose.setContent {
            MaterialTheme {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    NtfySettingsContent(NtfySettings(),onSave={ saves++ },onTest={ sends++ })
                }
            }
        }
        compose.onNodeWithTag("ntfy_test").assertIsNotEnabled()
        compose.onNodeWithTag("ntfy_topic_url").performTextInput("http://example.org/topic")
        compose.onNodeWithTag("ntfy_save").performScrollTo().performClick()
        compose.onNodeWithTag("ntfy_error").assertExists()
        compose.runOnIdle { assertEquals(0,saves); assertEquals(0,sends) }
    }
}
