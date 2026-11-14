package de.lesecuritae.korbuino

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import de.lesecuritae.korbuino.providers.RossmannStockClient
import de.lesecuritae.korbuino.providers.StockProduct
import de.lesecuritae.korbuino.providers.NetworkClientFactory
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable
internal fun AvailabilityScreen(initialPostal: String, onBack: () -> Unit) {
    var postal by rememberSaveable { mutableStateOf(initialPostal) }
    var articles by rememberSaveable { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("") }
    var products by remember { mutableStateOf(emptyList<StockProduct>()) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current.applicationContext
    Column(Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        TextButton(onClick = onBack) { Text("Zurück") }
        Text("Rossmann-Filialbestand", style = MaterialTheme.typography.headlineSmall)
        Text("Ohne Rossmann-App und ohne Rossmann-Konto. Gemeldeter Buchbestand, keine Reservierung oder Garantie für Regalware.")
        OutlinedTextField(postal, { postal = it }, label = { Text("Postleitzahl") }, singleLine = true, enabled = !loading)
        OutlinedTextField(articles, { articles = it }, label = { Text("Artikelnummern, eine pro Zeile") }, enabled = !loading)
        Text("Höchstens fünf sechsstellige Artikelnummern. Sie stehen auf der Rossmann-Produktseite. Keine EAN verwenden.")
        Button(enabled = !loading, onClick = {
            loading = true; message = "Bestände werden geprüft …"; products = emptyList()
            scope.launch {
                try {
                    val dans = articles.trim().split(Regex("[\\s,;]+")).distinct()
                    // Reuse the existing legacy Android TLS-provider preparation.
                    // Stock requests still use their own cookie-free HTTP client.
                    withContext(Dispatchers.IO) { NetworkClientFactory.create(context) }
                    products = RossmannStockClient.shared.check(postal.trim(), dans)
                    message = "Abfrage abgeschlossen. Fehler bedeuten nicht ausverkauft."
                } catch (cancelled: CancellationException) { throw cancelled }
                catch (error: Exception) { message = error.message ?: "Bestandsabfrage fehlgeschlagen" }
                finally { loading = false }
            }
        }) { Text(if (loading) "Abfrage läuft …" else "Bestände prüfen") }
        Text(message)
        for (product in products) {
            Text("Artikel ${product.dan}", style = MaterialTheme.typography.titleMedium)
            if (product.error != null) Text(product.error)
            else {
                val time = runCatching { DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm:ss").withZone(ZoneId.of("Europe/Berlin")).format(Instant.parse(product.checkedAt)) }.getOrDefault(product.checkedAt)
                Text("Abgerufen: $time${if (product.fromCache) " · zwischengespeichert" else ""}")
                if (product.stores.isEmpty()) Text("Keine Filialdaten erhalten; das bedeutet nicht ausverkauft.")
                for (store in product.stores) {
                    val stock = when (store.inStock) {
                        null -> "Bestand unbekannt"
                        false -> "0 Stück gemeldet"
                        true -> "${if (store.exact) "" else "mindestens "}${store.minimum} Stück gemeldet"
                    }
                    Text("${store.postalCode} ${store.city}, ${store.street}: $stock")
                }
            }
        }
        Text("Suchort und Artikelnummern werden an Rossmann übermittelt; die PLZ wird über OpenStreetMap/Nominatim aufgelöst. Kein Zugriff auf dein Rossmann-Konto oder deine Gerätekennung.")
    }
}
