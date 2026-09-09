package de.lesecuritae.korbuino.providers

import android.content.Context
import com.google.net.cronet.okhttptransport.CronetInterceptor
import okhttp3.OkHttpClient
import org.chromium.net.CronetEngine
import java.util.concurrent.TimeUnit

/**
 * Uses the Chromium transport when the device provides it and falls back to
 * the platform OkHttp stack. Both paths retain normal certificate validation.
 */
object NetworkClientFactory {
    fun create(context: Context): OkHttpClient {
        val base = OkHttpClient.Builder()
            .callTimeout(45, TimeUnit.SECONDS)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .followRedirects(true)
            .followSslRedirects(true)
        return runCatching {
            val engine = CronetEngine.Builder(context.applicationContext)
                .enableHttp2(true)
                .enableQuic(true)
                .build()
            base.addInterceptor(CronetInterceptor.newBuilder(engine).build()).build()
        }.getOrElse { base.build() }
    }
}
