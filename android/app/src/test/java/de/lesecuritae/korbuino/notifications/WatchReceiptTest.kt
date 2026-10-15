package de.lesecuritae.korbuino.notifications

import de.lesecuritae.korbuino.data.*
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

/** Exercises the lease protocol independently of transport and wall clock. */
class WatchReceiptTest {
    private class Receipts : WatchNotificationDao {
        val rows = mutableMapOf<String, WatchNotificationReceipt>()
        override suspend fun insert(receipt: WatchNotificationReceipt): Long = synchronized(rows) {
            if (rows.containsKey(receipt.receiptKey)) -1 else { rows[receipt.receiptKey] = receipt; 1 }
        }
        override suspend fun acquire(key: String, owner: String, now: Long, until: Long): Int = synchronized(rows) {
            val row = rows[key] ?: return@synchronized 0
            if (row.submittedAt != null || row.leaseUntil > now || row.attempts >= 3) 0
            else { rows[key] = row.copy(owner=owner,leaseUntil=until,attempts=row.attempts+1); 1 }
        }
        override suspend fun submitted(key: String, owner: String, now: Long) {
            synchronized(rows) { rows[key]?.takeIf { it.owner == owner && it.submittedAt == null }?.let { rows[key] = it.copy(submittedAt=now,leaseUntil=0) } }
        }
        override suspend fun failed(key: String, owner: String, retryAt: Long) {
            synchronized(rows) { rows[key]?.takeIf { it.owner == owner && it.submittedAt == null }?.let { rows[key] = it.copy(leaseUntil=retryAt) } }
        }
    }
    @Test fun concurrentClaimsHaveOneWinnerAndSuccessNeverRepeats() = runTest {
        val receipts = Receipts()
        val claims = (1..20).map { async { receipts.claim("key", "$it", 100) } }.awaitAll()
        assertEquals(1, claims.count { it })
        val owner = receipts.rows.getValue("key").owner
        receipts.submitted("key", "stale-worker", 200)
        assertNull(receipts.rows.getValue("key").submittedAt)
        receipts.submitted("key", owner, 200)
        assertFalse(receipts.claim("key", "new", 999_999))
    }
    @Test fun failedAndAbandonedAttemptsAreBoundedAndDelayed() = runTest {
        val receipts = Receipts()
        assertTrue(receipts.claim("key","one",100))
        assertFalse(receipts.claim("key","two",101))
        receipts.failed("key","one",300)
        assertFalse(receipts.claim("key","two",299))
        assertTrue(receipts.claim("key","two",300))
        // A dead worker's lease eventually expires without marking it submitted.
        assertTrue(receipts.claim("key","three",120_301))
        receipts.failed("key","three",120_302)
        assertFalse(receipts.claim("key","four",999_999))
        assertEquals(3,receipts.rows.getValue("key").attempts)
        assertNull(receipts.rows.getValue("key").submittedAt)
    }
}
