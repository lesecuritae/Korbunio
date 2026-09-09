package de.lesecuritae.korbuino

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.location.Geocoder
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.graphics.BitmapFactory
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.setContent
import androidx.core.content.ContextCompat
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
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.foundation.layout.size
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.platform.LocalContext
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    private val challengeLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        if (it.resultCode == RESULT_OK) (lastViewModel)?.refresh()
    }
    internal var lastViewModel: MainViewModel? = null
    private val locationPermission = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        if (result.values.any { it }) resolveLocation()
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            KorbuinoApp(
                openChallenge = { url -> challengeLauncher.launch(ChallengeActivity.intent(this, url)) },
                requestLocation = { requestLocation() },
            ) { lastViewModel = it }
        }
    }

    private fun requestLocation() {
        val granted = ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED
        if (granted) resolveLocation() else locationPermission.launch(arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION))
    }

    @SuppressLint("MissingPermission")
    private fun resolveLocation() {
        val viewModel = lastViewModel ?: return
        viewModel.message("Standort wird ermittelt …")
        val manager = getSystemService(LOCATION_SERVICE) as LocationManager
        val provider = listOf(LocationManager.NETWORK_PROVIDER, LocationManager.GPS_PROVIDER)
            .firstOrNull { runCatching { manager.isProviderEnabled(it) }.getOrDefault(false) }
        if (provider == null) {
            viewModel.message("Kein Standortanbieter verfügbar")
            return
        }
        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                manager.removeUpdates(this)
                lifecycleScope.launch(Dispatchers.IO) {
                    val address = runCatching {
                        Geocoder(this@MainActivity).getFromLocation(location.latitude, location.longitude, 1)?.firstOrNull()
                    }.getOrNull()
                    withContext(Dispatchers.Main) {
                        val postal = address?.postalCode.orEmpty()
                        val city = address?.locality ?: address?.subAdminArea.orEmpty()
                        if (postal.matches(Regex("\\d{5}"))) {
                            viewModel.postalCode(postal)
                            if (city.isNotBlank()) viewModel.city(city)
                            viewModel.message("Standort übernommen: $postal ${city}".trim())
                            viewModel.refresh()
                        } else viewModel.message("Am Standort wurde keine deutsche PLZ gefunden")
                    }
                }
            }
        }
        runCatching { manager.requestLocationUpdates(provider, 0L, 0f, listener, mainLooper) }
            .onFailure { viewModel.message("Standort konnte nicht ermittelt werden") }
    }
}

@Composable
private fun KorbuinoApp(
    openChallenge: (String) -> Unit,
    requestLocation: () -> Unit,
    registerViewModel: (MainViewModel) -> Unit,
) {
    val viewModel: MainViewModel = viewModel()
    registerViewModel(viewModel)
    val state by viewModel.state.collectAsState()
    val context = LocalContext.current
    val exportBackup = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri -> uri?.let(viewModel::exportBackup) }
    val importBackup = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> uri?.let(viewModel::importBackup) }
    var showOverview by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(state.offers.size, state.loading) {
        if (!state.loading && state.offers.isNotEmpty()) showOverview = true
    }
    val dark = isSystemInDarkTheme()
    MaterialTheme(colorScheme = if (dark) darkColorScheme() else lightColorScheme()) {
        Surface(modifier = Modifier.fillMaxSize()) {
            if (showOverview && state.offers.isNotEmpty()) {
                OfferOverview(
                    state = state,
                    viewModel = viewModel,
                    onBack = { showOverview = false },
                    openChallenge = openChallenge,
                )
            } else Column(
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
                Button(onClick = requestLocation) { Text("PLZ über Standort ermitteln") }
                Button(onClick = viewModel::refresh, enabled = !state.loading) {
                    if (state.loading) CircularProgressIndicator()
                    else Text("Angebote laden")
                }
                Text(state.message)
                OutlinedTextField(value = state.serverUrl, onValueChange = viewModel::serverUrl, label = { Text("Eigener Korbuino-Server (optional)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(value = state.serverToken, onValueChange = viewModel::serverToken, label = { Text("Server-Token (optional im LAN)") }, visualTransformation = PasswordVisualTransformation(), singleLine = true, modifier = Modifier.fillMaxWidth())
                Button(onClick = { viewModel.setServerMode(!state.serverMode) }) {
                    Text(if (state.serverMode) "Servermodus deaktivieren" else "Eigenen Server verwenden")
                }
                state.challengeUrl?.let { url ->
                    Button(onClick = { openChallenge(url) }) { Text("Händler-Bestätigung öffnen") }
                }
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
            }
        }
    }
}

@Composable
private fun OfferOverview(
    state: MainUiState,
    viewModel: MainViewModel,
    onBack: () -> Unit,
    openChallenge: (String) -> Unit,
) {
    var offerFilter by rememberSaveable { mutableStateOf("") }
    val visibleOffers = state.offers.filter { display ->
        offerFilter.isBlank() || display.productName.contains(offerFilter, ignoreCase = true) ||
            display.offer.retailerId.contains(offerFilter, ignoreCase = true) ||
            display.offer.categoryId.orEmpty().contains(offerFilter, ignoreCase = true)
    }
    Column(
        modifier = Modifier.padding(24.dp).fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
            Button(onClick = onBack) { Text("Zurück") }
            Text("Angebote", style = MaterialTheme.typography.headlineMedium)
        }
        Text(
            "${state.offers.size} Angebote · ${state.offers.map { it.offer.retailerId }.distinct().size} Händler",
            style = MaterialTheme.typography.bodyMedium,
        )
        OutlinedTextField(
            value = offerFilter,
            onValueChange = { offerFilter = it.take(80) },
            label = { Text("Angebote durchsuchen") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            Button(onClick = viewModel::refresh, enabled = !state.loading) {
                if (state.loading) CircularProgressIndicator() else Text("Aktualisieren")
            }
            state.challengeUrl?.let { url ->
                Button(onClick = { openChallenge(url) }) { Text("Händler bestätigen") }
            }
        }
        Text(state.message)
        LazyColumn(modifier = Modifier.fillMaxWidth().weight(1f)) {
            items(visibleOffers, key = { it.offer.id }) { offer ->
                Row(
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
                ) {
                    OfferThumbnail(offer.imagePath)
                    Column {
                        Text(offer.productName)
                        Text(offer.offer.retailerId, style = MaterialTheme.typography.labelMedium)
                        offer.offer.categoryId?.takeIf { it.isNotBlank() }?.let { category ->
                            Text(category, style = MaterialTheme.typography.bodySmall)
                        }
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
