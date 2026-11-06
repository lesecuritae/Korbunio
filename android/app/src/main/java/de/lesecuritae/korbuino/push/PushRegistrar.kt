package de.lesecuritae.korbuino.push

import android.content.Context
import de.lesecuritae.korbuino.providers.NetworkClientFactory
import de.lesecuritae.korbuino.security.SecureStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.IOException

/** Keeps the UnifiedPush endpoint and its registration on the own server (never logged or shown). */
object PushRegistrar {
    const val ENDPOINT = "push_endpoint"
    const val STATUS = "push_status"
    const val ON_SERVER = "push_on_server"

    /** Sends [endpoint] to the server; the server answers by pushing a test message to it. */
    suspend fun registerOnServer(context: Context, store: SecureStore = SecureStore(context)): String = withContext(Dispatchers.IO) {
        val endpoint = store.get(ENDPOINT).orEmpty()
        if (endpoint.isBlank()) return@withContext setStatus(store, "Noch kein Push-Endpunkt: erst aktivieren.")
        val request = ServerPushRegistration.request(store.get("server_url").orEmpty(), store.get("server_token").orEmpty(), endpoint)
            ?: return@withContext setStatus(store, "Server-Adresse fehlt oder ist ungültig; Endpunkt ist gespeichert.")
        try {
            NetworkClientFactory.create(context).newCall(request).execute().use { response ->
                when {
                    response.isSuccessful -> { store.put(ON_SERVER, "true"); setStatus(store, "Beim Server angemeldet; Testnachricht gesendet.") }
                    response.code == 401 || response.code == 403 -> setStatus(store, "Server lehnt ab (${response.code}): Server-Token prüfen.")
                    response.code == 502 -> setStatus(store, "Server konnte den Push-Endpunkt nicht erreichen (502).")
                    else -> setStatus(store, "Server antwortete mit HTTP ${response.code}.")
                }
            }
        } catch (_: IOException) {
            setStatus(store, "Server nicht erreichbar; später erneut anmelden.")
        }
    }

    /** Removes the push target from the server, but only if this app put it there. */
    suspend fun unregisterOnServer(context: Context, store: SecureStore = SecureStore(context)) = withContext(Dispatchers.IO) {
        if (store.get(ON_SERVER) == "true") {
            ServerPushRegistration.request(store.get("server_url").orEmpty(), store.get("server_token").orEmpty(), null)?.let { request ->
                try { NetworkClientFactory.create(context).newCall(request).execute().close() } catch (_: IOException) { }
            }
        }
        store.remove(ON_SERVER); store.remove(ENDPOINT)
        setStatus(store, "Push ist aus.")
    }

    fun setStatus(store: SecureStore, text: String): String { store.put(STATUS, text); return text }
}
