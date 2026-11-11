package de.lesecuritae.korbuino.data

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class OfferRefreshTest {
    /** In-memory query boundary; exercises the real DAO transaction method's deletion policy. */
    private class Dao : OfferDao {
        val rows = linkedMapOf<String, OfferEntity>()
        val deletions = mutableListOf<String>()
        override fun observeAll(): Flow<List<OfferEntity>> = flowOf(rows.values.toList())
        override suspend fun all() = rows.values.toList()
        override suspend fun upsertAll(offers: List<OfferEntity>) { offers.forEach { rows[it.id] = it } }
        override suspend fun deleteCurrentPartition(retailerId: String, sunday: String) { deletions += retailerId; rows.values.removeAll { it.retailerId == retailerId } }
        override suspend fun deleteWeek(retailerId: String, from: String, until: String) { deletions += retailerId; rows.values.removeAll { it.retailerId == retailerId } }
        override suspend fun deleteProvider(retailerId: String) { deletions += retailerId; rows.values.removeAll { it.retailerId == retailerId } }
        override suspend fun deleteAll() { rows.clear() }
    }
    private fun offer(id: String, cents: Int = 199) = OfferEntity(id, "mueller", id,
        externalId = id, priceCents = cents, sourceUrl = "https://example.org", cachedAt = 1)

    @Test fun `partial import updates delivered prices without deleting missing offline rows`() = runTest {
        val dao = Dao()
        dao.upsertAll(listOf(offer("old"), offer("updated")))
        dao.storeRefresh(listOf(offer("updated", 149), offer("new")), preserveRetailers = listOf("mueller"))
        assertEquals(setOf("old", "updated", "new"), dao.rows.keys)
        assertEquals(149, dao.rows.getValue("updated").priceCents)
        assertTrue(dao.deletions.isEmpty())
        dao.storeRefresh(listOf(offer("updated", 129)))
        assertEquals(setOf("updated"), dao.rows.keys)
        assertEquals(listOf("mueller"), dao.deletions)
    }

    @Test fun `confirmed market absence wins and partial next week preserves its old rows`() = runTest {
        val dao = Dao()
        dao.upsertAll(listOf(offer("old")))
        dao.storeWeekRefresh("mueller", "2026-11-16", "2026-11-22", emptyList(), preserveMissing = true)
        assertTrue("old" in dao.rows)
        dao.storeRefresh(emptyList(), unavailableRetailers = listOf("mueller"), preserveRetailers = listOf("mueller"))
        assertTrue(dao.rows.isEmpty())
    }
}
