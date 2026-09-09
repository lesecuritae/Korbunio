package de.lesecuritae.korbuino.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import de.lesecuritae.korbuino.images.ImageCache

class CacheMaintenanceWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        ImageCache(applicationContext).evictOlderThan(30L * 24 * 60 * 60 * 1000)
        return Result.success()
    }
}
