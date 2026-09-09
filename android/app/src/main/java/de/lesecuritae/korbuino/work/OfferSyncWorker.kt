package de.lesecuritae.korbuino.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import de.lesecuritae.korbuino.data.KorbuinoDatabase
import de.lesecuritae.korbuino.providers.NetworkClientFactory
import de.lesecuritae.korbuino.providers.ReweProvider
import de.lesecuritae.korbuino.providers.RetailerRequest

class OfferSyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val postalCode = inputData.getString("postal_code") ?: return Result.failure()
        val citySlug = inputData.getString("city_slug") ?: return Result.failure()
        return runCatching {
            val result = ReweProvider(NetworkClientFactory.create(applicationContext)).fetch(RetailerRequest(postalCode, citySlug = citySlug))
            val db = KorbuinoDatabase.create(applicationContext)
            db.productDao().upsertAll(result.products)
            db.offerDao().upsertAll(result.offers)
            db.close()
        }.fold(onSuccess = { Result.success() }, onFailure = { Result.retry() })
    }
}
