package de.lesecuritae.korbuino.providers

/**
 * One-shot handoff for a user-rendered Müller page.
 *
 * Müller serves the offer catalogue through client-side rendering and may
 * deny the background HTTP client while allowing a normal WebView.  The
 * WebView publishes only the rendered document, never cookies or credentials,
 * and the provider consumes it once in the same app process.
 */
object MuellerRenderedPageStore {
    private const val MAX_HTML_BYTES = 4 * 1024 * 1024
    private const val MAX_AGE_MS = 10 * 60 * 1000L

    private data class Entry(val html: String, val createdAt: Long)

    @Volatile
    private var entry: Entry? = null

    @Synchronized
    fun publish(html: String): Boolean {
        val value = html.trim()
        if (value.isBlank() || value.toByteArray(Charsets.UTF_8).size > MAX_HTML_BYTES) return false
        entry = Entry(value, System.currentTimeMillis())
        return true
    }

    @Synchronized
    fun consume(): String? {
        val current = entry
        entry = null
        if (current == null || System.currentTimeMillis() - current.createdAt > MAX_AGE_MS) return null
        return current.html
    }

    @Synchronized
    fun clear() {
        entry = null
    }
}
