package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext

/** Blocking retailer HTTP calls must not occupy an unbounded number of IO threads. */
internal suspend fun fetchProviderBatch(
    providers: List<RetailerProvider>,
    request: RetailerRequest,
    maxConcurrent: Int = 4,
): List<Pair<RetailerProvider, Result<ProviderResult>>> = coroutineScope {
    require(maxConcurrent > 0)
    val permits = Semaphore(maxConcurrent)
    providers.map { provider ->
        async {
            permits.withPermit {
                provider to try {
                    Result.success(withContext(Dispatchers.IO) { provider.fetch(request) })
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (error: Exception) {
                    Result.failure(error)
                }
            }
        }
    }.awaitAll()
}
