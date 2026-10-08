package de.lesecuritae.korbuino.providers

import android.content.Context
import android.os.Build
import android.webkit.CookieManager
import okhttp3.OkHttpClient
import org.conscrypt.Conscrypt
import java.security.Security
import java.util.concurrent.TimeUnit

/** Free transport only: OkHttp and bundled Conscrypt, with normal TLS validation. */
object NetworkClientFactory {
    @Volatile private var shared: OkHttpClient? = null

    @Suppress("UNUSED_PARAMETER")
    fun create(context: Context): OkHttpClient = shared ?: synchronized(this) {
        shared ?: build(Build.VERSION.SDK_INT) { url ->
            runCatching { CookieManager.getInstance().getCookie(url) }.getOrNull()
        }.also { shared = it }
    }

    internal fun build(sdkInt: Int, cookieHeader: (String) -> String?): OkHttpClient {
        // Android 8/9 need an up-to-date TLS implementation. This uses the
        // bundled free provider and does not discover or download Play Services.
        if (sdkInt < 29 && Security.getProvider("Conscrypt") == null) {
            Security.insertProviderAt(Conscrypt.newProvider(), 1)
        }
        return OkHttpClient.Builder()
            .callTimeout(45, TimeUnit.SECONDS)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .followRedirects(true)
            .followSslRedirects(true)
            .addInterceptor { chain ->
                val request = chain.request()
                val cookies = cookieHeader(request.url.toString())
                val enriched = if (cookies.isNullOrBlank()) request
                    else request.newBuilder().header("Cookie", cookies).build()
                chain.proceed(enriched)
            }
            .build()
    }
}
