package de.lesecuritae.korbuino.data

import androidx.room.*

@Entity(tableName = "watch_notification_receipts")
data class WatchNotificationReceipt(
    @PrimaryKey val receiptKey: String,
    val leaseUntil: Long,
    val attempts: Int,
    val submittedAt: Long? = null,
    val owner: String,
)

/** A lease prevents a worker and manual refresh from publishing the same hit together. */
@Dao
interface WatchNotificationDao {
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(receipt: WatchNotificationReceipt): Long

    @Query("UPDATE watch_notification_receipts SET owner=:owner, leaseUntil=:until, attempts=attempts+1 WHERE receiptKey=:key AND submittedAt IS NULL AND leaseUntil<=:now AND attempts<3")
    suspend fun acquire(key: String, owner: String, now: Long, until: Long): Int

    @Transaction
    suspend fun claim(key: String, owner: String, now: Long): Boolean {
        insert(WatchNotificationReceipt(key, 0, 0, owner = ""))
        return acquire(key, owner, now, now + 120_000) == 1
    }

    @Query("UPDATE watch_notification_receipts SET submittedAt=:now, leaseUntil=0 WHERE receiptKey=:key AND owner=:owner AND submittedAt IS NULL")
    suspend fun submitted(key: String, owner: String, now: Long)

    @Query("UPDATE watch_notification_receipts SET leaseUntil=:retryAt WHERE receiptKey=:key AND owner=:owner AND submittedAt IS NULL")
    suspend fun failed(key: String, owner: String, retryAt: Long)
}
