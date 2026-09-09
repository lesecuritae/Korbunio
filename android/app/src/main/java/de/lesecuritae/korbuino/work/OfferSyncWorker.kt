package de.lesecuritae.korbuino.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import de.lesecuritae.korbuino.data.KorbuinoDatabase
import de.lesecuritae.korbuino.data.ProviderCacheEntity
import de.lesecuritae.korbuino.providers.NetworkClientFactory
import de.lesecuritae.korbuino.providers.ProviderRegistry
import de.lesecuritae.korbuino.providers.RetailerRequest

class OfferSyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val postalCode = inputData.getString("postal_code") ?: return Result.failure()
        val citySlug = inputData.getString("city_slug") ?: return Result.failure()
        val providerId = inputData.getString("provider_id") ?: "rewe"
        return runCatching {
            val provider = ProviderRegistry.default(NetworkClientFactory.create(applicationContext)).byId(providerId)
                ?: error("Unbekannter Händler: $providerId")
            val result = provider.fetch(RetailerRequest(postalCode, citySlug = citySlug))
            val db = KorbuinoDatabase.create(applicationContext)
            db.productDao().upsertAll(result.products)
            db.offerDao().upsertAll(result.offers)
            db.providerDao().upsert(
                ProviderCacheEntity(
                    providerId = provider.id,
                    lastSuccess = System.currentTimeMillis(),
                    offerCount = result.offers.size,
                ),
            )
            db.close()
        }.fold(
            onSuccess = { Result.success() },
            onFailure = { error ->
                runCatching {
                    val db = KorbuinoDatabase.create(applicationContext)
                    db.providerDao().upsert(
                        ProviderCacheEntity(
                            providerId = providerId,
                            lastFailure = System.currentTimeMillis(),
                            lastError = error.javaClass.simpleName.take(80),
                        ),
                    )
                    db.close()
                }
                Result.retry()
            },
        )
    }
}
