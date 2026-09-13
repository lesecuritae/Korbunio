package de.lesecuritae.korbuino.providers

import android.content.Context
import android.os.Build
import android.webkit.CookieManager
import com.google.net.cronet.okhttptransport.CronetInterceptor
import com.google.android.gms.security.ProviderInstaller
import okhttp3.OkHttpClient
import org.chromium.net.CronetEngine
import org.conscrypt.Conscrypt
import java.security.Security
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
        if (!supportsCronetTransport(Build.VERSION.SDK_INT)) installLegacyTlsProvider(context)

        // Discovering Play Services can block. All providers execute their HTTP
        // calls on IO; initialize Chromium there, never while creating the UI.
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

        // Keep the legacy path free of Cronet interception. Several retailer
        // CDNs use certificate chains that the original Android 8/9 provider
        // cannot validate. Verification remains enabled with an updated TLS
        // provider from Play Services or the bundled Conscrypt fallback.
        if (!supportsCronetTransport(Build.VERSION.SDK_INT)) {
            return base.build()
        }

        val transport by lazy {
            runCatching {
                val engine = CronetEngine.Builder(context)
                    .enableHttp2(true)
                    .enableQuic(true)
                    .build()
                CronetInterceptor.newBuilder(engine).build()
            }.getOrNull()
        }
        return base.addInterceptor { chain ->
            transport?.intercept(chain) ?: chain.proceed(chain.request())
        }.build()
    }

    /**
     * The embedded Cronet adapter cannot complete modern certificate chains
     * reliably on the oldest supported Android releases. OkHttp uses the
     * platform trust store there and keeps full certificate verification.
     */
    internal fun supportsCronetTransport(sdkInt: Int): Boolean = sdkInt >= Build.VERSION_CODES.Q

    private fun installLegacyTlsProvider(context: Context) {
        val installedByPlayServices = runCatching {
            ProviderInstaller.installIfNeeded(context)
        }.isSuccess
        if (!installedByPlayServices && Security.getProvider("Conscrypt") == null) {
            Security.insertProviderAt(Conscrypt.newProvider(), 1)
        }
    }
}
