package de.lesecuritae.korbuino

import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** Offer validity as a Europe/Berlin calendar date, whatever form a provider stored (plain date or UTC instant). */
object BerlinDate {
    private val BERLIN: ZoneId = ZoneId.of("Europe/Berlin")
    private val COMPACT_OFFSET = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss[.SSS]Z")

    /** "2026-10-25" or an instant ("...Z", "...+0000", "...+02:00") -> Berlin "yyyy-MM-dd"; null if blank or unparseable. */
    fun toLocalDate(value: String?): String? {
        val text = value?.trim().orEmpty()
        if (text.isEmpty()) return null
        if (text.length == 10) return runCatching { LocalDate.parse(text).toString() }.getOrNull()
        val instant = runCatching { Instant.parse(text) }.getOrNull()
            ?: runCatching { OffsetDateTime.parse(text).toInstant() }.getOrNull()
            ?: runCatching { OffsetDateTime.parse(text, COMPACT_OFFSET).toInstant() }.getOrNull()
        return instant?.atZone(BERLIN)?.toLocalDate()?.toString()
    }
}
