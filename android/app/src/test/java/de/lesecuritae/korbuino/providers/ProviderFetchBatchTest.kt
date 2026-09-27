package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.atomic.AtomicInteger

class ProviderFetchBatchTest {
    @Test fun `limits concurrent providers and preserves result order`() = runBlocking {
        val active = AtomicInteger()
        val peak = AtomicInteger()
        val providers = (0 until 16).map { index ->
            provider(index) {
                val count = active.incrementAndGet()
                peak.accumulateAndGet(count, ::maxOf)
                try {
                    delay(20)
                    ProviderResult(emptyList(), emptyList())
                } finally {
                    active.decrementAndGet()
                }
            }
        }

        val results = fetchProviderBatch(providers, RetailerRequest("50677"))

        assertEquals(providers.map { it.id }, results.map { it.first.id })
        assertTrue(results.all { it.second.isSuccess })
        assertTrue("peak=${peak.get()}", peak.get() <= 4)
        assertTrue("requests should run concurrently", peak.get() > 1)
        assertEquals(0, active.get())
    }

    @Test fun `one provider failure does not discard other results`() = runBlocking {
        val providers = listOf(
            provider(0) { throw IllegalStateException("offline") },
            provider(1) { ProviderResult(emptyList(), emptyList()) },
        )

        val results = fetchProviderBatch(providers, RetailerRequest("50677"))

        assertTrue(results[0].second.exceptionOrNull() is IllegalStateException)
        assertTrue(results[1].second.isSuccess)
    }

    @Test(expected = CancellationException::class)
    fun `cancellation is not reported as provider failure`() {
        runBlocking {
            fetchProviderBatch(
                listOf(provider(0) { throw CancellationException("stopped") }),
                RetailerRequest("50677"),
            )
        }
    }

    private fun provider(index: Int, fetch: suspend () -> ProviderResult) = object : RetailerProvider {
        override val id = "provider-$index"
        override val displayName = id
        override suspend fun fetch(request: RetailerRequest) = fetch()
    }
}
