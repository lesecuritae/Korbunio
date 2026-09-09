package de.lesecuritae.korbuino.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(
    entities = [
        RetailerEntity::class, StoreEntity::class, ProductEntity::class,
        CategoryEntity::class, OfferEntity::class, ShoppingListEntity::class,
        ShoppingListItemEntity::class, FavoriteEntity::class,
        ProviderCacheEntity::class, ProductImageEntity::class,
        SettingEntity::class, SyncStateEntity::class,
    ],
    version = 1,
    exportSchema = true,
)
abstract class KorbuinoDatabase : RoomDatabase() {
    abstract fun offerDao(): OfferDao
    abstract fun productDao(): ProductDao
    abstract fun providerDao(): ProviderDao
    abstract fun settingsDao(): SettingsDao
    abstract fun shoppingListDao(): ShoppingListDao

    companion object {
        fun create(context: Context): KorbuinoDatabase = Room.databaseBuilder(
            context,
            KorbuinoDatabase::class.java,
            "korbuino.db",
        // Never erase user data on a downgrade. Future schema changes must ship
        // an explicit Room migration; otherwise startup fails safely.
        ).build()
    }
}
