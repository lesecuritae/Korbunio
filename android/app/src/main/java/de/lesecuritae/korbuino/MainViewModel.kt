package de.lesecuritae.korbuino

import androidx.room.withTransaction
import android.app.Application
import android.content.Intent
import android.net.Uri
import android.util.Log
import de.lesecuritae.korbuino.backup.BackupService
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.lesecuritae.korbuino.data.KorbuinoDatabase
import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import de.lesecuritae.korbuino.data.ShoppingListItemEntity
import de.lesecuritae.korbuino.data.FavoriteEntity
import de.lesecuritae.korbuino.notifications.NtfySettings
import de.lesecuritae.korbuino.notifications.NtfySender
import de.lesecuritae.korbuino.notifications.NativeWatchSync
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.util.UUID
import de.lesecuritae.korbuino.data.ShoppingListRow
import de.lesecuritae.korbuino.data.ProviderCacheEntity
import de.lesecuritae.korbuino.providers.NetworkClientFactory
import de.lesecuritae.korbuino.providers.ProviderRegistry
import de.lesecuritae.korbuino.providers.ProviderImportPolicy
import de.lesecuritae.korbuino.providers.RetailerRequest
import de.lesecuritae.korbuino.providers.RetailerProvider
import de.lesecuritae.korbuino.providers.ServerFallbackProvider
import de.lesecuritae.korbuino.providers.ServerProvider
import de.lesecuritae.korbuino.providers.fetchProviderBatch
import de.lesecuritae.korbuino.kitchenowl.KitchenOwlClient
import de.lesecuritae.korbuino.kitchenowl.KitchenOwlSyncPlan
import de.lesecuritae.korbuino.kitchenowl.KitchenOwlTarget
import de.lesecuritae.korbuino.security.SecureStore
import de.lesecuritae.korbuino.images.ProductImageProvider
import de.lesecuritae.korbuino.images.ImageCache
import de.lesecuritae.korbuino.update.UpdateInfo
import de.lesecuritae.korbuino.update.UpdateService
import de.lesecuritae.korbuino.work.BackgroundMode
import de.lesecuritae.korbuino.work.BackgroundScheduler
import de.lesecuritae.korbuino.work.BackgroundSettings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

private data class SyncResult(val added: Int, val removed: Int, val total: Int, val label: String)

data class MainUiState(
    val postalCode: String = "",
    val city: String = "",
    val retailerId: String = "all",
    val loading: Boolean = false,
    val offers: List<OfferDisplay> = emptyList(),
    val shoppingItems: List<ShoppingListRow> = emptyList(),
    val removedShoppingItem: ShoppingListRow? = null,
    val favorites: List<FavoriteEntity> = emptyList(),
    val ntfySettings: NtfySettings = NtfySettings(),
    /** Retailers that answered without offers for [emptyRetailersPostal]; hidden in the picker for that code. */
    val emptyRetailers: Set<String> = emptySet(),
    val emptyRetailersPostal: String = "",
    val kitchenOwlUrl: String = "",
    val kitchenConnecting: Boolean = false,
    val kitchenTargets: List<KitchenOwlTarget> = emptyList(),
    val update: UpdateInfo? = null,
    val dailySync: Boolean = false,
    val message: String = "Noch keine Angebote geladen",
    val challengeUrl: String? = null,
    val serverUrl: String = "",
    val serverToken: String = "",
    val serverMode: Boolean = false,
    val selectedLoyaltyPrograms: Set<String> = emptySet(),
)

data class OfferDisplay(
    val offer: OfferEntity,
    val productName: String,
    val imagePath: String? = null,
    val imageUrl: String? = null,
)

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val database = KorbuinoDatabase.create(application)
    private val registry = ProviderRegistry.default(NetworkClientFactory.create(application))
    private val _state = MutableStateFlow(MainUiState())
    private val secureStore = SecureStore(application)
    private val imageProvider = ProductImageProvider(NetworkClientFactory.create(application))
    private val imageCache = ImageCache.shared(application)
    val state: StateFlow<MainUiState> = _state.asStateFlow()

    val retailers = listOf("all" to "Alle Händler") + registry.all().map { it.id to it.displayName }

    init {
        viewModelScope.launch {
            val saved = withContext(Dispatchers.IO) {
                database.offerDao().deleteProvider("marktguru-combi")
                database.providerDao().delete("marktguru-combi")
                val savedRetailer = secureStore.get("retailer_id") ?: "all"
                if (savedRetailer == "marktguru-combi") secureStore.put("retailer_id", "all")
                Triple(
                    secureStore.get("postal_code").orEmpty(),
                    secureStore.get("city").orEmpty(),
                    RetailerSelection.format(RetailerSelection.parse(savedRetailer, retailers.map { it.first })),
                )
            }
            _state.value = _state.value.copy(
                ntfySettings = secureStore.loadNtfySettings(),
                postalCode = saved.first,
                city = saved.second,
                retailerId = saved.third,
                dailySync = secureStore.get("daily_sync") == "true",
                serverUrl = secureStore.get("server_url").orEmpty(),
                serverToken = secureStore.get("server_token").orEmpty(),
                serverMode = secureStore.get("server_mode") == "true",
                kitchenOwlUrl = secureStore.get("kitchenowl_url").orEmpty(),
                emptyRetailers = secureStore.get("empty_retailers").orEmpty().split(',').filter(String::isNotBlank).toSet(),
                emptyRetailersPostal = secureStore.get("empty_retailers_postal").orEmpty(),
                selectedLoyaltyPrograms = secureStore.get("loyalty_programs")
                    .orEmpty().split(',').filter(String::isNotBlank).toSet(),
            )
            // Match the established KorbKlar flow: with a stored location,
            // the complete offer overview starts loading as soon as the app
            // opens. The user can still start it manually after changing the
            // location.
            if (saved.first.length == 5) refresh()
            if (_state.value.dailySync) {
                BackgroundScheduler.apply(
                    getApplication(), BackgroundSettings(mode = BackgroundMode.DAILY),
                    saved.first, saved.second, saved.third,
                )
            }
        }
        viewModelScope.launch {
            database.favoriteDao().observeAll().collect { values -> _state.value = _state.value.copy(favorites = values) }
        }
        viewModelScope.launch {
            database.offerDao().observeAll().collect { offers ->
                rebuildOfferDisplay(offers)
            }
        }
        viewModelScope.launch {
            database.shoppingListDao().observeDefault().collect { items ->
                _state.value = _state.value.copy(shoppingItems = items)
            }
        }
    }

    private fun itemEntity(item: ShoppingListRow, quantity: Int = item.quantity, checked: Boolean = item.checked,
                           retailerId: String? = item.retailerId, offerId: String? = item.offerId) =
        ShoppingListItemEntity("default", item.productId, quantity, checked, item.note, item.itemId, retailerId, offerId)

    fun shoppingQuantity(item: ShoppingListRow, quantity: Int) {
        if (quantity !in 1..999) return
        viewModelScope.launch { database.shoppingListDao().upsertAll(listOf(itemEntity(item, quantity = quantity))) }
    }

    fun shoppingChecked(item: ShoppingListRow, checked: Boolean) {
        viewModelScope.launch { database.shoppingListDao().upsertAll(listOf(itemEntity(item, checked = checked))) }
    }

    fun selectShoppingOffer(item: ShoppingListRow, offer: OfferDisplay?) {
        viewModelScope.launch {
            database.shoppingListDao().upsertAll(listOf(itemEntity(item, retailerId = offer?.offer?.retailerId, offerId = offer?.offer?.id)))
        }
    }

    fun addOfferToShoppingList(display: OfferDisplay) {
        viewModelScope.launch {
            val itemId = "offer:${display.offer.retailerId}:${display.offer.id}"
            val existing = database.shoppingListDao().allItems().firstOrNull { it.listId == "default" && it.itemId == itemId }
            database.shoppingListDao().upsertAll(listOf(existing?.copy(quantity = (existing.quantity + 1).coerceAtMost(999), checked = false)
                ?: ShoppingListItemEntity("default", display.offer.productId, itemId = itemId,
                    retailerId = display.offer.retailerId, offerId = display.offer.id)))
            _state.value = _state.value.copy(message = "Zur Einkaufsliste hinzugefügt")
        }
    }

    fun saveFavorite(query: String, retailerIds: Set<String>, maxPriceCents: Int?, currentWeek: Boolean,
                     nextWeek: Boolean, notifications: Boolean, existingId: String? = null) {
        val clean = query.trim().take(120)
        if (clean.isBlank() || (maxPriceCents != null && maxPriceCents <= 0) || (!currentWeek && !nextWeek)) {
            message("Suchbegriff, Preis und mindestens einen Wochenbereich prüfen")
            return
        }
        val known = retailers.map { it.first }.filterNot { it == "all" }.toSet()
        if (!known.containsAll(retailerIds)) { message("Unbekannte Händlerauswahl"); return }
        viewModelScope.launch {
            val previous = _state.value.favorites.firstOrNull { it.productId == existingId }
            database.favoriteDao().upsert(FavoriteEntity(existingId ?: UUID.randomUUID().toString(),
                previous?.createdAt ?: System.currentTimeMillis(), clean, Json.encodeToString(retailerIds.sorted()),
                maxPriceCents, currentWeek, nextWeek, notifications, _state.value.postalCode))
            message("Favorit gespeichert. Meldungen benötigen zusätzlich eine aktivierte ntfy-Verbindung.")
        }
    }

    fun removeFavorite(favorite: FavoriteEntity) {
        viewModelScope.launch { database.favoriteDao().remove(favorite.productId) }
    }

    fun saveNtfy(settings: NtfySettings) {
        NtfySender.validationError(settings)?.let { message(it); return }
        // Topic and token live exclusively in the existing encrypted preferences.
        secureStore.saveNtfySettings(settings)
        _state.value = _state.value.copy(ntfySettings = settings,
            message = "ntfy-Einstellungen gespeichert; die Hintergrundaktualisierung bleibt unverändert")
    }

    fun testNtfy(settings: NtfySettings) {
        viewModelScope.launch {
            val result = NtfySender(NetworkClientFactory.create(getApplication())).test(settings)
            message(result.message)
        }
    }

    fun postalCode(value: String) {
        val clean = value.filter(Char::isDigit).take(5)
        _state.value = _state.value.copy(postalCode = clean)
        secureStore.put("postal_code", clean)
    }
    fun city(value: String) {
        val clean = value.take(60)
        _state.value = _state.value.copy(city = clean)
        secureStore.put("city", clean)
    }

    fun message(value: String) { _state.value = _state.value.copy(message = value) }

    fun serverUrl(value: String) { val clean = value.trim().take(240); _state.value = _state.value.copy(serverUrl = clean); secureStore.put("server_url", clean) }
    fun serverToken(value: String) { val clean = value.trim().take(500); _state.value = _state.value.copy(serverToken = clean); secureStore.put("server_token", clean) }
    fun setServerMode(enabled: Boolean) { _state.value = _state.value.copy(serverMode = enabled); secureStore.put("server_mode", enabled.toString()) }
    fun selectedRetailers(): Set<String> = RetailerSelection.parse(_state.value.retailerId, retailers.map { it.first })

    /** Adds or removes a retailer from the choice; "all" clears it. */
    fun toggleRetailer(id: String) {
        if (retailers.none { it.first == id }) return
        val value = RetailerSelection.format(RetailerSelection.toggle(selectedRetailers(), id))
        _state.value = _state.value.copy(retailerId = value)
        secureStore.put("retailer_id", value)
    }

    fun toggleLoyaltyProgram(program: String) {
        val selected = _state.value.selectedLoyaltyPrograms.toMutableSet()
        if (!selected.add(program)) selected.remove(program)
        _state.value = _state.value.copy(selectedLoyaltyPrograms = selected)
        secureStore.put("loyalty_programs", selected.sorted().joinToString(","))
    }

    fun setDailySync(enabled: Boolean) {
        val current = _state.value
        _state.value = current.copy(dailySync = enabled)
        secureStore.put("daily_sync", enabled.toString())
        BackgroundScheduler.apply(
            getApplication(), BackgroundSettings(mode = if (enabled) BackgroundMode.DAILY else BackgroundMode.MANUAL),
            current.postalCode, current.city, current.retailerId,
        )
        _state.value = _state.value.copy(message = if (enabled) "Tägliche Aktualisierung aktiviert" else "Automatische Aktualisierung deaktiviert")
    }

    fun addShoppingItem(name: String, retailer: String = "") {
        val clean = name.trim().take(120)
        if (clean.isBlank()) return
        viewModelScope.launch {
            // Product wishes have their own identity. Free notes are never retailer IDs.
            val existing = _state.value.shoppingItems.firstOrNull {
                it.name.equals(clean, ignoreCase = true) && it.retailerId == null &&
                    it.offerId == null && !it.checked && it.note == retailer.take(60)
            }
            if (existing != null) {
                database.shoppingListDao().upsertAll(listOf(itemEntity(existing, quantity = (existing.quantity + 1).coerceAtMost(999))))
            } else {
                val id = "manual:" + UUID.randomUUID().toString()
                database.productDao().upsertAll(listOf(ProductEntity(id, clean, normalizedKey = id)))
                database.shoppingListDao().upsertAll(listOf(ShoppingListItemEntity("default", id, note = retailer.take(60))))
            }
        }
    }

    fun removeShoppingItem(item: ShoppingListRow) {
        viewModelScope.launch {
            database.shoppingListDao().remove(item.itemId)
            _state.value = _state.value.copy(removedShoppingItem = item)
        }
    }

    fun undoRemoveShoppingItem() {
        val item = _state.value.removedShoppingItem ?: return
        viewModelScope.launch {
            database.shoppingListDao().upsertAll(
                listOf(itemEntity(item)),
            )
            _state.value = _state.value.copy(removedShoppingItem = null)
        }
    }

    fun kitchenOwlUrl(value: String) { _state.value = _state.value.copy(kitchenOwlUrl = value.take(200)) }

    fun checkUpdate() {
        if (!BuildConfig.ENABLE_SELF_UPDATE) return
        viewModelScope.launch {
            _state.value = _state.value.copy(message = "Nach Updates wird gesucht …")
            runCatching { withContext(Dispatchers.IO) { UpdateService(getApplication()).check() } }
                .onSuccess { update ->
                    _state.value = _state.value.copy(update = update, message = update?.let { "Update ${it.version} verfügbar" } ?: "Kein Update verfügbar")
                }
                .onFailure { error -> _state.value = _state.value.copy(message = "Updateprüfung: ${error.message}") }
        }
    }

    fun installUpdate(info: UpdateInfo, start: (Intent) -> Unit) {
        if (!BuildConfig.ENABLE_SELF_UPDATE) return
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, message = "Update wird geladen …")
            runCatching {
                val service = UpdateService(getApplication())
                withContext(Dispatchers.IO) { service.install(service.download(info)) }
            }.onSuccess { intent ->
                _state.value = _state.value.copy(loading = false, message = "Installationsdialog wird geöffnet")
                start(intent)
            }.onFailure { error -> _state.value = _state.value.copy(loading = false, message = "Update: ${error.message}") }
        }
    }

    fun exportBackup(uri: Uri) {
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    getApplication<Application>().contentResolver.openOutputStream(uri)?.use { BackupService(getApplication()).export(it) }
                        ?: error("Backup-Ziel konnte nicht geöffnet werden")
                }
            }.onSuccess { _state.value = _state.value.copy(message = "Backup gespeichert") }
                .onFailure { error -> _state.value = _state.value.copy(message = "Backup: ${error.message}") }
        }
    }

    fun importBackup(uri: Uri) {
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    getApplication<Application>().contentResolver.openInputStream(uri)?.use { BackupService(getApplication()).import(it) }
                        ?: error("Backup konnte nicht geöffnet werden")
                }
            }.onSuccess { _state.value = _state.value.copy(message = "Backup importiert") }
                .onFailure { error -> _state.value = _state.value.copy(message = "Backup: ${error.message}") }
        }
    }

    fun connectKitchenOwl(url: String, token: String) = connectKitchenOwlWith(url) { token.trim() }

    fun loginKitchenOwl(url: String, username: String, password: String) = connectKitchenOwlWith(url) {
        KitchenOwlClient.login(url.trim(), username, password)
    }

    private fun connectKitchenOwlWith(url: String, getToken: () -> String) {
        if (_state.value.kitchenConnecting) return
        _state.value = _state.value.copy(kitchenConnecting = true, message = "KitchenOwl wird geprüft …")
        viewModelScope.launch {
            runCatching {
                val (token, targets) = withContext(Dispatchers.IO) {
                    val token = getToken()
                    token to KitchenOwlClient(url.trim(), token).targets()
                }
                secureStore.put("kitchenowl_url", url.trim())
                secureStore.put("kitchenowl_token", token)
                targets
            }.onSuccess { targets ->
                _state.value = _state.value.copy(kitchenOwlUrl = url.trim(), kitchenTargets = targets, message = "${targets.size} KitchenOwl-Liste(n) verbunden")
            }.onFailure { error -> _state.value = _state.value.copy(message = "KitchenOwl: ${error.message}") }
            _state.value = _state.value.copy(kitchenConnecting = false)
        }
    }

    fun syncKitchenOwl(target: KitchenOwlTarget) {
        viewModelScope.launch {
            val url = secureStore.get("kitchenowl_url") ?: return@launch
            val token = secureStore.get("kitchenowl_token") ?: return@launch
            runCatching {
                val client = KitchenOwlClient(url, token)
                withContext(Dispatchers.IO) {
                    // Idempotent: nothing is added twice, and articles removed from the Korbuino list are
                    // removed again in KitchenOwl, but only ones Korbuino put there itself.
                    val remote = client.itemIds(target.id)
                    val notes = LinkedHashMap<String, Pair<String, String>>()
                    database.shoppingListDao().allItems().forEach { item ->
                        val product = database.productDao().find(listOf(item.productId)).firstOrNull()
                        val name = product?.name?.trim().orEmpty()
                        if (name.isBlank()) return@forEach
                        val retailer = item.retailerId?.let { id -> retailers.toMap()[id] ?: id }
                        val offer = item.offerId?.let { id -> database.offerDao().all().firstOrNull { it.id == id } }
                        val displayName = "${item.quantity}× $name" + retailer?.let { " ($it)" }.orEmpty() +
                            offer?.packSize?.let { " · $it" }.orEmpty()
                        val note = listOfNotNull(item.note.takeIf { it.isNotBlank() },
                            offer?.let { offerPriceLabel(OfferDisplay(it, name), _state.value.selectedLoyaltyPrograms) }).joinToString(" · ")
                        notes.putIfAbsent(displayName.lowercase(), displayName to note)
                    }
                    val syncedKey = "kitchenowl_synced_${target.id}"
                    val previous = secureStore.get(syncedKey).orEmpty().split('\n').filter(String::isNotBlank).toSet()
                    val plan = KitchenOwlSyncPlan.plan(notes.keys, previous, remote.keys)
                    plan.toAdd.forEach { key -> notes.getValue(key).let { (name, note) -> client.addItem(target.id, name, note) } }
                    plan.toRemove.forEach { key -> remote[key]?.let { client.removeItem(target.id, it) } }
                    secureStore.put(syncedKey, plan.nowSynced.joinToString("\n"))
                    val added = plan.toAdd.size
                    val total = notes.size
                    SyncResult(added, plan.toRemove.size, total, target.label)
                }
            }.onSuccess { (added, removed, total, label) ->
                _state.value = _state.value.copy(
                    message = when {
                        total == 0 && removed == 0 -> "Die Einkaufsliste ist leer, nichts zu übertragen"
                        added == 0 && removed == 0 -> "Alle $total Artikel sind schon auf $label"
                        else -> listOfNotNull("$added Artikel zu $label übertragen".takeIf { added > 0 }, "$removed entfernt".takeIf { removed > 0 }).joinToString(", ")
                    },
                )
            }
                .onFailure { error -> _state.value = _state.value.copy(message = "KitchenOwl-Sync: ${error.message}") }
        }
    }

    fun refresh() {
        val current = _state.value
        if (current.loading) return
        if (current.postalCode.length != 5) {
            _state.value = current.copy(message = "Eine gültige fünfstellige PLZ eingeben")
            return
        }
        // Mark the request in flight before launching so an automatic startup
        // refresh and a tap cannot start two full batches together.
        _state.value = current.copy(loading = true, challengeUrl = null)
        viewModelScope.launch {
            val serverToken = secureStore.get("server_token").orEmpty()
            val http = NetworkClientFactory.create(getApplication())
            val providers = if (current.serverMode && current.serverUrl.isNotBlank()) {
                listOf(ServerProvider(current.serverUrl, serverToken, http))
            } else {
                val chosen = selectedRetailers()
                val direct = if (chosen.isEmpty()) registry.all() else chosen.mapNotNull(registry::byId)
                // With a server address set, blocked retailers (403) are retried through the server.
                if (current.serverUrl.isBlank()) direct else direct.map { provider ->
                    ServerFallbackProvider(
                        provider,
                        ServerProvider(current.serverUrl, serverToken, http, provider.serverName(), provider.id),
                    )
                }
            }
            if (providers.isEmpty()) {
                _state.value = _state.value.copy(loading = false, message = "Kein Händler ausgewählt")
                return@launch
            }
            val label = if (providers.size == 1) providers.single().displayName else "${providers.size} Händler"
            _state.value = _state.value.copy(loading = true, challengeUrl = null, message = "$label-Angebote werden direkt geladen …")
            val fetched = fetchProviderBatch(providers, RetailerRequest(current.postalCode, citySlug = current.city))
            if (!current.serverMode) rememberEmptyRetailers(current.postalCode, fetched)
            val successes = mutableListOf<Pair<de.lesecuritae.korbuino.providers.RetailerProvider, de.lesecuritae.korbuino.providers.ProviderResult>>()
            var emptySources = 0
            var rejectedSources = 0
            var failedSources = 0
            if (_state.value.postalCode != current.postalCode) {
                _state.value = _state.value.copy(loading = false, message = "PLZ geändert. Bitte Angebote erneut laden.")
                return@launch
            }
            fetched.forEach { (provider, result) ->
                val previous = database.providerDao().get(provider.id)
                result.onSuccess { value ->
                    val rejection = ProviderImportPolicy.rejectionReason(provider.id, value, previous?.offerCount ?: 0)
                    if (rejection == null) {
                        successes += provider to value
                    } else if (value.offers.isEmpty()) {
                        emptySources++
                    } else {
                        rejectedSources++
                    }
                    database.providerDao().upsert(
                        ProviderCacheEntity(
                            providerId = provider.id,
                            lastSuccess = if (rejection == null) System.currentTimeMillis() else previous?.lastSuccess,
                            lastFailure = if (rejection == null || value.offers.isEmpty()) previous?.lastFailure else System.currentTimeMillis(),
                            lastError = rejection,
                            offerCount = if (rejection == null) value.offers.size else previous?.offerCount ?: 0,
                            retailerReachable = true,
                            sourceReachable = true,
                            offersAvailable = value.offers.isNotEmpty(),
                            imagesAvailable = value.offers.any { !it.imageUrl.isNullOrBlank() },
                            parserOk = true,
                        ),
                    )
                }.onFailure { error ->
                    failedSources++
                    val safeDiagnostic = generateSequence(error) { it.cause }
                        .joinToString(" <- ") { cause ->
                            "${cause.javaClass.simpleName}: ${cause.message.orEmpty()}"
                        }.take(320)
                    Log.w("KorbuinoProvider", "${provider.id}: $safeDiagnostic")
                    val detail = generateSequence(error) { it.cause }.joinToString(" ") { it.message.orEmpty() }.lowercase()
                    val parserFailure = listOf("parse", "format", "json", "angebotsblock", "daten fehlen").any(detail::contains)
                    val transportFailure = listOf("timeout", "timed out", "unable to resolve", "failed to connect", "ssl", "certificate").any(detail::contains)
                    database.providerDao().upsert(
                        ProviderCacheEntity(
                            providerId = provider.id,
                            lastSuccess = previous?.lastSuccess,
                            lastFailure = System.currentTimeMillis(),
                            lastError = error.message.orEmpty().ifBlank { error.javaClass.simpleName }.take(160),
                            offerCount = previous?.offerCount ?: 0,
                            retailerReachable = !transportFailure,
                            sourceReachable = false,
                            offersAvailable = false,
                            imagesAvailable = previous?.imagesAvailable ?: false,
                            parserOk = !parserFailure,
                        ),
                    )
                }
            }
            if (successes.isNotEmpty()) {
                // Products are shared across retailers. Canonicalising by the
                // Room normalized key prevents a multi-retailer refresh from
                // violating the unique product index while retaining every
                // retailer offer through a stable product reference.
                val imported = database.withTransaction {
                    if (secureStore.get("postal_code") != current.postalCode) return@withTransaction null
                    val rawProducts = successes.flatMap { it.second.products }
                    val canonicalProducts = LinkedHashMap<String, ProductEntity>()
                    database.productDao().all().forEach { canonicalProducts.putIfAbsent(it.normalizedKey, it) }
                    rawProducts.forEach { product -> canonicalProducts.putIfAbsent(product.normalizedKey, product) }
                    val productIds = rawProducts.associate { it.id to canonicalProducts.getValue(it.normalizedKey).id }
                    val products = rawProducts.map { canonicalProducts.getValue(it.normalizedKey) }.distinctBy { it.id }
                    val offers = successes.flatMap { it.second.offers }.map { offer ->
                        productIds[offer.productId]?.let { canonicalId -> offer.copy(productId = canonicalId) } ?: offer
                    }.distinctBy { it.id }
                    database.productDao().upsertAll(products)
                    val previousOfferPostal = secureStore.get("offer_postal_code").orEmpty()
                    if (previousOfferPostal.isNotBlank() && previousOfferPostal != current.postalCode) {
                        database.offerDao().deleteAll()
                    }
                    database.offerDao().storeRefresh(offers, successes.flatMap { it.second.unavailableRetailers(it.first.id) })
                    products to offers
                }
                if (imported == null) {
                    _state.value = _state.value.copy(loading = false, message = "PLZ geändert. Bitte Angebote erneut laden.")
                    return@launch
                }
                val (products, offers) = imported
                secureStore.put("offer_postal_code", current.postalCode)
                NativeWatchSync.afterSuccessfulSync(database, secureStore, providers, current.postalCode, current.city, http)
                // Cards download their first-party image on demand. Optional
                // GTIN enrichment remains a background task and must never
                // hold the offer overview behind dozens of image requests.
                viewModelScope.launch(Dispatchers.IO) {
                    val knownImages = database.imageDao().find(products.map { it.id }).map { it.productId }.toSet()
                    products.filter { !it.gtin.isNullOrBlank() && it.id !in knownImages }.take(40).forEach { product ->
                        runCatching {
                            imageProvider.find(product.id, product.gtin, product.name, product.brand, "", "multi")
                        }.getOrNull()?.let { image ->
                            database.imageDao().upsert(image)
                            imageCache.download(image.imageUrl)
                        }
                    }
                    rebuildOfferDisplay(database.offerDao().all())
                }
                val challenge = fetched.firstNotNullOfOrNull { (provider, result) ->
                    result.exceptionOrNull()?.let { error -> provider.challengeUrl?.takeIf { isChallengeError(error) } }
                }
                _state.value = _state.value.copy(
                    loading = false,
                    challengeUrl = challenge,
                    message = buildString {
                        append("${offers.size} Angebote von ${successes.size} Quellen gespeichert")
                        if (emptySources > 0) append(" · $emptySources ohne aktuelle Angebote")
                        if (rejectedSources > 0) append(" · $rejectedSources wegen Datenqualität verworfen")
                        if (failedSources > 0) {
                            append(" · $failedSources Abruffehler")
                            fetched.firstOrNull { it.second.isFailure }?.let { (provider, result) ->
                                val error = result.exceptionOrNull()!!
                                append("\n${provider.displayName}: ${(error.message ?: error.javaClass.simpleName).take(160)}")
                            }
                        }
                    },
                )
            } else {
                val challenge = fetched.firstNotNullOfOrNull { (provider, result) ->
                    result.exceptionOrNull()?.let { error -> provider.challengeUrl?.takeIf { isChallengeError(error) } }
                }
                val error = fetched.firstNotNullOfOrNull { it.second.exceptionOrNull() }
                _state.value = _state.value.copy(
                    loading = false,
                    challengeUrl = challenge,
                    message = when {
                        challenge != null -> "Händler-Bestätigung erforderlich"
                        error != null -> "Offline/Fehler: ${error.message ?: error.javaClass.simpleName}"
                        rejectedSources > 0 && emptySources == 0 -> "Angebote wegen Datenqualität verworfen"
                        // Every source answered, none had offers: not a network problem.
                        else -> "Keine aktuellen Angebote für PLZ ${current.postalCode} gefunden (z. B. kein Markt in der Nähe)"
                    },
                )
            }
        }
    }

    /** Remembers which retailers answered without offers for this postal code, so the picker can hide them. */
    private fun rememberEmptyRetailers(
        postalCode: String,
        fetched: List<Pair<RetailerProvider, Result<de.lesecuritae.korbuino.providers.ProviderResult>>>,
    ) {
        val answered = fetched.filter { it.second.isSuccess }
        val empty = answered.filter { it.second.getOrNull()?.offers?.isEmpty() == true }.map { it.first.id }
        val kept = if (_state.value.emptyRetailersPostal == postalCode) {
            // A failed retry no longer confirms an older empty result. Keep
            // the retailer selectable so browser confirmation/retry is possible.
            _state.value.emptyRetailers - fetched.map { it.first.id }.toSet()
        } else emptySet()
        val merged = kept + empty
        secureStore.put("empty_retailers", merged.sorted().joinToString(","))
        secureStore.put("empty_retailers_postal", postalCode)
        _state.value = _state.value.copy(emptyRetailers = merged, emptyRetailersPostal = postalCode)
    }

    private fun isChallengeError(error: Throwable): Boolean = ServerFallbackProvider.isBlocked(error)

    /** The regional suffix is only shown in the app; the server knows the plain retailer name. */
    private fun RetailerProvider.serverName(): String = displayName.removeSuffix(" (regional)")

    private suspend fun rebuildOfferDisplay(offers: List<OfferEntity>) {
        val products = withContext(Dispatchers.IO) {
            database.productDao().find(offers.map { it.productId }).associateBy { it.id }
        }
        val images = withContext(Dispatchers.IO) {
            database.imageDao().find(offers.map { it.productId }).associateBy { it.productId }
        }
        val display = withContext(Dispatchers.IO) {
            offers.map { offer ->
                val imageUrl = offer.imageUrl?.takeIf { it.isNotBlank() }
                    ?: images[offer.productId]?.imageUrl?.takeIf { it.isNotBlank() }
                OfferDisplay(
                    offer = offer,
                    productName = products[offer.productId]?.name ?: offer.productId,
                    imagePath = imageUrl?.let { imageCache.get(it, Long.MAX_VALUE)?.path },
                    imageUrl = imageUrl,
                )
            }
        }
        _state.value = _state.value.copy(offers = display)
    }

    override fun onCleared() { database.close(); super.onCleared() }
}
