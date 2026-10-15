package de.lesecuritae.korbuino.data

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

class WatchReceiptPersistenceTest {
    @Test fun parallelPublishClaimsAndRestartDoNotDuplicateSuccessfulReceipt() = runBlocking {
        val context=ApplicationProvider.getApplicationContext<android.content.Context>()
        val name="issue58-watch-receipts.db"
        context.deleteDatabase(name)
        fun open()=Room.databaseBuilder(context,KorbuinoDatabase::class.java,name).build()
        var db=open()
        try {
            val dao=db.watchNotificationDao()
            val winners=coroutineScope { (0 until 8).map { index -> async(Dispatchers.IO) {
                index to dao.claim("one-event","worker-$index",1000)
            } }.awaitAll().filter { it.second } }
            assertEquals(1,winners.size)
            val first="worker-${winners.single().first}"
            assertFalse(dao.claim("one-event","too-early",2000))
            assertTrue(dao.claim("one-event","new-owner",122000))
            dao.submitted("one-event",first,122001) // stale owner cannot acknowledge.
            assertFalse(dao.claim("one-event","third",123000))
            dao.submitted("one-event","new-owner",122002)
            db.close()
            db=open()
            assertFalse(db.watchNotificationDao().claim("one-event","after-restart",999999))
        } finally { db.close(); context.deleteDatabase(name) }
    }
}
