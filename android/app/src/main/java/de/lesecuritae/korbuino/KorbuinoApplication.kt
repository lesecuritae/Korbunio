package de.lesecuritae.korbuino

import android.app.Application
import dagger.hilt.android.HiltAndroidApp

@HiltAndroidApp
class KorbuinoApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        CrashReporter.install(this)
    }
}
