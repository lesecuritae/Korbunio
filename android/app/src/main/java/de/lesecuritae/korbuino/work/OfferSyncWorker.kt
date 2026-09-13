package de.lesecuritae.korbuino.work

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import de.lesecuritae.korbuino.data.KorbuinoDatabase
import de.lesecuritae.korbuino.data.ProviderCacheEntity
import de.lesecuritae.korbuino.providers.NetworkClientFactory
import de.lesecuritae.korbuino.providers.ProviderRegistry
import de.lesecuritae.korbuino.providers.ProviderImportPolicy
import de.lesecuritae.korbuino.providers.RetailerRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope

class OfferSyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val postalCode = inputData.getString("postal_code") ?: return Result.failure()
        val citySlug = inputData.getString("city_slug") ?: return Result.failure()
        val providerId = inputData.getString("provider_id") ?: "rewe"
        return runCatching {
            val registry = ProviderRegistry.default(NetworkClientFactory.create(applicationContext))
            val providers = if (providerId == "all") registry.all() else listOfNotNull(registry.byId(providerId))
            if (providers.isEmpty()) error("Unbekannter Händler: $providerId")
            val fetched = coroutineScope {
                providers.map { provider ->
                    async(Dispatchers.IO) {
                        provider to runCatching { provider.fetch(RetailerRequest(postalCode, citySlug = citySlug)) }
                    }
                }.awaitAll()
            }
            val db = KorbuinoDatabase.create(applicationContext)
            try {
                val successes = fetched.mapNotNull { (provider, result) ->
                    val value = result.getOrNull() ?: return@mapNotNull null
                    val previous = db.providerDao().get(provider.id)
                    val rejection = ProviderImportPolicy.rejectionReason(provider.id, value.offers.size, previous?.offerCount ?: 0)
                    db.providerDao().upsert(
                        ProviderCacheEntity(
                            providerId = provider.id,
                            lastSuccess = if (rejection == null) System.currentTimeMillis() else previous?.lastSuccess,
                            lastFailure = if (rejection == null || value.offers.isEmpty()) previous?.lastFailure else System.currentTimeMillis(),
                            lastError = rejection,
                            offerCount = if (rejection == null) value.offers.size else previous?.offerCount ?: 0,
                            retailerReachable = true,
                            sourceReachable = true,
                            offersAvailable = value.offers.isNotEmpty(),
                            imagesAvailable = value.offers.any { !it.imageUrl.isNullOrBlank() },
                            parserOk = true,
                        ),
                    )
                    if (rejection == null) provider to value else null
                }
                if (successes.isEmpty()) error("Keine Händlerangebote verfügbar")
                val rawProducts = successes.flatMap { it.second.products }
                val canonical = LinkedHashMap<String, de.lesecuritae.korbuino.data.ProductEntity>()
                rawProducts.forEach { canonical.putIfAbsent(it.normalizedKey, it) }
                val productIds = rawProducts.associate { it.id to canonical.getValue(it.normalizedKey).id }
                val products = canonical.values.toList()
                val offers = successes.flatMap { it.second.offers }.map { offer ->
                    productIds[offer.productId]?.let { offer.copy(productId = it) } ?: offer
                }.distinctBy { it.id }
                db.productDao().upsertAll(products)
                db.offerDao().storeRefresh(offers)
            } finally {
                db.close()
            }
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
