package de.lesecuritae.korbuino

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
import de.lesecuritae.korbuino.data.ShoppingListRow
import de.lesecuritae.korbuino.data.ProviderCacheEntity
import de.lesecuritae.korbuino.providers.NetworkClientFactory
import de.lesecuritae.korbuino.providers.ProviderRegistry
import de.lesecuritae.korbuino.providers.ProviderImportPolicy
import de.lesecuritae.korbuino.providers.RetailerRequest
import de.lesecuritae.korbuino.providers.ServerProvider
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
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class MainUiState(
    val postalCode: String = "",
    val city: String = "",
    val retailerId: String = "all",
    val loading: Boolean = false,
    val offers: List<OfferDisplay> = emptyList(),
    val shoppingItems: List<ShoppingListRow> = emptyList(),
    val kitchenOwlUrl: String = "",
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
                    savedRetailer.takeUnless { it == "marktguru-combi" } ?: "all",
                )
            }
            _state.value = _state.value.copy(
                postalCode = saved.first,
                city = saved.second,
                retailerId = saved.third,
                dailySync = secureStore.get("daily_sync") == "true",
                serverUrl = secureStore.get("server_url").orEmpty(),
                serverToken = secureStore.get("server_token").orEmpty(),
                serverMode = secureStore.get("server_mode") == "true",
                kitchenOwlUrl = secureStore.get("kitchenowl_url").orEmpty(),
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
    fun retailer(value: String) {
        if (retailers.any { it.first == value }) {
            _state.value = _state.value.copy(retailerId = value)
            secureStore.put("retailer_id", value)
        }
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
        if (current.postalCode.length != 5) {
            _state.value = current.copy(message = "Eine gültige fünfstellige PLZ eingeben")
            return
        }
        viewModelScope.launch {
            val serverToken = secureStore.get("server_token").orEmpty()
            val http = NetworkClientFactory.create(getApplication())
            val providers = if (current.serverMode && current.serverUrl.isNotBlank()) {
                listOf(ServerProvider(current.serverUrl, serverToken, http))
            } else if (current.retailerId == "all") {
                registry.all()
            } else {
                listOfNotNull(registry.byId(current.retailerId))
            }
            if (providers.isEmpty()) {
                _state.value = _state.value.copy(loading = false, message = "Kein Händler ausgewählt")
                return@launch
            }
            val label = if (providers.size == 1) providers.single().displayName else "${providers.size} Händler"
            _state.value = _state.value.copy(loading = true, challengeUrl = null, message = "$label-Angebote werden direkt geladen …")
            val fetched = coroutineScope {
                providers.map { provider ->
                    async(Dispatchers.IO) {
                        provider to runCatching { provider.fetch(RetailerRequest(current.postalCode, citySlug = current.city)) }
                    }
                }.awaitAll()
            }
            val successes = mutableListOf<Pair<de.lesecuritae.korbuino.providers.RetailerProvider, de.lesecuritae.korbuino.providers.ProviderResult>>()
            var emptySources = 0
            var rejectedSources = 0
            var failedSources = 0
            fetched.forEach { (provider, result) ->
                val previous = database.providerDao().get(provider.id)
                result.onSuccess { value ->
                    val rejection = ProviderImportPolicy.rejectionReason(provider.id, value.offers.size, previous?.offerCount ?: 0)
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
                val rawProducts = successes.flatMap { it.second.products }
                val canonicalProducts = LinkedHashMap<String, ProductEntity>()
                rawProducts.forEach { product -> canonicalProducts.putIfAbsent(product.normalizedKey, product) }
                val productIds = rawProducts.associate { it.id to canonicalProducts.getValue(it.normalizedKey).id }
                val products = canonicalProducts.values.toList()
                val offers = successes.flatMap { it.second.offers }.map { offer ->
                    productIds[offer.productId]?.let { canonicalId -> offer.copy(productId = canonicalId) } ?: offer
                }.distinctBy { it.id }
                database.productDao().upsertAll(products)
                val previousOfferPostal = secureStore.get("offer_postal_code").orEmpty()
                if (previousOfferPostal.isNotBlank() && previousOfferPostal != current.postalCode) {
                    database.offerDao().deleteAll()
                }
                database.offerDao().storeRefresh(offers)
                secureStore.put("offer_postal_code", current.postalCode)
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
                        if (failedSources > 0) append(" · $failedSources Abruffehler")
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
                    message = if (challenge != null) "Händler-Bestätigung erforderlich" else "Offline/Fehler: ${error?.message ?: "Keine Angebote verfügbar"}",
                )
            }
        }
    }

    private fun isChallengeError(error: Throwable): Boolean {
        val text = generateSequence(error) { it.cause }.joinToString(" ") { it.message.orEmpty() }.lowercase()
        return listOf("403", "429", "captcha", "challenge", "forbidden", "anti-bot", "bot protection").any(text::contains)
    }

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
