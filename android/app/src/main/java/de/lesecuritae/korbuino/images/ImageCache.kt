package de.lesecuritae.korbuino.images

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.security.MessageDigest
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

class ImageCache(private val context: Context, private val http: OkHttpClient = OkHttpClient()) {
    companion object {
        @Volatile private var shared: ImageCache? = null
        fun shared(context: Context): ImageCache = shared ?: synchronized(this) {
            shared ?: ImageCache(context.applicationContext,
                de.lesecuritae.korbuino.providers.NetworkClientFactory.create(context.applicationContext))
                .also { shared = it }
        }
    }

    private val downloads = Semaphore(4)

    /** Decode bounded thumbnails, including files cached by older app versions. */
    suspend fun thumbnail(path: String?, url: String?, referer: String?): Bitmap? = withContext(Dispatchers.IO) {
        fun decode(file: File): Bitmap? {
            val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(file.path, options)
            if (options.outWidth <= 0 || options.outHeight <= 0) return null
            options.inJustDecodeBounds = false
            options.inSampleSize = 1
            while (options.outWidth / options.inSampleSize > 512 || options.outHeight / options.inSampleSize > 512) {
                options.inSampleSize *= 2
            }
            return BitmapFactory.decodeFile(file.path, options)
        }
        val cached = path?.let(::File)?.takeIf { it.isFile } ?: url?.let { get(it, Long.MAX_VALUE) }
        cached?.let { file ->
            decode(file)?.let { return@withContext it }
            // Broken images from older versions must not poison the cache forever.
            if (file.parentFile?.canonicalFile == directory.canonicalFile) file.delete()
        }
        url?.let { download(it, referer) }?.let(::decode)
    }

    // filesDir survives normal app cache eviction and is included in the
    // app's private storage without exposing images to other applications.
    private val directory get() = File(context.filesDir, "product-images").also { it.mkdirs() }

    suspend fun get(url: String, maxAgeMs: Long = 30L * 24 * 60 * 60 * 1000): File? = withContext(Dispatchers.IO) {
        val file = File(directory, sha256(url))
        if (!file.exists() || file.length() == 0L || System.currentTimeMillis() - file.lastModified() > maxAgeMs) return@withContext null
        file
    }

    suspend fun download(url: String, referer: String? = null): File? = withContext(Dispatchers.IO) {
        if (url.toHttpUrlOrNull()?.scheme != "https") return@withContext null
        get(url)?.let { return@withContext it }
        val requestBuilder = Request.Builder().url(url).header("User-Agent", "Korbuino/0.1").header("Accept", "image/webp,image/png,image/jpeg,image/*;q=0.8")
        val host = url.toHttpUrlOrNull()?.host.orEmpty()
        val safeReferer = referer?.takeIf { it.startsWith("https://") }
            ?: if (host.endsWith("mg2de.b-cdn.net")) "https://www.marktguru.de/" else null
        if (safeReferer != null) requestBuilder.header("Referer", safeReferer)
        downloads.withPermit {
            try {
                http.newCall(requestBuilder.build()).execute().use { response ->
                    if (!response.isSuccessful) {
                        android.util.Log.w("KorbuinoImages", "Image HTTP ${response.code} from $host")
                        return@use null
                    }
                    val body = response.body ?: return@use null
                    val file = File(directory, sha256(url))
                    if (body.contentLength() > 8L * 1024 * 1024) return@use null
                    val temporary = File.createTempFile("image-", ".part", directory)
                    try {
                        body.byteStream().use { input -> temporary.outputStream().use { output ->
                            val buffer = ByteArray(8192)
                            var total = 0L
                            while (true) {
                                val count = input.read(buffer)
                                if (count == -1) break
                                total += count
                                check(total <= 8L * 1024 * 1024) { "Image exceeds size limit" }
                                output.write(buffer, 0, count)
                            }
                        } }
                        val bounds = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
                        android.graphics.BitmapFactory.decodeFile(temporary.path, bounds)
                        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
                            android.util.Log.w("KorbuinoImages", "Unsupported or invalid image from $host")
                            return@use null
                        }
                        check(temporary.renameTo(file)) { "Image cache write failed" }
                        file
                    } finally {
                        temporary.delete()
                    }
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: java.io.IOException) {
                android.util.Log.w("KorbuinoImages", "Image transport ${error.javaClass.simpleName} from $host")
                null
            } catch (_: IllegalStateException) {
                null
            }
        }
    }

    suspend fun evictOlderThan(maxAgeMs: Long) = withContext(Dispatchers.IO) {
        val cutoff = System.currentTimeMillis() - maxAgeMs
        directory.listFiles()?.forEach { if (it.lastModified() < cutoff) it.delete() }
    }

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray()).joinToString("") { "%02x".format(it) }
}
