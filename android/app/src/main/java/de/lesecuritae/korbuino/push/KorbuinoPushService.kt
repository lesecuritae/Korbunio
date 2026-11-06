package de.lesecuritae.korbuino.push

import de.lesecuritae.korbuino.security.SecureStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import org.unifiedpush.android.connector.FailedReason
import org.unifiedpush.android.connector.PushService
import org.unifiedpush.android.connector.data.PushEndpoint
import org.unifiedpush.android.connector.data.PushMessage

/** Receives UnifiedPush (for example NextPush): a new endpoint goes to the own server, messages become notifications. */
class KorbuinoPushService : PushService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onNewEndpoint(endpoint: PushEndpoint, instance: String) {
        val store = SecureStore(applicationContext)
        store.put(PushRegistrar.ENDPOINT, endpoint.url)
        PushRegistrar.setStatus(store, "Push-Endpunkt erhalten; melde beim Server an…")
        scope.launch { PushRegistrar.registerOnServer(applicationContext, store) }
    }

    override fun onMessage(message: PushMessage, instance: String) {
        PushNotifier.show(applicationContext, PushText.from(message.content))
    }

    override fun onRegistrationFailed(reason: FailedReason, instance: String) {
        PushRegistrar.setStatus(SecureStore(applicationContext), "Push-Anmeldung fehlgeschlagen ($reason). Verteiler (z. B. NextPush) prüfen.")
    }

    override fun onUnregistered(instance: String) {
        scope.launch { PushRegistrar.unregisterOnServer(applicationContext) }
    }
}
