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
    version = 4,
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
        ).addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4).build()

        private val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL("ALTER TABLE product_images ADD COLUMN retailer TEXT NOT NULL DEFAULT ''")
                database.execSQL("ALTER TABLE product_images ADD COLUMN sourceType TEXT NOT NULL DEFAULT 'external'")
                database.execSQL("ALTER TABLE product_images ADD COLUMN gtin TEXT")
            }
        }

        private val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL("ALTER TABLE offers ADD COLUMN loyaltyProgram TEXT")
                database.execSQL("ALTER TABLE offers ADD COLUMN loyaltyLabel TEXT")
                database.execSQL("ALTER TABLE offers ADD COLUMN loyaltyPriceCents INTEGER")
            }
        }

        private val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL("ALTER TABLE provider_cache ADD COLUMN sourceReachable INTEGER NOT NULL DEFAULT 0")
                database.execSQL("ALTER TABLE provider_cache ADD COLUMN retailerReachable INTEGER NOT NULL DEFAULT 0")
                database.execSQL("ALTER TABLE provider_cache ADD COLUMN offersAvailable INTEGER NOT NULL DEFAULT 0")
                database.execSQL("ALTER TABLE provider_cache ADD COLUMN imagesAvailable INTEGER NOT NULL DEFAULT 0")
                database.execSQL("ALTER TABLE provider_cache ADD COLUMN parserOk INTEGER NOT NULL DEFAULT 0")
            }
        }
    }
}
