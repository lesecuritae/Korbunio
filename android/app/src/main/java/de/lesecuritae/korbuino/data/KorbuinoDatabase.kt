package de.lesecuritae.korbuino.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [
        RetailerEntity::class, StoreEntity::class, ProductEntity::class,
        CategoryEntity::class, OfferEntity::class, ShoppingListEntity::class,
        ShoppingListItemEntity::class, FavoriteEntity::class,
        ProviderCacheEntity::class, ProductImageEntity::class,
        SettingEntity::class, SyncStateEntity::class,
    ],
    version = 2,
    exportSchema = true,
)
abstract class KorbuinoDatabase : RoomDatabase() {
    abstract fun offerDao(): OfferDao
    abstract fun productDao(): ProductDao
    abstract fun providerDao(): ProviderDao
    abstract fun settingsDao(): SettingsDao
    abstract fun shoppingListDao(): ShoppingListDao
    abstract fun imageDao(): ImageDao

    companion object {
        fun create(context: Context): KorbuinoDatabase = Room.databaseBuilder(
            context,
            KorbuinoDatabase::class.java,
            "korbuino.db",
        // Never erase user data on a downgrade. Future schema changes must ship
        // an explicit Room migration; otherwise startup fails safely.
        ).addMigrations(MIGRATION_1_2).build()

        private val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL("ALTER TABLE product_images ADD COLUMN retailer TEXT NOT NULL DEFAULT ''")
                database.execSQL("ALTER TABLE product_images ADD COLUMN sourceType TEXT NOT NULL DEFAULT 'external'")
                database.execSQL("ALTER TABLE product_images ADD COLUMN gtin TEXT")
            }
        }
    }
}
