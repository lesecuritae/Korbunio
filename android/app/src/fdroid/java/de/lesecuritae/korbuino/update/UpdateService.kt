package de.lesecuritae.korbuino.update

import android.content.Context
import android.content.Intent
import java.io.File

/** No HTTP, APK downloads or installer intents in the F-Droid distribution. */
@Suppress("UNUSED_PARAMETER")
class UpdateService(context: Context) {
    fun check(): UpdateInfo? = null
    fun download(info: UpdateInfo): File = error("Updates werden über F-Droid installiert")
    fun install(file: File): Intent = error("Updates werden über F-Droid installiert")

    companion object {
        fun isNewerVersion(remote: String, installed: String): Boolean =
            UpdateVersions.isNewerVersion(remote, installed)
    }
}
