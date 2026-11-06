package de.lesecuritae.korbuino.push

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

/** Text of a push message: the server sends plain text (title and offer), so show it as it is. */
object PushText {
    const val MAX_LENGTH = 500
    const val FALLBACK = "Neue Meldung von Korbuino"

    fun from(content: ByteArray): String {
        val cleaned = content.toString(Charsets.UTF_8)
            .filter { it == '\n' || !it.isISOControl() }
            .trim()
            .take(MAX_LENGTH)
        return cleaned.ifBlank { FALLBACK }
    }

    /** First line is the title when the message has several lines; otherwise "Korbuino". */
    fun split(text: String): Pair<String, String> {
        val lines = text.lines()
        return if (lines.size > 1 && lines.first().length <= 80) lines.first() to lines.drop(1).joinToString("\n").trim()
        else "Korbuino" to text
    }
}

/** Tells the own Korbuino server where to push to (PUT) or to stop (DELETE) via the existing notify route. */
object ServerPushRegistration {
    private const val PATH = "api/v1/notify"

    /** @return null when [serverUrl] is not a usable http(s) address; [endpoint] null means unregister. */
    fun request(serverUrl: String, token: String, endpoint: String?): Request? {
        val base = serverUrl.trim().toHttpUrlOrNull() ?: return null
        val url = base.newBuilder().addPathSegments(PATH).build()
        val builder = Request.Builder().url(url).header("Accept", "application/json")
        if (token.isNotBlank() && token.none { it == '\r' || it == '\n' }) builder.header("Authorization", "Bearer ${token.trim()}")
        return if (endpoint == null) {
            builder.delete().build()
        } else {
            val body = buildJsonObject { put("url", endpoint) }.toString().toRequestBody("application/json; charset=utf-8".toMediaType())
            builder.put(body).build()
        }
    }
}
