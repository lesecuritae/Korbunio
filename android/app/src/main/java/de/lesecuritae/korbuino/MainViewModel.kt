package de.lesecuritae.korbuino

import android.app.Application
import android.content.Intent
import android.net.Uri
import de.lesecuritae.korbuino.backup.BackupService
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.lesecuritae.korbuino.data.KorbuinoDatabase
import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import de.lesecuritae.korbuino.data.ShoppingListItemEntity
import de.lesecuritae.korbuino.data.ShoppingListRow
import de.lesecuritae.korbuino.data.ProviderCacheEntity
import de.lesecuritae.korbuino.providers.NetworkClientFactory
import de.lesecuritae.korbuino.providers.ProviderRegistry
import de.lesecuritae.korbuino.providers.RetailerRequest
import de.lesecuritae.korbuino.kitchenowl.KitchenOwlClient
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

data class MainUiState(
    val postalCode: String = "",
    val city: String = "",
    val retailerId: String = "rewe",
    val loading: Boolean = false,
    val offers: List<OfferEntity> = emptyList(),
    val shoppingItems: List<ShoppingListRow> = emptyList(),
    val kitchenOwlUrl: String = "",
    val kitchenTargets: List<KitchenOwlTarget> = emptyList(),
    val update: UpdateInfo? = null,
    val dailySync: Boolean = false,
    val message: String = "Noch keine Angebote geladen",
)

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val database = KorbuinoDatabase.create(application)
    private val registry = ProviderRegistry.default(NetworkClientFactory.create(application))
    private val _state = MutableStateFlow(MainUiState())
    private val secureStore = SecureStore(application)
    private val imageProvider = ProductImageProvider(NetworkClientFactory.create(application))
    private val imageCache = ImageCache(application, NetworkClientFactory.create(application))
    val state: StateFlow<MainUiState> = _state.asStateFlow()

    val retailers = registry.all().map { it.id to it.displayName }

    init {
        viewModelScope.launch {
            val saved = withContext(Dispatchers.IO) {
                Triple(secureStore.get("postal_code").orEmpty(), secureStore.get("city").orEmpty(), secureStore.get("retailer_id") ?: "rewe")
            }
            _state.value = _state.value.copy(postalCode = saved.first, city = saved.second, retailerId = saved.third, dailySync = secureStore.get("daily_sync") == "true")
            if (_state.value.dailySync) {
                BackgroundScheduler.apply(
                    getApplication(), BackgroundSettings(mode = BackgroundMode.DAILY),
                    saved.first, saved.second, saved.third,
                )
            }
        }
        viewModelScope.launch {
            database.offerDao().observeAll().collect { offers ->
                _state.value = _state.value.copy(offers = offers)
            }
        }
        viewModelScope.launch {
            database.shoppingListDao().observeDefault().collect { items ->
                _state.value = _state.value.copy(shoppingItems = items)
            }
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
    fun retailer(value: String) {
        if (retailers.any { it.first == value }) {
            _state.value = _state.value.copy(retailerId = value)
            secureStore.put("retailer_id", value)
        }
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

    fun addShoppingItem(name: String) {
        val clean = name.trim().take(120)
        if (clean.isBlank()) return
        viewModelScope.launch {
            val id = "manual:" + clean.lowercase().replace("[^a-z0-9]+".toRegex(), "-")
            database.productDao().upsertAll(listOf(ProductEntity(id, clean, normalizedKey = id)))
            database.shoppingListDao().upsertAll(listOf(ShoppingListItemEntity("default", id)))
        }
    }

    fun kitchenOwlUrl(value: String) { _state.value = _state.value.copy(kitchenOwlUrl = value.take(200)) }

    fun checkUpdate() {
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

    fun connectKitchenOwl(url: String, token: String) {
        viewModelScope.launch {
            _state.value = _state.value.copy(message = "KitchenOwl wird geprüft …")
            runCatching {
                val targets = withContext(Dispatchers.IO) { KitchenOwlClient(url.trim(), token.trim()).targets() }
                secureStore.put("kitchenowl_url", url.trim())
                secureStore.put("kitchenowl_token", token.trim())
                targets
            }.onSuccess { targets ->
                _state.value = _state.value.copy(kitchenOwlUrl = url.trim(), kitchenTargets = targets, message = "${targets.size} KitchenOwl-Liste(n) verbunden")
            }.onFailure { error -> _state.value = _state.value.copy(message = "KitchenOwl: ${error.message}") }
        }
    }

    fun syncKitchenOwl(target: KitchenOwlTarget) {
        viewModelScope.launch {
            val url = secureStore.get("kitchenowl_url") ?: return@launch
            val token = secureStore.get("kitchenowl_token") ?: return@launch
            runCatching {
                val client = KitchenOwlClient(url, token)
                withContext(Dispatchers.IO) {
                    // KitchenOwl synchronisation is intentionally idempotent:
                    // do not add an article that is already on the target list.
                    val existing = client.existingItems(target.id).map { it.trim().lowercase() }.toMutableSet()
                    database.shoppingListDao().allItems().forEach { item ->
                        val product = database.productDao().find(listOf(item.productId)).firstOrNull()
                        val name = product?.name?.trim().orEmpty()
                        if (name.isNotBlank() && existing.add(name.lowercase())) {
                            client.addItem(target.id, name, "Menge: ${item.quantity}")
                        }
                    }
                }
            }.onSuccess { _state.value = _state.value.copy(message = "Einkaufsliste zu ${target.label} übertragen") }
                .onFailure { error -> _state.value = _state.value.copy(message = "KitchenOwl-Sync: ${error.message}") }
        }
    }

    fun refresh() {
        val current = _state.value
        if (current.postalCode.length != 5 || current.city.isBlank()) {
            _state.value = current.copy(message = "PLZ und Stadt eingeben")
            return
        }
        viewModelScope.launch {
            val provider = registry.byId(current.retailerId)
                ?: error("Unbekannter Händler")
            _state.value = _state.value.copy(loading = true, message = "${provider.displayName}-Angebote werden direkt geladen …")
            runCatching { provider.fetch(RetailerRequest(current.postalCode, citySlug = current.city)) }
                .onSuccess { result ->
                    database.productDao().upsertAll(result.products)
                    database.offerDao().upsertAll(result.offers)
                    withContext(Dispatchers.IO) {
                        val knownImages = database.imageDao().find(result.products.map { it.id }).map { it.productId }.toSet()
                        // Image enrichment is deliberately bounded so a large
                        // flyer cannot turn one refresh into hundreds of API calls.
                        result.products.filter { !it.gtin.isNullOrBlank() && it.id !in knownImages }.take(20).forEach { product ->
                            runCatching {
                                imageProvider.find(product.id, product.gtin, product.name, product.brand, "", provider.id)
                            }.getOrNull()?.let { image ->
                                database.imageDao().upsert(image)
                                imageCache.download(image.imageUrl)
                            }
                        }
                    }
                    database.providerDao().upsert(
                        ProviderCacheEntity(
                            providerId = provider.id,
                            lastSuccess = System.currentTimeMillis(),
                            lastError = null,
                            offerCount = result.offers.size,
                        ),
                    )
                    _state.value = _state.value.copy(loading = false, message = "${result.offers.size} Angebote gespeichert")
                }
                .onFailure { error ->
                    database.providerDao().upsert(
                        ProviderCacheEntity(
                            providerId = provider.id,
                            lastFailure = System.currentTimeMillis(),
                            lastError = error.javaClass.simpleName.take(80),
                        ),
                    )
                    _state.value = _state.value.copy(loading = false, message = "Offline/Fehler: ${error.message}")
                }
        }
    }

    override fun onCleared() { database.close(); super.onCleared() }
}
