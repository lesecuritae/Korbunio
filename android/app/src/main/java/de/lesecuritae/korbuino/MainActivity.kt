package de.lesecuritae.korbuino

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.location.Geocoder
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import de.lesecuritae.korbuino.data.OfferEntity
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.setContent
import androidx.core.content.ContextCompat
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.Image
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.IconButton
import androidx.compose.material3.FilterChip
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
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.background
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
    var showSettings by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(state.offers.size, state.loading) {
        if (!state.loading && state.offers.isNotEmpty()) showOverview = true
    }
    val dark = isSystemInDarkTheme()
    val lightScheme = lightColorScheme(
        primary = Color(0xFF116149),
        onPrimary = Color.White,
        background = Color(0xFFF4F7F5),
        surface = Color(0xFFF4F7F5),
        surfaceVariant = Color.White,
        onSurface = Color(0xFF14201B),
        outline = Color(0xFFDCE5E0),
    )
    val darkScheme = darkColorScheme(
        primary = Color(0xFF72D5A6),
        onPrimary = Color(0xFF10231B),
        background = Color(0xFF111318),
        surface = Color(0xFF111318),
        surfaceVariant = Color(0xFF191C22),
        onSurface = Color(0xFFF1F3F5),
        outline = Color(0xFF303641),
    )
    MaterialTheme(colorScheme = if (dark) darkScheme else lightScheme) {
        Surface(modifier = Modifier.fillMaxSize()) {
            if (showOverview && state.offers.isNotEmpty()) {
                OfferOverview(
                    state = state,
                    viewModel = viewModel,
                    onBack = { showOverview = false },
                    openSettings = { showOverview = false; showSettings = true },
                    openChallenge = openChallenge,
                )
            } else if (showSettings) {
                AppSettings(state = state, viewModel = viewModel, onBack = { showSettings = false })
            } else Column(
                modifier = Modifier.padding(24.dp).fillMaxWidth().verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Korbuino", style = MaterialTheme.typography.headlineMedium)
                        Text("Serverlose native Android-App", style = MaterialTheme.typography.titleMedium)
                    }
                    IconButton(onClick = { showSettings = true }) {
                        Text("⚙", style = MaterialTheme.typography.headlineSmall)
                    }
                }
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
            }
        }
    }
}

@Composable
private fun AppSettings(
    state: MainUiState,
    viewModel: MainViewModel,
    onBack: () -> Unit,
) {
    var kitchenToken by rememberSaveable { mutableStateOf("") }
    Column(
        modifier = Modifier.padding(24.dp).fillMaxWidth().verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
            Button(onClick = onBack) { Text("Zurück") }
            Text("Einstellungen", style = MaterialTheme.typography.headlineMedium)
        }
        Text("Verbindungen", style = MaterialTheme.typography.titleLarge)
        Text("Eigener Korbuino-Server", style = MaterialTheme.typography.titleMedium)
        OutlinedTextField(
            value = state.serverUrl,
            onValueChange = viewModel::serverUrl,
            label = { Text("Server-Adresse (optional)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = state.serverToken,
            onValueChange = viewModel::serverToken,
            label = { Text("Server-Token") },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Button(onClick = { viewModel.setServerMode(!state.serverMode) }) {
            Text(if (state.serverMode) "Servermodus deaktivieren" else "Eigenen Server verwenden")
        }
        Text("KitchenOwl", style = MaterialTheme.typography.titleMedium)
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
        Text(state.message, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun OfferOverview(
    state: MainUiState,
    viewModel: MainViewModel,
    onBack: () -> Unit,
    openSettings: () -> Unit,
    openChallenge: (String) -> Unit,
) {
    var offerFilter by rememberSaveable { mutableStateOf("") }
    var retailerFilter by rememberSaveable { mutableStateOf("all") }
    var sortMode by rememberSaveable { mutableStateOf("retailer") }
    var sortMenuOpen by remember { mutableStateOf(false) }
    var selectedTab by rememberSaveable { mutableStateOf(0) }
    val retailerNames = viewModel.retailers.toMap()
    val presentRetailerIds = state.offers.map { it.offer.retailerId }.toSet()
    val retailerIds = viewModel.retailers.map { it.first }.filter { it != "all" && it in presentRetailerIds } +
        presentRetailerIds.filter { it !in retailerNames }.sorted()
    val retailerCounts = state.offers.groupingBy { it.offer.retailerId }.eachCount()
    val retailerOptions = listOf("all" to "Alle Händler") + retailerIds.map { it to (retailerNames[it] ?: it) }
    val visibleOffers = state.offers
        .filter { display -> retailerFilter == "all" || display.offer.retailerId == retailerFilter }
        .filter { display ->
            offerFilter.isBlank() || display.productName.contains(offerFilter, ignoreCase = true) ||
                display.offer.retailerId.contains(offerFilter, ignoreCase = true) ||
                display.offer.categoryId.orEmpty().contains(offerFilter, ignoreCase = true)
        }
        .let { offers ->
            when (sortMode) {
                "product" -> offers.sortedWith(compareBy({ it.productName.lowercase() }, { retailerNames[it.offer.retailerId] ?: it.offer.retailerId }))
                "retailer" -> offers.sortedWith(compareBy(
                    { retailerIds.indexOf(it.offer.retailerId).takeIf { index -> index >= 0 } ?: Int.MAX_VALUE },
                    { effectivePriceCents(it.offer, state.selectedLoyaltyPrograms) },
                    { it.productName.lowercase() },
                ))
                else -> offers.sortedWith(compareBy({ effectivePriceCents(it.offer, state.selectedLoyaltyPrograms) }, { it.productName.lowercase() }))
            }
        }
    val availableLoyaltyPrograms = state.offers.mapNotNull { display ->
        val id = display.offer.loyaltyProgram ?: return@mapNotNull null
        id to (display.offer.loyaltyLabel ?: id)
    }.distinctBy { it.first }.sortedBy { it.second }
    Column(
        modifier = Modifier.padding(24.dp).fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
            Button(onClick = onBack) { Text("Zurück") }
            Text("Angebote", style = MaterialTheme.typography.headlineMedium)
            Spacer(modifier = Modifier.weight(1f))
            IconButton(onClick = openSettings) {
                Text("⚙", style = MaterialTheme.typography.headlineSmall)
            }
        }
        Text(
            "${state.offers.size} Angebote · ${state.offers.map { it.offer.retailerId }.distinct().size} Händler",
            style = MaterialTheme.typography.bodyMedium,
        )
        androidx.compose.material3.TabRow(selectedTabIndex = selectedTab) {
            androidx.compose.material3.Tab(selected = selectedTab == 0, onClick = { selectedTab = 0 }, text = { Text("Ergebnisse") })
            androidx.compose.material3.Tab(selected = selectedTab == 1, onClick = { selectedTab = 1 }, text = { Text("Einkauf") })
        }
        if (selectedTab == 1) {
            ShoppingListOverview(state = state, viewModel = viewModel)
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxWidth().weight(1f),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 24.dp),
            ) {
                item {
                    OutlinedTextField(
                        value = offerFilter,
                        onValueChange = { offerFilter = it.take(80) },
                        label = { Text("Angebote durchsuchen") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                item {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                        items(retailerOptions) { (id, name) ->
                            val count = if (id == "all") state.offers.size else retailerCounts[id] ?: 0
                            FilterChip(
                                selected = retailerFilter == id,
                                onClick = { retailerFilter = id },
                                label = { Text("$name · $count") },
                            )
                        }
                    }
                }
                if (availableLoyaltyPrograms.isNotEmpty()) {
                    item { Text("Bonusprogramme", style = MaterialTheme.typography.labelLarge) }
                    item {
                        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                            items(availableLoyaltyPrograms) { (id, label) ->
                                FilterChip(
                                    selected = id in state.selectedLoyaltyPrograms,
                                    onClick = { viewModel.toggleLoyaltyProgram(id) },
                                    label = { Text(label) },
                                )
                            }
                        }
                    }
                }
                item {
                    Box {
                        Button(onClick = { sortMenuOpen = true }) {
                            Text("Sortierung: ${when (sortMode) { "product" -> "Produktname"; "retailer" -> "Händler"; else -> "Preis" }}")
                        }
                        DropdownMenu(expanded = sortMenuOpen, onDismissRequest = { sortMenuOpen = false }) {
                            listOf("price" to "Preis", "retailer" to "Händler", "product" to "Produktname").forEach { (id, label) ->
                                DropdownMenuItem(text = { Text(label) }, onClick = { sortMode = id; sortMenuOpen = false })
                            }
                        }
                    }
                }
                item {
                    Text(
                        "${visibleOffers.size} Treffer · " + when (sortMode) {
                            "product" -> "nach Produktname sortiert"
                            "retailer" -> "nach Händler gruppiert"
                            else -> "nach Preis sortiert"
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                        Button(onClick = viewModel::refresh, enabled = !state.loading) {
                            if (state.loading) CircularProgressIndicator() else Text("Aktualisieren")
                        }
                        state.challengeUrl?.let { url ->
                            Button(onClick = { openChallenge(url) }) { Text("Händler bestätigen") }
                        }
                    }
                }
                item { Text(state.message) }
                items(visibleOffers, key = { it.offer.id }) { offer ->
                    Card(
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
                        shape = RoundedCornerShape(14.dp),
                        modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp),
                    ) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                                OfferThumbnail(offer.imagePath, offer.imageUrl, offer.offer.sourceUrl)
                                Column(modifier = Modifier.weight(1f)) {
                                    if (retailerFilter == "all") {
                                        Text(retailerNames[offer.offer.retailerId] ?: offer.offer.retailerId, color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold)
                                    }
                                    Text(offer.productName, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                                    offer.offer.categoryId?.takeIf { it.isNotBlank() }?.let { category ->
                                        Text(category, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                                    }
                                    offer.offer.basePriceCents?.let { base ->
                                        Text("Grundpreis ${base / 100},${(base % 100).toString().padStart(2, '0')} €", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                                    }
                                    offer.offer.loyaltyPriceCents?.takeIf {
                                        offer.offer.loyaltyProgram in state.selectedLoyaltyPrograms
                                    }?.let { loyaltyPrice ->
                                        Text(
                                            "Mit ${offer.offer.loyaltyLabel ?: "Kundenprogramm"}: " +
                                                "${loyaltyPrice / 100},${(loyaltyPrice % 100).toString().padStart(2, '0')} €",
                                            color = MaterialTheme.colorScheme.primary,
                                            style = MaterialTheme.typography.labelMedium,
                                            fontWeight = FontWeight.Bold,
                                        )
                                    }
                                }
                                Text(
                                    "${offer.offer.priceCents / 100},${(offer.offer.priceCents % 100).toString().padStart(2, '0')} €",
                                    style = MaterialTheme.typography.headlineSmall,
                                    fontWeight = FontWeight.Bold,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                                TextButton(onClick = { viewModel.addShoppingItem(offer.productName) }) { Text("Zur Einkaufsliste") }
                                if (state.kitchenTargets.isNotEmpty()) {
                                    TextButton(onClick = { viewModel.syncKitchenOwl(state.kitchenTargets.first()) }) { Text("Auf KitchenOwl") }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

internal fun effectivePriceCents(offer: OfferEntity, selectedPrograms: Set<String>): Int {
    val loyaltyPrice = offer.loyaltyPriceCents
    return if (offer.loyaltyProgram in selectedPrograms && loyaltyPrice != null) {
        minOf(offer.priceCents, loyaltyPrice)
    } else {
        offer.priceCents
    }
}

@Composable
private fun ShoppingListOverview(state: MainUiState, viewModel: MainViewModel) {
    var itemText by rememberSaveable { mutableStateOf("") }
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
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
        LazyColumn(modifier = Modifier.fillMaxWidth().heightIn(min = 80.dp, max = 360.dp)) {
            items(state.shoppingItems) { item ->
                Text("${item.quantity}× ${item.name}", modifier = Modifier.padding(vertical = 6.dp))
            }
        }
        if (state.shoppingItems.isEmpty()) {
            Text("Noch keine Artikel in der Einkaufsliste.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun OfferThumbnail(path: String?, url: String?, referer: String) {
    val context = LocalContext.current.applicationContext
    val cache = remember(context) { de.lesecuritae.korbuino.images.ImageCache.shared(context) }
    val bitmapState = remember { mutableStateOf<android.graphics.Bitmap?>(null) }
    LaunchedEffect(path, url, referer) {
        bitmapState.value = null
        bitmapState.value = cache.thumbnail(path, url, referer)
    }
    val bitmap = bitmapState.value
    Box(
        modifier = Modifier.size(68.dp).background(MaterialTheme.colorScheme.background, RoundedCornerShape(10.dp)),
        contentAlignment = androidx.compose.ui.Alignment.Center,
    ) {
        if (bitmap != null) Image(
            bitmap = bitmap.asImageBitmap(),
            contentDescription = null,
            contentScale = ContentScale.Fit,
            modifier = Modifier.size(62.dp).padding(3.dp),
        ) else Text("🛒", style = MaterialTheme.typography.titleLarge)
    }
}
