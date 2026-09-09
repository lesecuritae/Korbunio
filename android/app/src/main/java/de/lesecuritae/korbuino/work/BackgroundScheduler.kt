package de.lesecuritae.korbuino.work

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

enum class BackgroundMode { MANUAL, DAILY }

data class BackgroundSettings(
    val mode: BackgroundMode = BackgroundMode.MANUAL,
    val wifiOnly: Boolean = true,
    val chargingOnly: Boolean = false,
    val allowMetered: Boolean = false,
)

object BackgroundScheduler {
    private const val OFFER_SYNC = "korbuino-offer-sync"
    private const val CACHE_MAINTENANCE = "korbuino-cache-maintenance"

    fun apply(context: Context, settings: BackgroundSettings, postalCode: String, citySlug: String, providerId: String = "rewe") {
        val manager = WorkManager.getInstance(context)
        val maintenance = PeriodicWorkRequestBuilder<CacheMaintenanceWorker>(1, TimeUnit.DAYS).build()
        manager.enqueueUniquePeriodicWork(CACHE_MAINTENANCE, ExistingPeriodicWorkPolicy.UPDATE, maintenance)
        if (settings.mode == BackgroundMode.MANUAL || postalCode.isBlank()) {
            manager.cancelUniqueWork(OFFER_SYNC)
            return
        }
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(
                if (settings.wifiOnly || !settings.allowMetered) NetworkType.UNMETERED else NetworkType.CONNECTED,
            )
            .setRequiresCharging(settings.chargingOnly)
            .build()
        val request = PeriodicWorkRequestBuilder<OfferSyncWorker>(1, TimeUnit.DAYS)
            .setConstraints(constraints)
            .setInputData(androidx.work.workDataOf("postal_code" to postalCode, "city_slug" to citySlug, "provider_id" to providerId))
            .build()
        manager.enqueueUniquePeriodicWork(OFFER_SYNC, ExistingPeriodicWorkPolicy.UPDATE, request)
    }
}
