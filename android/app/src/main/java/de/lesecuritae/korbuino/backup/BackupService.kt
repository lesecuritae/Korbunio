package de.lesecuritae.korbuino.backup

import android.content.Context
import de.lesecuritae.korbuino.data.KorbuinoDatabase
import de.lesecuritae.korbuino.data.ProductEntity
import de.lesecuritae.korbuino.data.SettingEntity
import de.lesecuritae.korbuino.data.ShoppingListItemEntity
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.booleanOrNull
import java.io.InputStream
import java.io.OutputStream
import java.security.MessageDigest

@Serializable
data class SafeBackup(
    val formatVersion: Int = 1,
    val productNames: Map<String, String> = emptyMap(),
    val listItems: List<BackupListItem> = emptyList(),
    val settings: Map<String, String> = emptyMap(),
)

@Serializable
data class BackupListItem(
    val productId: String,
    val quantity: Int,
    val checked: Boolean,
    val note: String = "",
)

/**
 * Exports and imports user data while intentionally excluding API tokens and
 * credentials. SecureStore is never serialized. Unknown fields from the old
 * Flutter JSON format are ignored for forward/backward compatibility.
 */
class BackupService(private val context: Context) {
    private val json = Json { prettyPrint = true; encodeDefaults = true; ignoreUnknownKeys = true }
    private val secretKey = Regex("(?i)(token|secret|password|credential|api[_-]?key)")

    suspend fun export(output: OutputStream) {
        val database = KorbuinoDatabase.create(context)
        try {
            val products = database.productDao().all()
            val items = database.shoppingListDao().allItems()
            val settings = database.settingsDao().all().filterNot { secretKey.containsMatchIn(it.key) }
            val document = SafeBackup(
                productNames = products.associate { it.id to it.name },
                listItems = items.map { it.toBackup() },
                settings = settings.associate { it.key to it.value },
            )
            output.bufferedWriter().use { it.write(json.encodeToString(document)) }
        } finally {
            database.close()
        }
    }

    /** Imports both native backups and the previous Flutter shopping-list JSON. */
    suspend fun import(input: InputStream) {
        val root = json.parseToJsonElement(input.bufferedReader().use { it.readText() }).jsonObject
        val database = KorbuinoDatabase.create(context)
        try {
            // The old Flutter document also contains an `items` array. Do not
            // decode it as an empty native document merely because all native
            // fields have defaults.
            val isNative = root.containsKey("formatVersion") || root.containsKey("productNames") || root.containsKey("listItems")
            val native = if (isNative) runCatching { json.decodeFromJsonElement<SafeBackup>(root) }.getOrNull() else null
            val legacyItems = root["items"]?.jsonArray.orEmpty()
            val productNames = native?.productNames ?: legacyItems
                .mapNotNull { item -> item.jsonObject["name"]?.jsonPrimitive?.content?.trim() }
                .filter(String::isNotBlank).distinct().associateBy { stableId(it) }
            val listItems = native?.listItems ?: legacyItems.mapNotNull { item ->
                val obj = item.jsonObject
                val name = obj["name"]?.jsonPrimitive?.content?.trim().orEmpty()
                if (name.isBlank()) return@mapNotNull null
                BackupListItem(
                    productId = stableId(name),
                    quantity = obj["quantity"]?.jsonPrimitive?.intOrNull?.coerceIn(1, 999) ?: 1,
                    checked = obj["checked"]?.jsonPrimitive?.booleanOrNull ?: false,
                    note = obj["note"]?.jsonPrimitive?.content.orEmpty().take(500),
                )
            }
            val products = productNames.map { (id, name) ->
                ProductEntity(id, name, normalizedKey = name.trim().lowercase())
            }
            if (products.isNotEmpty()) database.productDao().upsertAll(products)
            if (listItems.isNotEmpty()) database.shoppingListDao().upsertAll(listItems.map { it.toEntity() })
            native?.settings?.filterKeys { !secretKey.containsMatchIn(it) }
                ?.forEach { (key, value) -> database.settingsDao().put(SettingEntity(key, value)) }
        } finally {
            database.close()
        }
    }

    private fun BackupListItem.toEntity() = ShoppingListItemEntity("default", productId, quantity, checked, note)
    private fun ShoppingListItemEntity.toBackup() = BackupListItem(productId, quantity, checked, note)

    private fun stableId(name: String): String = "imported:" + MessageDigest.getInstance("SHA-256")
        .digest(name.trim().lowercase().toByteArray()).joinToString("") { "%02x".format(it) }.take(24)
}
