package de.lesecuritae.korbuino.data

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(tableName = "retailers")
data class RetailerEntity(@PrimaryKey val id: String, val name: String, val enabled: Boolean = true)

@Entity(tableName = "stores", indices = [Index(value = ["retailerId", "postalCode"], unique = true)])
data class StoreEntity(
    @PrimaryKey val id: String,
    val retailerId: String,
    val name: String,
    val postalCode: String,
    val address: String = "",
    val sourceUrl: String = "",
)

@Entity(tableName = "products", indices = [Index(value = ["normalizedKey"], unique = true)])
data class ProductEntity(
    @PrimaryKey val id: String,
    val name: String,
    val brand: String = "",
    val normalizedKey: String,
    val gtin: String? = null,
)

@Entity(tableName = "categories")
data class CategoryEntity(@PrimaryKey val id: String, val name: String)

@Entity(tableName = "offers", indices = [Index(value = ["retailerId", "externalId"], unique = true)])
data class OfferEntity(
    @PrimaryKey val id: String,
    val retailerId: String,
    val productId: String,
    val categoryId: String? = null,
    val externalId: String,
    val priceCents: Int,
    val basePriceCents: Int? = null,
    val baseUnit: String? = null,
    val depositCents: Int? = null,
    val validFrom: String? = null,
    val validUntil: String? = null,
    val sourceUrl: String,
    val imageUrl: String? = null,
    val cachedAt: Long,
)

@Entity(tableName = "shopping_lists")
data class ShoppingListEntity(@PrimaryKey val id: String, val name: String, val updatedAt: Long)

@Entity(tableName = "shopping_list_items", primaryKeys = ["listId", "productId"])
data class ShoppingListItemEntity(
    val listId: String,
    val productId: String,
    val quantity: Int = 1,
    val checked: Boolean = false,
    val note: String = "",
)

@Entity(tableName = "favorites", primaryKeys = ["productId"])
data class FavoriteEntity(val productId: String, val createdAt: Long)

@Entity(tableName = "provider_cache")
data class ProviderCacheEntity(
    @PrimaryKey val providerId: String,
    val lastSuccess: Long? = null,
    val lastFailure: Long? = null,
    val lastError: String? = null,
    val offerCount: Int = 0,
)

@Entity(tableName = "product_images")
data class ProductImageEntity(
    @PrimaryKey val productId: String,
    val imageUrl: String,
    val source: String,
    val matchMethod: String,
    val confidence: Double,
    val verifiedAt: Long,
    val cachedAt: Long,
    val retailer: String = "",
    val sourceType: String = "external",
    val gtin: String? = null,
)

@Entity(tableName = "settings")
data class SettingEntity(@PrimaryKey val key: String, val value: String)

@Entity(tableName = "sync_state")
data class SyncStateEntity(@PrimaryKey val providerId: String, val state: String, val updatedAt: Long)
