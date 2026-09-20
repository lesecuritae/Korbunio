package de.lesecuritae.korbuino

import android.content.Context
import android.os.Build
import android.util.Log
import java.io.File
import java.time.Instant

/**
 * Keeps the last crash so it can be shown (and copied or shared) at the next start.
 *
 * Phones without Google services (GrapheneOS, for example) have no crash reporting built in, and a crash
 * often leaves nothing to read without a computer. The report holds only technical facts: the error with its
 * stack trace, the app version, the Android version and the device model. No offers, no shopping list, no
 * postal code.
 */
object CrashReporter {
    private const val FILE = "crash-report.txt"
    private const val MAX_CHARS = 20_000

    fun install(context: Context) {
        val app = context.applicationContext
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            runCatching { File(app.filesDir, FILE).writeText(describe(thread.name, error, BuildConfig.VERSION_NAME)) }
            previous?.uncaughtException(thread, error)
        }
    }

    fun describe(threadName: String, error: Throwable, appVersion: String): String = buildString {
        appendLine("Korbuino $appVersion")
        appendLine("Zeit: ${Instant.now()}")
        appendLine("Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}), ${Build.MANUFACTURER} ${Build.MODEL}")
        appendLine("Thread: $threadName")
        appendLine()
        append(Log.getStackTraceString(error))
    }.take(MAX_CHARS)

    fun read(context: Context): String? =
        runCatching { File(context.filesDir, FILE).takeIf { it.isFile }?.readText()?.takeIf { it.isNotBlank() } }.getOrNull()

    fun clear(context: Context) {
        runCatching { File(context.filesDir, FILE).delete() }
    }
}
