package de.lesecuritae.korbuino.security

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

class SecureStore(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context,
        "korbuino-secrets",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun loadNtfySettings() = de.lesecuritae.korbuino.notifications.NtfySettings(
        get("ntfy_enabled") == "true", get("ntfy_topic_url").orEmpty(), get("ntfy_bearer_token").orEmpty(),
    )

    fun saveNtfySettings(settings: de.lesecuritae.korbuino.notifications.NtfySettings) {
        prefs.edit().putBoolean("ntfy_configured", true)
            .putString("ntfy_enabled", settings.enabled.toString())
            .putString("ntfy_topic_url", settings.topicUrl.trim())
            .putString("ntfy_bearer_token", settings.bearerToken.trim()).apply()
    }

    fun get(key: String): String? = prefs.getString(key, null)
    fun put(key: String, value: String) = prefs.edit().putString(key, value).apply()
    fun remove(key: String) = prefs.edit().remove(key).apply()
}
