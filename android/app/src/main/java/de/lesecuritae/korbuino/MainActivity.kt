package de.lesecuritae.korbuino

import android.os.Bundle
import android.graphics.BitmapFactory
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.Image
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.foundation.layout.size
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.platform.LocalContext
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { KorbuinoApp() }
    }
}

@Composable
private fun KorbuinoApp() {
    val viewModel: MainViewModel = viewModel()
    val state by viewModel.state.collectAsState()
    val context = LocalContext.current
    val exportBackup = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri -> uri?.let(viewModel::exportBackup) }
    val importBackup = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> uri?.let(viewModel::importBackup) }
    MaterialTheme {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier.padding(24.dp).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("Korbuino", style = MaterialTheme.typography.headlineMedium)
                Text("Serverlose native Android-App", style = MaterialTheme.typography.titleMedium)
                Text("Angebote werden direkt abgerufen und lokal gespeichert.")
                var menuOpen by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf(false) }
                androidx.compose.foundation.layout.Box {
                    Button(onClick = { menuOpen = true }) {
                        Text("Händler: ${viewModel.retailers.firstOrNull { it.first == state.retailerId }?.second ?: state.retailerId}")
                    }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        viewModel.retailers.forEach { (id, name) ->
                            DropdownMenuItem(text = { Text(name) }, onClick = { viewModel.retailer(id); menuOpen = false })
                        }
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedTextField(
                        value = state.postalCode,
                        onValueChange = viewModel::postalCode,
                        label = { Text("PLZ") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = state.city,
                        onValueChange = viewModel::city,
                        label = { Text("Stadt") },
                        singleLine = true,
                        modifier = Modifier.weight(2f),
                    )
                }
                Button(onClick = viewModel::refresh, enabled = !state.loading) {
                    if (state.loading) CircularProgressIndicator()
                    else Text("Angebote laden")
                }
                Text(state.message)
                Button(onClick = viewModel::checkUpdate) { Text("Nach Updates suchen") }
                Button(onClick = { viewModel.setDailySync(!state.dailySync) }) {
                    Text(if (state.dailySync) "Tägliche Aktualisierung deaktivieren" else "Tägliche Aktualisierung aktivieren")
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    Button(onClick = { exportBackup.launch("korbunio-backup.json") }) { Text("Backup exportieren") }
                    Button(onClick = { importBackup.launch(arrayOf("application/json", "text/json", "text/plain")) }) { Text("Backup importieren") }
                }
                state.update?.let { update ->
                    Button(onClick = { viewModel.installUpdate(update) { context.startActivity(it) } }, enabled = !state.loading) {
                        Text("Update ${update.version} installieren")
                    }
                }
                var itemText by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf("") }
                Text("Einkaufsliste", style = MaterialTheme.typography.titleLarge)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedTextField(
                        value = itemText,
                        onValueChange = { itemText = it.take(120) },
                        label = { Text("Artikel hinzufügen") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    Button(onClick = { viewModel.addShoppingItem(itemText); itemText = "" }) { Text("+") }
                }
                state.shoppingItems.forEach { item -> Text("${item.quantity}× ${item.name}") }
                var kitchenToken by androidx.compose.runtime.remember { androidx.compose.runtime.mutableStateOf("") }
                Text("KitchenOwl (optional)", style = MaterialTheme.typography.titleLarge)
                OutlinedTextField(
                    value = state.kitchenOwlUrl,
                    onValueChange = viewModel::kitchenOwlUrl,
                    label = { Text("KitchenOwl HTTPS-Adresse") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedTextField(
                        value = kitchenToken,
                        onValueChange = { kitchenToken = it },
                        label = { Text("Token") },
                        visualTransformation = PasswordVisualTransformation(),
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    Button(onClick = { viewModel.connectKitchenOwl(state.kitchenOwlUrl, kitchenToken) }) { Text("Verbinden") }
                }
                state.kitchenTargets.forEach { target ->
                    Button(onClick = { viewModel.syncKitchenOwl(target) }) { Text("Zu ${target.label} übertragen") }
                }
                Text("Angebote", style = MaterialTheme.typography.titleLarge)
                LazyColumn(modifier = Modifier.fillMaxWidth().weight(1f)) {
                    items(state.offers, key = { it.offer.id }) { offer ->
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(10.dp),
                            modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
                        ) {
                            OfferThumbnail(offer.imagePath)
                            Column {
                                Text(offer.productName)
                                Text(
                                    "${offer.offer.priceCents / 100},${(offer.offer.priceCents % 100).toString().padStart(2, '0')} €",
                                    style = MaterialTheme.typography.bodyMedium,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun OfferThumbnail(path: String?) {
    val bitmapState = remember { mutableStateOf<android.graphics.Bitmap?>(null) }
    LaunchedEffect(path) {
        bitmapState.value = path?.let { withContext(Dispatchers.IO) { BitmapFactory.decodeFile(it) } }
    }
    val bitmap = bitmapState.value
    if (bitmap != null) {
        Image(
            bitmap = bitmap.asImageBitmap(),
            contentDescription = null,
            contentScale = ContentScale.Fit,
            modifier = Modifier.size(56.dp).padding(top = 2.dp),
        )
    }
}
