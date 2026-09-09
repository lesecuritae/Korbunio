package de.lesecuritae.korbuino.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.contentOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.security.MessageDigest

data class UpdateInfo(val tag: String, val version: String, val apkUrl: String, val sha256: String?, val releaseUrl: String?)

/** GitHub-release updater for the native APK. Android still performs signature validation on install. */
class UpdateService(
    private val context: Context,
    private val http: OkHttpClient = OkHttpClient(),
    private val repository: String = "lesecuritae/Korbunio",
) {
    private val json = Json { ignoreUnknownKeys = true }

    fun check(): UpdateInfo? {
        val request = Request.Builder().url("https://api.github.com/repos/$repository/releases/latest")
            .header("Accept", "application/vnd.github+json").header("User-Agent", "Korbuino-Android").build()
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return null
            val root = json.parseToJsonElement(response.body?.string().orEmpty()).jsonObject
            val tag = root["tag_name"]?.jsonPrimitive?.contentOrNull ?: return null
            val version = tag.removePrefix("v")
            val installed = context.packageManager
                .getPackageInfo(context.packageName, 0)
                .versionName
                .orEmpty()
            if (!isNewerVersion(version, installed)) return null
            val apk = root["assets"]?.jsonArray.orEmpty().firstOrNull { asset ->
                asset.jsonObject["name"]?.jsonPrimitive?.contentOrNull?.endsWith(".apk") == true
            }?.jsonObject ?: return null
            return UpdateInfo(
                tag = tag,
                version = version,
                apkUrl = apk["browser_download_url"]?.jsonPrimitive?.contentOrNull ?: return null,
                sha256 = findDigest(root, apk["name"]?.jsonPrimitive?.contentOrNull.orEmpty()),
                releaseUrl = root["html_url"]?.jsonPrimitive?.contentOrNull,
            )
        }
    }

    fun download(info: UpdateInfo): File {
        require(info.apkUrl.startsWith("https://")) { "Update-URL muss HTTPS verwenden" }
        val dir = File(context.cacheDir, "updates").also { it.mkdirs() }
        val file = File(dir, "korbuino-${info.version}.apk")
        val request = Request.Builder().url(info.apkUrl).header("User-Agent", "Korbuino-Android").build()
        http.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "APK-Download HTTP ${response.code}" }
            response.body?.byteStream()?.use { input -> file.outputStream().use { output -> input.copyTo(output) } }
        }
        info.sha256?.let { expected ->
            val actual = sha256(file)
            check(actual.equals(expected, ignoreCase = true)) { "APK-Prüfsumme stimmt nicht" }
        }
        return file
    }

    fun install(file: File): Intent {
        val uri: Uri = FileProvider.getUriForFile(context, "de.lesecuritae.korbuino.fileprovider", file)
        return Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        }
    }

    private fun findDigest(root: JsonObject, apkName: String): String? {
        val assets = root["assets"]?.jsonArray ?: return null
        val sidecar = assets.firstOrNull { it.jsonObject["name"]?.jsonPrimitive?.contentOrNull == "$apkName.sha256" }
            ?: assets.firstOrNull { it.jsonObject["name"]?.jsonPrimitive?.contentOrNull?.endsWith(".sha256") == true }
            ?: return null
        val url = sidecar.jsonObject["browser_download_url"]?.jsonPrimitive?.contentOrNull ?: return null
        val request = Request.Builder().url(url).header("User-Agent", "Korbuino-Android").build()
        return http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) null else response.body?.string()?.trim()?.split(Regex("\\s+"))?.firstOrNull()
        }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(8192)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    companion object {
        /** Compare dotted numeric release versions without treating 0.1.10 as 0.1.2. */
        fun isNewerVersion(remote: String, installed: String): Boolean {
            fun parts(value: String): List<Int> = value.removePrefix("v")
                .split('.', '-', '+')
                .map { it.toIntOrNull() ?: 0 }
                .take(4)
                .let { values -> values + List(4 - values.size) { 0 } }
            return parts(remote).zip(parts(installed)).firstOrNull { (r, i) -> r != i }
                ?.let { (r, i) -> r > i } ?: false
        }
    }
}
