package de.lesecuritae.korbuino.work

import androidx.room.withTransaction
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
import de.lesecuritae.korbuino.RetailerSelection
import kotlinx.coroutines.coroutineScope

class OfferSyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val secureStore = de.lesecuritae.korbuino.security.SecureStore(applicationContext)
        if (secureStore.get("daily_sync") != "true" || secureStore.get("server_mode") == "true") return Result.success()
        val postalCode = secureStore.get("postal_code").orEmpty()
        val citySlug = secureStore.get("city").orEmpty()
        val providerId = secureStore.get("retailer_id") ?: inputData.getString("provider_id") ?: "all"
        if (!postalCode.matches(Regex("\\d{5}"))) return Result.failure()
        return runCatching {
            val registry = ProviderRegistry.default(NetworkClientFactory.create(applicationContext))
            val chosen = RetailerSelection.parse(providerId, registry.all().map { it.id })
            val providers = if (providerId == "all") registry.all() else chosen.mapNotNull(registry::byId)
            if (providers.isEmpty()) error("Unbekannter Händler: $providerId")
            val fetched = coroutineScope {
                providers.map { provider ->
                    async(Dispatchers.IO) {
                        provider to runCatching { provider.fetch(RetailerRequest(postalCode, citySlug = citySlug)) }
                    }
                }.awaitAll()
            }
            if (secureStore.get("daily_sync") != "true" || secureStore.get("postal_code") != postalCode) return Result.success()
            val db = KorbuinoDatabase.create(applicationContext)
            try {
                val successes = fetched.mapNotNull { (provider, result) ->
                    val value = result.getOrNull() ?: return@mapNotNull null
                    val previous = db.providerDao().get(provider.id)
                    val rejection = ProviderImportPolicy.rejectionReason(provider.id, value, previous?.offerCount ?: 0)
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
                db.withTransaction {
                    check(secureStore.get("daily_sync") == "true" && secureStore.get("postal_code") == postalCode) { "Aktualisierung inzwischen deaktiviert oder PLZ geändert" }
                    val rawProducts = successes.flatMap { it.second.products }
                    val canonical = LinkedHashMap<String, de.lesecuritae.korbuino.data.ProductEntity>()
                    db.productDao().all().forEach { canonical.putIfAbsent(it.normalizedKey, it) }
                    rawProducts.forEach { canonical.putIfAbsent(it.normalizedKey, it) }
                    val productIds = rawProducts.associate { it.id to canonical.getValue(it.normalizedKey).id }
                    val products = rawProducts.map { canonical.getValue(it.normalizedKey) }.distinctBy { it.id }
                    val offers = successes.flatMap { it.second.offers }.map { offer ->
                        productIds[offer.productId]?.let { offer.copy(productId = it) } ?: offer
                    }.distinctBy { it.id }
                    db.productDao().upsertAll(products)
                    val previousPostalCode = secureStore.get("offer_postal_code").orEmpty()
                    if (previousPostalCode.isNotBlank() && previousPostalCode != postalCode) db.offerDao().deleteAll()
                    db.offerDao().storeRefresh(offers, successes.flatMap { it.second.unavailableRetailers(it.first.id) })
                }
                secureStore.put("offer_postal_code", postalCode)
                de.lesecuritae.korbuino.notifications.NativeWatchSync.afterSuccessfulSync(
                    db, secureStore, providers,
                    postalCode, citySlug, NetworkClientFactory.create(applicationContext),
                )
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
                if (runAttemptCount < 2) Result.retry() else Result.failure()
            },
        )
    }
}
