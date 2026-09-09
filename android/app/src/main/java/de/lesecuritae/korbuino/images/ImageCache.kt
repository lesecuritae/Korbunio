package de.lesecuritae.korbuino.images

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.security.MessageDigest
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

class ImageCache(private val context: Context, private val http: OkHttpClient = OkHttpClient()) {
    // filesDir survives normal app cache eviction and is included in the
    // app's private storage without exposing images to other applications.
    private val directory get() = File(context.filesDir, "product-images").also { it.mkdirs() }

    suspend fun get(url: String, maxAgeMs: Long = 30L * 24 * 60 * 60 * 1000): File? = withContext(Dispatchers.IO) {
        val file = File(directory, sha256(url))
        if (!file.exists() || System.currentTimeMillis() - file.lastModified() > maxAgeMs) return@withContext null
        file
    }

    suspend fun download(url: String): File? = withContext(Dispatchers.IO) {
        if (url.toHttpUrlOrNull()?.scheme != "https") return@withContext null
        val request = Request.Builder().url(url).header("User-Agent", "Korbuino/0.1").build()
        runCatching {
            http.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@use null
                val body = response.body ?: return@use null
                val file = File(directory, sha256(url))
                body.byteStream().use { input -> file.outputStream().use { output -> input.copyTo(output) } }
                file
            }
        }.getOrNull()
    }

    suspend fun evictOlderThan(maxAgeMs: Long) = withContext(Dispatchers.IO) {
        val cutoff = System.currentTimeMillis() - maxAgeMs
        directory.listFiles()?.forEach { if (it.lastModified() < cutoff) it.delete() }
    }

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray()).joinToString("") { "%02x".format(it) }
}
