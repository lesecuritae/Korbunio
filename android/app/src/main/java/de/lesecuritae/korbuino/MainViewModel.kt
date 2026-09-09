package de.lesecuritae.korbuino

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import de.lesecuritae.korbuino.data.KorbuinoDatabase
import de.lesecuritae.korbuino.data.OfferEntity
import de.lesecuritae.korbuino.providers.NetworkClientFactory
import de.lesecuritae.korbuino.providers.ReweProvider
import de.lesecuritae.korbuino.providers.RetailerRequest
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class MainUiState(
    val postalCode: String = "",
    val city: String = "",
    val loading: Boolean = false,
    val offers: List<OfferEntity> = emptyList(),
    val message: String = "Noch keine Angebote geladen",
)

class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val database = KorbuinoDatabase.create(application)
    private val provider = ReweProvider(NetworkClientFactory.create(application))
    private val _state = MutableStateFlow(MainUiState())
    val state: StateFlow<MainUiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            database.offerDao().observeAll().collect { offers ->
                _state.value = _state.value.copy(offers = offers)
            }
        }
    }

    fun postalCode(value: String) { _state.value = _state.value.copy(postalCode = value.filter(Char::isDigit).take(5)) }
    fun city(value: String) { _state.value = _state.value.copy(city = value.take(60)) }

    fun refresh() {
        val current = _state.value
        if (current.postalCode.length != 5 || current.city.isBlank()) {
            _state.value = current.copy(message = "PLZ und Stadt eingeben")
            return
        }
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, message = "REWE-Angebote werden direkt geladen …")
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
