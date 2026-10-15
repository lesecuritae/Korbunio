package de.lesecuritae.korbuino.notifications

import androidx.room.withTransaction
import de.lesecuritae.korbuino.data.KorbuinoDatabase
import de.lesecuritae.korbuino.providers.*
import de.lesecuritae.korbuino.security.SecureStore
import okhttp3.OkHttpClient
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.TemporalAdjusters
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive

/** Shared by foreground and WorkManager. Only saved active watches request previews. */
object NativeWatchSync {
    suspend fun afterSuccessfulSync(
        database: KorbuinoDatabase, secureStore: SecureStore, providers: List<RetailerProvider>,
        postalCode: String, citySlug: String?, http: OkHttpClient = OkHttpClient(),
    ): EvaluationResult {
        fun regionStillCurrent() = secureStore.get("offer_postal_code") == postalCode && secureStore.get("postal_code") == postalCode
        if (!regionStillCurrent()) return EvaluationResult()
        refreshUpcoming(database, providers, postalCode, citySlug, ::regionStillCurrent)
        if (!regionStillCurrent()) return EvaluationResult()
        return WatchNotificationService(database, secureStore, http).evaluate(postalCode)
    }

    suspend fun refreshUpcoming(database: KorbuinoDatabase, providers: List<RetailerProvider>, postalCode: String, citySlug: String?, regionStillCurrent: () -> Boolean = { true }) {
        val watches = database.favoriteDao().all().filter {
            it.includeNextWeek && it.query.isNotBlank() && (it.postalCode.isBlank() || it.postalCode == postalCode)
        }
        if (watches.isEmpty()) return
        val from = LocalDate.now(ZoneId.of("Europe/Berlin"))
            .with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY)).plusWeeks(1)
        val until = from.plusDays(6)
        providers.filter { provider -> watches.any { watch ->
            val retailers = runCatching { Json.parseToJsonElement(watch.preferredRetailerIdsJson).jsonArray.map { it.jsonPrimitive.content } }.getOrElse { listOf("invalid") }
            retailers.isEmpty() || provider.id in retailers
        } }.forEach { provider ->
            // An unsupported preview returns no dated next-week offers; never redate current results.
            val result = runCatching { provider.fetch(RetailerRequest(postalCode, citySlug = citySlug, week = OfferWeek.NEXT)) }.getOrNull() ?: return@forEach
            if (!regionStillCurrent()) return
            val offers = result.offers.filter { offer ->
                val start = offer.validFrom?.let { runCatching { LocalDate.parse(it) }.getOrNull() }
                val end = offer.validUntil?.let { runCatching { LocalDate.parse(it) }.getOrNull() }
                start != null && end != null && start <= until && end >= from && end >= start
            }
            if (offers.isEmpty()) {
                database.offerDao().storeWeekRefresh(provider.id, from.toString(), until.toString(), emptyList())
                return@forEach
            }
            if (ProviderImportPolicy.rejectionReason(provider.id, offers.size) != null) return@forEach
            // Canonicalize against the durable product index as well as this response.
            database.withTransaction {
                if (!regionStillCurrent()) return@withTransaction
                val canonical = database.productDao().all().associateBy { it.normalizedKey }.toMutableMap()
                val ids = result.products.associate { product ->
                    val existing = canonical.getOrPut(product.normalizedKey) { product }
                    product.id to existing.id
                }
                database.productDao().upsertAll(result.products.map { canonical.getValue(it.normalizedKey) }.distinctBy { it.id })
                val existingOffers = database.offerDao().all()
                val dated = offers.map { offer ->
                    val suffix = "@${offer.validFrom}:${offer.validUntil}"
                    val existing = existingOffers.firstOrNull {
                        it.retailerId == offer.retailerId && it.externalId.removeSuffix(suffix) == offer.externalId &&
                            it.validFrom == offer.validFrom && it.validUntil == offer.validUntil
                    }
                    offer.copy(id = existing?.id ?: (offer.id + suffix), externalId = existing?.externalId ?: (offer.externalId + suffix),
                        productId = ids[offer.productId] ?: offer.productId)
                }
                database.offerDao().storeWeekRefresh(provider.id, from.toString(), until.toString(), dated)
            }
        }
    }
}
