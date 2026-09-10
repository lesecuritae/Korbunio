package de.lesecuritae.korbuino.providers

import android.content.Context
import android.webkit.CookieManager
import com.google.net.cronet.okhttptransport.CronetInterceptor
import okhttp3.OkHttpClient
import org.chromium.net.CronetEngine
import java.util.concurrent.TimeUnit

/**
 * Uses the Chromium transport when the device provides it and falls back to
 * the platform OkHttp stack. Both paths retain normal certificate validation.
 */
object NetworkClientFactory {
    @Volatile private var shared: OkHttpClient? = null

    fun create(context: Context): OkHttpClient = shared ?: synchronized(this) {
        shared ?: build(context.applicationContext).also { shared = it }
    }

    private fun build(context: Context): OkHttpClient {
        // Discovering Play Services can block. All providers execute their HTTP
        // calls on IO; initialize Chromium there, never while creating the UI.
        val transport by lazy {
            runCatching {
                val engine = CronetEngine.Builder(context)
                    .enableHttp2(true)
                    .enableQuic(true)
                    .build()
                CronetInterceptor.newBuilder(engine).build()
            }.getOrNull()
        }
        val base = OkHttpClient.Builder()
            .callTimeout(45, TimeUnit.SECONDS)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .followRedirects(true)
            .followSslRedirects(true)
            .addInterceptor { chain ->
                val request = chain.request()
                val cookies = runCatching { CookieManager.getInstance().getCookie(request.url.toString()) }.getOrNull()
                val enriched = if (cookies.isNullOrBlank()) request else request.newBuilder().header("Cookie", cookies).build()
                chain.proceed(enriched)
            }
        return base.addInterceptor { chain ->
            transport?.intercept(chain) ?: chain.proceed(chain.request())
        }.build()
    }
}
