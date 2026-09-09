package de.lesecuritae.korbuino.backup

import android.content.Context
import de.lesecuritae.korbuino.data.KorbuinoDatabase
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.io.OutputStream

@Serializable
data class SafeBackup(
    val formatVersion: Int = 1,
    val productNames: Map<String, String> = emptyMap(),
    val listItems: List<BackupListItem> = emptyList(),
    val settings: Map<String, String> = emptyMap(),
)

@Serializable
data class BackupListItem(val productId: String, val quantity: Int, val checked: Boolean, val note: String)

/** Exports user data while intentionally excluding API tokens and credentials. */
class BackupService(private val context: Context) {
    private val json = Json { prettyPrint = true; encodeDefaults = true }

    suspend fun export(output: OutputStream) {
        val database = KorbuinoDatabase.create(context)
        // Credentials live only in SecureStore and can never enter this document.
        output.bufferedWriter().use { it.write(json.encodeToString(SafeBackup())) }
        database.close()
    }
}
