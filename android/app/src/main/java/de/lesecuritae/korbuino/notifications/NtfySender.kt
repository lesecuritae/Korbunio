package de.lesecuritae.korbuino.notifications

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import java.io.IOException
import java.io.InterruptedIOException
import java.util.concurrent.TimeUnit

// Deliberately no generated toString: settings contain credentials and a private topic.
class NtfySettings(val enabled: Boolean = false, val topicUrl: String = "", val bearerToken: String = "")
data class NtfyResult(val submitted: Boolean, val message: String, val retryable: Boolean = false)

class NtfySender(http: OkHttpClient = OkHttpClient()) {
    // Redirects must never send a private topic or credentials to another endpoint.
    private val client = http.newBuilder().followRedirects(false).followSslRedirects(false)
        .callTimeout(20, TimeUnit.SECONDS).build()

    companion object {
        /** The same local validation is used by settings save and publication. No network calls. */
        fun validationError(settings: NtfySettings, requireTopic: Boolean = settings.enabled): String? {
            if (settings.bearerToken.any { it == '\r' || it == '\n' }) return "Ungültiger Bearer-Token."
            if (settings.topicUrl.isBlank()) return if (requireTopic) "Bitte die vollständige ntfy-Themen-URL eintragen." else null
            val url = settings.topicUrl.trim().toHttpUrlOrNull()
            if (url == null || !url.isHttps || url.host.isBlank() || url.username.isNotEmpty() || url.password.isNotEmpty() ||
                url.query != null || url.fragment != null || url.pathSegments.lastOrNull().isNullOrBlank()) {
                return "Ungültige ntfy-URL: HTTPS und ein Thema im Pfad sind erforderlich; keine Zugangsdaten oder URL-Parameter."
            }
            return null
        }
    }

    suspend fun test(settings: NtfySettings): NtfyResult = send(settings, "Korbuino: Testnachricht erfolgreich angefordert.")

    suspend fun send(settings: NtfySettings, text: String): NtfyResult = withContext(Dispatchers.IO) {
        if (!settings.enabled) return@withContext NtfyResult(false, "ntfy ist deaktiviert.")
        validationError(settings, requireTopic = true)?.let { return@withContext NtfyResult(false, it) }
        val url = settings.topicUrl.trim().toHttpUrlOrNull()!!
        try {
            val request = Request.Builder().url(url)
                .post(text.toRequestBody("text/plain; charset=utf-8".toMediaType()))
                .header("Title", "Korbuino")
                .apply { if (settings.bearerToken.isNotBlank()) header("Authorization", "Bearer ${settings.bearerToken.trim()}") }
                .build()
            client.newCall(request).execute().use { response ->
                when (response.code) {
                    in 200..299 -> NtfyResult(true, "Nachricht an ntfy übermittelt.")
                    401 -> NtfyResult(false, "ntfy: Anmeldung erforderlich. Bearer-Token prüfen (401).")
                    403 -> NtfyResult(false, "ntfy: Keine Schreibberechtigung für dieses Thema (403).")
                    429 -> NtfyResult(false, "ntfy: Zu viele Anfragen; später erneut versuchen (429).", true)
                    in 500..599 -> NtfyResult(false, "ntfy vorübergehend nicht erreichbar (${response.code}).", true)
                    else -> NtfyResult(false, "ntfy hat die Anfrage abgelehnt (${response.code}). Themen-URL prüfen.")
                }
            }
        } catch (_: InterruptedIOException) {
            NtfyResult(false, "ntfy: Zeitüberschreitung. Verbindung prüfen und später erneut versuchen.", true)
        } catch (_: IOException) {
            NtfyResult(false, "ntfy: Verbindung fehlgeschlagen. Netzwerk und HTTPS-Zertifikat prüfen.", true)
        } catch (_: IllegalArgumentException) {
            NtfyResult(false, "Ungültige ntfy-URL oder Bearer-Token.")
        }
    }
}
