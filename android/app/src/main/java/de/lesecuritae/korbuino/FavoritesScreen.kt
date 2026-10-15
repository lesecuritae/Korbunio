package de.lesecuritae.korbuino

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import de.lesecuritae.korbuino.data.FavoriteEntity
import de.lesecuritae.korbuino.notifications.NtfySender
import de.lesecuritae.korbuino.notifications.NtfySettings
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import java.math.BigDecimal
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.temporal.TemporalAdjusters

/** Null is a valid empty limit; [favoritePriceError] distinguishes it from invalid input. */
internal fun favoritePriceCents(text: String): Int? {
    val value = text.trim()
    if (value.isBlank()) return null
    if (!Regex("\\d{1,7}([,.]\\d{1,2})?").matches(value)) return null
    return runCatching { BigDecimal(value.replace(',', '.')).movePointRight(2).intValueExact() }
        .getOrNull()?.takeIf { it > 0 }
}
internal fun favoritePriceError(text: String): String? =
    if (text.isNotBlank() && favoritePriceCents(text) == null) "Bitte einen Preis größer als 0 mit höchstens zwei Nachkommastellen eingeben." else null

private fun favoriteRetailers(favorite: FavoriteEntity): Set<String> = runCatching {
    Json.parseToJsonElement(favorite.preferredRetailerIdsJson).jsonArray.map { it.jsonPrimitive.content }.toSet()
}.getOrDefault(emptySet())

@Composable
internal fun FavoritesScreen(
    state: MainUiState,
    retailerNames: Map<String, String>,
    viewModel: MainViewModel,
    modifier: Modifier = Modifier,
) = FavoritesContent(state, retailerNames, viewModel::saveFavorite, viewModel::removeFavorite, modifier)

@Composable
internal fun FavoritesContent(
    state: MainUiState,
    retailerNames: Map<String, String>,
    onSave: (String, Set<String>, Int?, Boolean, Boolean, Boolean, String?) -> Unit,
    onRemove: (FavoriteEntity) -> Unit,
    modifier: Modifier = Modifier,
) {
    var editing by remember { mutableStateOf<FavoriteEntity?>(null) }
    var editorVisible by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf<FavoriteEntity?>(null) }
    val today = LocalDate.now(ZoneId.of("Europe/Berlin"))
    val monday = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
    val format = DateTimeFormatter.ofPattern("dd.MM.yyyy")
    val currentLabel = "Aktuelle Woche: ${monday.format(format)} – ${monday.plusDays(6).format(format)}"
    val nextLabel = "Nächste Woche: ${monday.plusWeeks(1).format(format)} – ${monday.plusDays(13).format(format)}"
    LazyColumn(modifier.fillMaxSize().testTag("favorites_screen"), verticalArrangement = Arrangement.spacedBy(12.dp),
        contentPadding = PaddingValues(16.dp)) {
        item {
            Text("Favoriten", style = MaterialTheme.typography.headlineSmall)
            Text("Suchbegriffe und Angebotswünsche speichern. Meldungen sind pro Favorit optional.")
            Text("$currentLabel\n$nextLabel\nZeitzone: Europe/Berlin", style = MaterialTheme.typography.bodySmall)
            Button(onClick = { editing = null; editorVisible = true }, modifier = Modifier.testTag("favorite_add")) { Text("Favorit hinzufügen") }
        }
        if (state.favorites.isEmpty()) item { Text("Noch keine Favoriten. Zum Beispiel Coca-Cola oder Em-eukal hinzufügen.") }
        items(state.favorites, key = { it.productId }) { favorite ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(favorite.query, style = MaterialTheme.typography.titleMedium)
                    val ids = favoriteRetailers(favorite)
                    Text(if (ids.isEmpty()) "Alle Händler" else ids.sorted().joinToString { retailerNames[it] ?: it })
                    Text(favorite.maxPriceCents?.let { "Preisgrenze: ${OfferMatcher.formatPrice(it)}" } ?: "Ohne Preisgrenze")
                    Text(listOfNotNull(if (favorite.includeCurrentWeek) "Aktuelle Woche" else null,
                        if (favorite.includeNextWeek) "Nächste Woche" else null).joinToString(" · "))
                    if (favorite.postalCode.isNotBlank()) Text("PLZ ${favorite.postalCode}", style = MaterialTheme.typography.bodySmall)
                    Text(if (favorite.notificationsEnabled) "Meldungen gewünscht" else "Meldungen aus")
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(onClick = { editing = favorite; editorVisible = true }, modifier = Modifier.testTag("favorite_edit_${favorite.productId}")) { Text("Bearbeiten") }
                        TextButton(onClick = { deleting = favorite }, modifier = Modifier.testTag("favorite_delete_${favorite.productId}")) { Text("Löschen") }
                    }
                }
            }
        }
        item {
            Text("Es werden veröffentlichte Angebote geprüft; eine Vorschau hängt vom Händler ab. Die Preisgrenze gilt für den nötigen Zahlbetrag, bei Mehrfachkauf also für das ganze Paket. Kundenpreise gelten nur für deine ausgewählten Programme; Guthaben wird nicht vom Preis abgezogen.", style = MaterialTheme.typography.bodySmall)
            Text("Meldungen benötigen zusätzlich eine aktivierte ntfy-Verbindung. Automatische Aktualisierungen werden separat in den Einstellungen aktiviert.", style = MaterialTheme.typography.bodySmall)
        }
    }
    if (editorVisible) FavoriteEditor(editing, retailerNames, state.postalCode, currentLabel, nextLabel,
        onDismiss = { editorVisible = false }, onSave = { query, ids, price, current, next, notify ->
            onSave(query, ids, price, current, next, notify, editing?.productId)
            editorVisible = false
        })
    deleting?.let { favorite ->
        AlertDialog(onDismissRequest = { deleting = null }, title = { Text("Favorit löschen?") },
            text = { Text(favorite.query) }, confirmButton = {
                TextButton(onClick = { onRemove(favorite); deleting = null }) { Text("Löschen") }
            }, dismissButton = { TextButton(onClick = { deleting = null }) { Text("Abbrechen") } })
    }
}

@Composable
private fun FavoriteEditor(
    favorite: FavoriteEntity?, retailerNames: Map<String, String>, postalCode: String,
    currentLabel: String, nextLabel: String, onDismiss: () -> Unit,
    onSave: (String, Set<String>, Int?, Boolean, Boolean, Boolean) -> Unit,
) {
    var query by remember(favorite?.productId) { mutableStateOf(favorite?.query.orEmpty()) }
    var ids by remember(favorite?.productId) { mutableStateOf(favorite?.let(::favoriteRetailers) ?: emptySet()) }
    var price by remember(favorite?.productId) { mutableStateOf(favorite?.maxPriceCents?.let { "${it / 100},${(it % 100).toString().padStart(2, '0')}" }.orEmpty()) }
    var current by remember(favorite?.productId) { mutableStateOf(favorite?.includeCurrentWeek ?: true) }
    var next by remember(favorite?.productId) { mutableStateOf(favorite?.includeNextWeek ?: true) }
    var notify by remember(favorite?.productId) { mutableStateOf(favorite?.notificationsEnabled ?: false) }
    val priceError = favoritePriceError(price)
    val valid = query.isNotBlank() && priceError == null && (current || next)
    AlertDialog(onDismissRequest = onDismiss,
        title = { Text(if (favorite == null) "Neuer Favorit" else "Favorit bearbeiten") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(query, { query = it.take(120) }, label = { Text("Suchbegriff") }, singleLine = true,
                    modifier = Modifier.fillMaxWidth().testTag("favorite_query"))
                OutlinedTextField(price, { price = it.take(12) }, label = { Text("Maximaler Zahlbetrag in € (optional)") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), singleLine = true,
                    isError = priceError != null, supportingText = { if (priceError != null) Text(priceError) },
                    modifier = Modifier.fillMaxWidth().testTag("favorite_max_price"))
                Text("Bei Mehrkauf gilt der Höchstbetrag für das gesamte Aktionspaket, nicht für eine einzelne Packung.", style = MaterialTheme.typography.bodySmall)
                Text("Händler", style = MaterialTheme.typography.titleSmall)
                LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    item { FilterChip(selected = ids.isEmpty(), onClick = { ids = emptySet() }, label = { Text("Alle") }) }
                    items(retailerNames.entries.filter { it.key != "all" }.sortedBy { it.value }, key = { it.key }) { (id, name) ->
                        FilterChip(selected = id in ids, onClick = { ids = if (id in ids) ids - id else ids + id }, label = { Text(name) },
                            modifier = Modifier.testTag("favorite_retailer_$id"))
                    }
                }
                FavoriteCheck(currentLabel, current, { current = it }, "favorite_current_week")
                FavoriteCheck(nextLabel, next, { next = it }, "favorite_next_week")
                if (!current && !next) Text("Mindestens eine Woche auswählen.", color = MaterialTheme.colorScheme.error)
                Text("Zeitangaben gelten für Europe/Berlin. Vorschauen enthalten nur bereits veröffentlichte Angebote.", style = MaterialTheme.typography.bodySmall)
                FavoriteCheck("ntfy-Meldungen für diesen Favoriten", notify, { notify = it }, "favorite_notifications")
                Text("Der Favorit wird auch ohne Meldungen gespeichert. PLZ: ${postalCode.ifBlank { "noch nicht festgelegt" }}", style = MaterialTheme.typography.bodySmall)
            }
        }, confirmButton = {
            TextButton(enabled = valid, onClick = { onSave(query.trim(), ids, favoritePriceCents(price), current, next, notify) },
                modifier = Modifier.testTag("favorite_save")) { Text("Speichern") }
        }, dismissButton = { TextButton(onClick = onDismiss) { Text("Abbrechen") } })
}

@Composable
private fun FavoriteCheck(label: String, checked: Boolean, onChecked: (Boolean) -> Unit, tag: String) {
    Row(Modifier.fillMaxWidth().clickable { onChecked(!checked) }.padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        Checkbox(checked, onChecked, modifier = Modifier.testTag(tag))
        Text(label, modifier = Modifier.weight(1f))
    }
}

@Composable
internal fun NtfySettingsCard(state: MainUiState, viewModel: MainViewModel) =
    NtfySettingsContent(state.ntfySettings, viewModel::saveNtfy, viewModel::testNtfy)

@Composable
internal fun NtfySettingsContent(settings: NtfySettings, onSave: (NtfySettings) -> Unit, onTest: (NtfySettings) -> Unit) {
    // Topic URL and token remain in memory only while this screen is composed.
    var enabled by remember(settings) { mutableStateOf(settings.enabled) }
    var url by remember(settings) { mutableStateOf(settings.topicUrl) }
    var token by remember(settings) { mutableStateOf(settings.bearerToken) }
    var error by remember { mutableStateOf<String?>(null) }
    Card(Modifier.fillMaxWidth().testTag("ntfy_settings")) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Favoritenmeldungen mit ntfy", style = MaterialTheme.typography.titleMedium)
            Text("Optional: Korbunio sendet passende Angebote direkt an dein ntfy-Thema. Zum Empfangen benötigst du einen externen ntfy-Client, der dieses Thema abonniert. Ein eigener Korbunio-Server ist dafür nicht nötig.")
            FavoriteCheck("ntfy aktivieren", enabled, { enabled = it; error = null }, "ntfy_enabled")
            OutlinedTextField(url, { url = it; error = null }, label = { Text("ntfy-Themen-URL (HTTPS)") },
                placeholder = { Text("https://ntfy.example/mein-thema") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth().testTag("ntfy_topic_url"))
            OutlinedTextField(token, { token = it; error = null }, label = { Text("Bearer-Token (optional)") },
                visualTransformation = PasswordVisualTransformation(), singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                modifier = Modifier.fillMaxWidth().testTag("ntfy_token"))
            if (error != null) Text(error.orEmpty(), color = MaterialTheme.colorScheme.error, modifier = Modifier.testTag("ntfy_error"))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    val draft = NtfySettings(enabled, url.trim(), token.trim())
                    error = NtfySender.validationError(draft)
                    if (error == null) onSave(draft)
                }, modifier = Modifier.testTag("ntfy_save")) { Text("Speichern") }
                TextButton(enabled = enabled, onClick = {
                    val draft = NtfySettings(enabled, url.trim(), token.trim())
                    error = NtfySender.validationError(draft, requireTopic = true)
                    if (error == null) onTest(draft)
                }, modifier = Modifier.testTag("ntfy_test")) { Text("Test senden") }
            }
            Text("URL und Token werden geschützt auf diesem Gerät gespeichert und nicht ins Backup aufgenommen. Nachrichten enthalten Produkt, Händler, Preis und Gültigkeit.", style = MaterialTheme.typography.bodySmall)
            Text("Angebote werden nach manueller Aktualisierung geprüft. Automatische Aktualisierungen aktivierst du separat in den Hintergrund-Einstellungen.", style = MaterialTheme.typography.bodySmall)
        }
    }
}
