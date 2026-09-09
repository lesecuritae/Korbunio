package de.lesecuritae.korbuino.providers

/**
 * Short-lived handoff for pages rendered by the user's WebView. It stores
 * only the rendered document, never cookies or credentials, and is consumed
 * once by the matching provider.
 */
object RenderedPageStore {
    private const val MAX_HTML_BYTES = 4 * 1024 * 1024
    private const val MAX_AGE_MS = 10 * 60 * 1000L

    private data class Entry(val html: String, val createdAt: Long)
    private val entries = mutableMapOf<String, Entry>()

    @Synchronized
    fun publish(url: String, html: String): Boolean {
        val value = html.trim()
        if (url.isBlank() || value.isBlank() || value.toByteArray(Charsets.UTF_8).size > MAX_HTML_BYTES) return false
        entries[url] = Entry(value, System.currentTimeMillis())
        return true
    }

    @Synchronized
    fun consume(url: String): String? {
        val current = entries.remove(url) ?: return null
        if (System.currentTimeMillis() - current.createdAt > MAX_AGE_MS) return null
        return current.html
    }

    @Synchronized
    fun clear() = entries.clear()
}
