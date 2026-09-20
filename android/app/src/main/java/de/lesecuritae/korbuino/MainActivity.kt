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
import androidx.activity.enableEdgeToEdge
import androidx.core.content.ContextCompat
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.Image
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
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
import androidx.compose.runtime.mutableStateListOf
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
        enableEdgeToEdge()
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
    var crashReport by remember { mutableStateOf(CrashReporter.read(context)) }
    crashReport?.let { report ->
        androidx.compose.material3.AlertDialog(
            onDismissRequest = {},
            title = { Text("Korbuino ist abgestürzt") },
            text = {
                Column {
                    Text(
                        "Der Bericht enthält nur technische Angaben (Fehlermeldung, App-, Android- und Gerätetyp), " +
                            "keine Angebote und keine persönlichen Daten. Bitte kopiere ihn und schicke ihn mit, wenn du den Fehler meldest.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        report.take(1500),
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                        modifier = Modifier.heightIn(max = 220.dp).verticalScroll(rememberScrollState()),
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    val clipboard = context.getSystemService(android.content.ClipboardManager::class.java)
                    clipboard?.setPrimaryClip(android.content.ClipData.newPlainText("Korbuino Absturzbericht", report))
                    android.widget.Toast.makeText(context, "Bericht kopiert", android.widget.Toast.LENGTH_SHORT).show()
                }) { Text("Kopieren") }
            },
            dismissButton = {
                Row {
                    TextButton(onClick = {
                        val send = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
                            type = "text/plain"
                            putExtra(android.content.Intent.EXTRA_SUBJECT, "Korbuino Absturzbericht")
                            putExtra(android.content.Intent.EXTRA_TEXT, report)
                        }
                        context.startActivity(android.content.Intent.createChooser(send, "Bericht teilen").addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
                    }) { Text("Teilen") }
                    TextButton(onClick = { CrashReporter.clear(context); crashReport = null }) { Text("Verwerfen") }
                }
            },
        )
    }
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
          Box(modifier = Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing)) {
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
                val chosen = RetailerSelection.parse(state.retailerId, viewModel.retailers.map { it.first })
                androidx.compose.foundation.layout.Box {
                    Button(onClick = { menuOpen = true }) {
                        val names = viewModel.retailers.toMap()
                        Text("Händler: ${RetailerSelection.label(chosen, names, viewModel.retailers.map { it.first })}")
                    }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        // Hide retailers that had no offers for this postal code on the last load.
                        val hidden = if (state.postalCode == state.emptyRetailersPostal) state.emptyRetailers else emptySet()
                        viewModel.retailers.filter { (id, _) -> id == "all" || id in chosen || id !in hidden }.forEach { (id, name) ->
                            DropdownMenuItem(
                                text = { Text(name) },
                                leadingIcon = { Checkbox(checked = if (id == "all") chosen.isEmpty() else id in chosen, onCheckedChange = null) },
                                // The menu stays open so several retailers can be ticked in a row.
                                onClick = { viewModel.toggleRetailer(id) },
                            )
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
                ShoppingListOverview(state = state, viewModel = viewModel)
            }
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
    // Product groups are picked from a menu (several at once); nothing picked means all of them.
    var groupSelection by rememberSaveable { mutableStateOf(setOf<String>()) }
    var groupMenuOpen by remember { mutableStateOf(false) }
    val retailerNames = viewModel.retailers.toMap()
    // Only what the retailer menu selected is shown. Offers of earlier loads of other retailers stay
    // stored but do not turn up in the list or the search (in server mode the server decides).
    val menuSelection = RetailerSelection.parse(state.retailerId, viewModel.retailers.map { it.first })
    val shownOffers = remember(state.offers, menuSelection, state.serverMode) {
        if (menuSelection.isEmpty() || state.serverMode) state.offers
        else state.offers.filter { it.offer.retailerId in menuSelection }
    }
    val presentRetailerIds = shownOffers.map { it.offer.retailerId }.toSet()
    val retailerIds = viewModel.retailers.map { it.first }.filter { it != "all" && it in presentRetailerIds } +
        presentRetailerIds.filter { it !in retailerNames }.sorted()
    val retailerCounts = shownOffers.groupingBy { it.offer.retailerId }.eachCount()
    val retailerOptions = listOf("all" to "Alle Händler") + retailerIds.map { it to (retailerNames[it] ?: it) }
    val groupOf = remember(shownOffers) {
        shownOffers.associate { it.offer.id to ProductGroups.of(it.offer.categoryId, it.productName) }
    }
    // The product-group tabs count what the retailer chip and the text filter leave, but not the tab itself.
    val scopedOffers = shownOffers
        .filter { display -> retailerFilter == "all" || display.offer.retailerId == retailerFilter }
        .filter { display ->
            offerFilter.isBlank() || display.productName.contains(offerFilter, ignoreCase = true) ||
                display.offer.retailerId.contains(offerFilter, ignoreCase = true) ||
                display.offer.categoryId.orEmpty().contains(offerFilter, ignoreCase = true)
        }
    val groupCounts = scopedOffers.groupingBy { groupOf[it.offer.id] ?: ProductGroups.OTHER }.eachCount()
    val groupTabs = ProductGroups.ORDER.filter { it in groupCounts } + groupCounts.keys.filter { it !in ProductGroups.ORDER }.sorted()
    val activeGroups = groupSelection.filter { it in groupCounts }.toSet()
    val visibleOffers = scopedOffers
        .filter { display -> activeGroups.isEmpty() || (groupOf[display.offer.id] ?: ProductGroups.OTHER) in activeGroups }
        // The list is keyed by offer id; a repeated id would crash the list, so each offer shows once.
        .distinctBy { it.offer.id }
        .let { offers ->
            when (sortMode) {
                "product" -> offers.sortedWith(compareBy({ it.productName.lowercase() }, { retailerNames[it.offer.retailerId] ?: it.offer.retailerId }))
                "retailer" -> offers.sortedWith(compareBy(
                    { retailerIds.indexOf(it.offer.retailerId).takeIf { index -> index >= 0 } ?: Int.MAX_VALUE },
                    { effectivePriceCents(it.offer, state.selectedLoyaltyPrograms) },
                    { it.productName.lowercase() },
                ))
                "category" -> offers.sortedWith(compareBy(
                    { ProductGroups.rank(groupOf[it.offer.id] ?: ProductGroups.OTHER) },
                    { groupOf[it.offer.id] ?: ProductGroups.OTHER },
                    { effectivePriceCents(it.offer, state.selectedLoyaltyPrograms) },
                    { it.productName.lowercase() },
                ))
                else -> offers.sortedWith(compareBy({ effectivePriceCents(it.offer, state.selectedLoyaltyPrograms) }, { it.productName.lowercase() }))
            }
        }
    val availableLoyaltyPrograms = shownOffers.mapNotNull { display ->
        val id = display.offer.loyaltyProgram ?: return@mapNotNull null
        id to (display.offer.loyaltyLabel ?: id)
    }.distinctBy { it.first }.sortedBy { it.second }
    val listState = androidx.compose.foundation.lazy.rememberLazyListState()
    // Items in front of the offer rows: search, retailer chips, sort, count, refresh row, message (+ optional rows).
    val headerItems = 6 + (if (groupTabs.isNotEmpty()) 1 else 0) + (if (availableLoyaltyPrograms.isNotEmpty()) 2 else 0)
    // What the fast scroller shows for the row under its handle, depending on the sort.
    val scrollLabel: (Int) -> String = { index ->
        when (val row = visibleOffers.getOrNull(index)) {
            is OfferDisplay -> when (sortMode) {
                "product" -> row.productName.trim().firstOrNull()?.uppercaseChar()?.takeIf { it.isLetter() }?.toString() ?: "#"
                "retailer" -> retailerNames[row.offer.retailerId] ?: row.offer.retailerId
                "category" -> groupOf[row.offer.id] ?: ProductGroups.OTHER
                else -> effectivePriceCents(row.offer, state.selectedLoyaltyPrograms).let { "${it / 100},${(it % 100).toString().padStart(2, '0')} €" }
            }
            else -> ""
        }
    }
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
            "${shownOffers.size} Angebote · ${shownOffers.map { it.offer.retailerId }.distinct().size} Händler",
            style = MaterialTheme.typography.bodyMedium,
        )
        androidx.compose.material3.TabRow(selectedTabIndex = selectedTab) {
            androidx.compose.material3.Tab(selected = selectedTab == 0, onClick = { selectedTab = 0 }, text = { Text("Ergebnisse") })
            androidx.compose.material3.Tab(selected = selectedTab == 1, onClick = { selectedTab = 1 }, text = { Text("Einkauf") })
        }
        if (selectedTab == 1) {
            ShoppingListOverview(state = state, viewModel = viewModel)
        } else {
            Box(modifier = Modifier.fillMaxWidth().weight(1f)) {
            LazyColumn(
                state = listState,
                modifier = Modifier.fillMaxSize(),
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
                            val count = if (id == "all") shownOffers.size else retailerCounts[id] ?: 0
                            FilterChip(
                                selected = retailerFilter == id,
                                onClick = { retailerFilter = id },
                                label = { Text("$name · $count") },
                            )
                        }
                    }
                }
                if (groupTabs.isNotEmpty()) {
                    item {
                        Box {
                            Button(onClick = { groupMenuOpen = true }) {
                                Text("Warengruppen: " + when (activeGroups.size) {
                                    0 -> "Alle"
                                    1 -> activeGroups.first()
                                    else -> "${activeGroups.size} gewählt"
                                })
                            }
                            DropdownMenu(expanded = groupMenuOpen, onDismissRequest = { groupMenuOpen = false }) {
                                DropdownMenuItem(
                                    text = { Text("Alle Warengruppen · ${scopedOffers.size}") },
                                    leadingIcon = { Checkbox(checked = activeGroups.isEmpty(), onCheckedChange = null) },
                                    onClick = { groupSelection = emptySet() },
                                )
                                groupTabs.forEach { group ->
                                    DropdownMenuItem(
                                        text = { Text("$group · ${groupCounts[group] ?: 0}") },
                                        leadingIcon = { Checkbox(checked = group in activeGroups, onCheckedChange = null) },
                                        // The menu stays open so several groups can be ticked in a row.
                                        onClick = { groupSelection = if (group in activeGroups) activeGroups - group else activeGroups + group },
                                    )
                                }
                            }
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
                            Text("Sortierung: ${when (sortMode) { "product" -> "Produktname"; "retailer" -> "Händler"; "category" -> "Warengruppe"; else -> "Preis" }}")
                        }
                        DropdownMenu(expanded = sortMenuOpen, onDismissRequest = { sortMenuOpen = false }) {
                            listOf("price" to "Preis", "retailer" to "Händler", "category" to "Warengruppe", "product" to "Produktname").forEach { (id, label) ->
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
                            "category" -> "nach Warengruppe sortiert"
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
                                TextButton(onClick = { viewModel.addShoppingItem(offer.productName, retailerNames[offer.offer.retailerId] ?: offer.offer.retailerId) }) { Text("Zur Einkaufsliste") }
                                if (state.kitchenTargets.isNotEmpty()) {
                                    TextButton(onClick = { viewModel.syncKitchenOwl(state.kitchenTargets.first()) }) { Text("Auf KitchenOwl") }
                                }
                            }
                        }
                    }
                }
            }
            FastScroller(
                listState = listState,
                rowCount = visibleOffers.size,
                headerCount = headerItems,
                label = scrollLabel,
                modifier = Modifier.align(androidx.compose.ui.Alignment.CenterEnd),
            )
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
    var expanded by rememberSaveable { mutableStateOf(setOf<String>()) }
    val retailerNames = viewModel.retailers.toMap()
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
        state.removedShoppingItem?.let { removed ->
            Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("„${removed.name}“ entfernt.", modifier = Modifier.weight(1f))
                TextButton(onClick = viewModel::undoRemoveShoppingItem) { Text("Rückgängig") }
            }
        }
        state.shoppingItems.forEach { item ->
            val open = item.productId in expanded
            Column(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                Text(item.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                if (item.note.isNotBlank()) {
                    Text(
                        "Eingetragen bei ${item.note}",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = { expanded = if (open) expanded - item.productId else expanded + item.productId }) {
                        Text(if (open) "Angebote ausblenden" else "Im Angebot?")
                    }
                    TextButton(onClick = { viewModel.removeShoppingItem(item) }) { Text("Entfernen") }
                }
                if (open) {
                    val matches = OfferMatcher.matches(item.name, state.offers)
                    if (matches.isEmpty()) {
                        Text(
                            if (state.offers.isEmpty()) "Noch keine Angebote geladen."
                            else "Aktuell in keinem geladenen Angebot.",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        matches.take(8).forEach { match ->
                            Row(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        retailerNames[match.offer.retailerId] ?: match.offer.retailerId,
                                        color = MaterialTheme.colorScheme.primary,
                                        style = MaterialTheme.typography.labelMedium,
                                        fontWeight = FontWeight.Bold,
                                    )
                                    Text(match.productName, style = MaterialTheme.typography.bodyMedium)
                                }
                                Text(
                                    OfferMatcher.formatPrice(match.offer.priceCents),
                                    fontWeight = FontWeight.Bold,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }
                        if (matches.size > 8) Text("… und ${matches.size - 8} weitere", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
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
