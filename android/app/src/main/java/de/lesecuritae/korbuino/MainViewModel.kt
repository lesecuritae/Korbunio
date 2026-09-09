package de.lesecuritae.korbuino

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.lesecuritae.korbuino.data.KorbuinoDatabase
import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.data.ProductEntity
import de.lesecuritae.korbuino.data.ShoppingListItemEntity
import de.lesecuritae.korbuino.data.ShoppingListRow
import de.lesecuritae.korbuino.providers.NetworkClientFactory
import de.lesecuritae.korbuino.providers.ProviderRegistry
import de.lesecuritae.korbuino.providers.RetailerRequest
import de.lesecuritae.korbuino.kitchenowl.KitchenOwlClient
import de.lesecuritae.korbuino.kitchenowl.KitchenOwlTarget
import de.lesecuritae.korbuino.security.SecureStore
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
    val message: String = "Noch keine Angebote geladen",
)

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val database = KorbuinoDatabase.create(application)
    private val registry = ProviderRegistry.default(NetworkClientFactory.create(application))
    private val _state = MutableStateFlow(MainUiState())
    private val secureStore = SecureStore(application)
    val state: StateFlow<MainUiState> = _state.asStateFlow()

    val retailers = registry.all().map { it.id to it.displayName }

    init {
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

    fun postalCode(value: String) { _state.value = _state.value.copy(postalCode = value.filter(Char::isDigit).take(5)) }
    fun city(value: String) { _state.value = _state.value.copy(city = value.take(60)) }
    fun retailer(value: String) { if (retailers.any { it.first == value }) _state.value = _state.value.copy(retailerId = value) }

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
                    database.shoppingListDao().allItems().forEach { item ->
                        val product = database.productDao().find(listOf(item.productId)).firstOrNull()
                        if (product != null) client.addItem(target.id, product.name, "Menge: ${item.quantity}")
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
                    _state.value = _state.value.copy(loading = false, message = "${result.offers.size} Angebote gespeichert")
                }
                .onFailure { error -> _state.value = _state.value.copy(loading = false, message = "Offline/Fehler: ${error.message}") }
        }
    }

    override fun onCleared() { database.close(); super.onCleared() }
}
