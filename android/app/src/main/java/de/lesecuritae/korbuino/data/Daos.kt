package de.lesecuritae.korbuino.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import kotlinx.coroutines.flow.Flow

@Dao
interface OfferDao {
    @Query("SELECT * FROM offers ORDER BY validUntil DESC, id")
    fun observeAll(): Flow<List<OfferEntity>>

    @Query("SELECT * FROM offers ORDER BY validUntil DESC, id")
    suspend fun all(): List<OfferEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(offers: List<OfferEntity>)

    @Transaction
    suspend fun storeRefresh(offers: List<OfferEntity>) {
        offers.map { it.retailerId }.distinct().forEach { deleteProvider(it) }
        upsertAll(offers)
    }

    @Query("DELETE FROM offers WHERE retailerId = :retailerId")
    suspend fun deleteProvider(retailerId: String)

    @Query("DELETE FROM offers")
    suspend fun deleteAll()
}

@Dao
interface ProductDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(products: List<ProductEntity>)

    @Query("SELECT * FROM products WHERE id IN (:ids)")
    suspend fun findChunk(ids: List<String>): List<ProductEntity>

    @Transaction
    suspend fun find(ids: List<String>): List<ProductEntity> =
        ids.distinct().chunked(SQLITE_BIND_CHUNK_SIZE).flatMap { findChunk(it) }

    @Query("SELECT * FROM products")
    suspend fun all(): List<ProductEntity>
}

@Dao
interface ProviderDao {
    @Query("SELECT * FROM provider_cache")
    fun observe(): Flow<List<ProviderCacheEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(value: ProviderCacheEntity)

    @Query("SELECT * FROM provider_cache WHERE providerId = :providerId LIMIT 1")
    suspend fun get(providerId: String): ProviderCacheEntity?

    @Query("DELETE FROM provider_cache WHERE providerId = :providerId")
    suspend fun delete(providerId: String)
}

@Dao
interface ImageDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(value: ProductImageEntity)

    @Query("SELECT * FROM product_images WHERE productId IN (:ids)")
    suspend fun findChunk(ids: List<String>): List<ProductImageEntity>

    @Transaction
    suspend fun find(ids: List<String>): List<ProductImageEntity> =
        ids.distinct().chunked(SQLITE_BIND_CHUNK_SIZE).flatMap { findChunk(it) }
}

@Dao
interface SettingsDao {
    @Query("SELECT value FROM settings WHERE `key` = :key LIMIT 1")
    suspend fun get(key: String): String?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(value: SettingEntity)

    @Query("SELECT * FROM settings")
    suspend fun all(): List<SettingEntity>
}

@Dao
interface ShoppingListDao {
    @Query("SELECT * FROM shopping_list_items")
    suspend fun allItems(): List<ShoppingListItemEntity>

    @Query("SELECT shopping_list_items.productId AS productId, products.name AS name, shopping_list_items.quantity AS quantity, shopping_list_items.checked AS checked FROM shopping_list_items INNER JOIN products ON products.id = shopping_list_items.productId WHERE shopping_list_items.listId = 'default' ORDER BY products.name")
    fun observeDefault(): Flow<List<ShoppingListRow>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertAll(items: List<ShoppingListItemEntity>)
}

data class ShoppingListRow(val productId: String, val name: String, val quantity: Int, val checked: Boolean)

private const val SQLITE_BIND_CHUNK_SIZE = 900
