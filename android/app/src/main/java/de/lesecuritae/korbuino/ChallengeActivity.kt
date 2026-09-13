package de.lesecuritae.korbuino

import android.app.Activity
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import de.lesecuritae.korbuino.security.ChallengePolicy
import de.lesecuritae.korbuino.providers.MuellerRenderedPageStore
import de.lesecuritae.korbuino.providers.RenderedPageStore
import org.json.JSONTokener

/** User-mediated anti-bot step; no CAPTCHA solving or bypass is automated. */
class ChallengeActivity : Activity() {
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        val url = intent.getStringExtra(EXTRA_URL).orEmpty()
        if (!ChallengePolicy.isAllowed(url)) {
            setResult(RESULT_CANCELED)
            finish()
            return
        }
        val isMueller = url.contains("mueller.de", ignoreCase = true)
        val isAldiSouth = url.contains("aldi-sued.de", ignoreCase = true)
        val isRossmann = url.contains("rossmann.de", ignoreCase = true)
        val supportsRenderedHandoff = isMueller || isAldiSouth || isRossmann
        var doneButton: Button? = null
        val web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.setSupportMultipleWindows(false)
            CookieManager.getInstance().setAcceptCookie(true)
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView, pageUrl: String) {
                    doneButton?.isEnabled = true
                }
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean =
                    !ChallengePolicy.isAllowed(request.url.toString())
            }
        }
        lateinit var webView: WebView
        val done = Button(this).apply {
            doneButton = this
            isEnabled = false
            text = when {
                isMueller -> "Müller-Angebote übernehmen"
                isAldiSouth -> "ALDI Süd-Angebote übernehmen"
                isRossmann -> "Rossmann-Angebote übernehmen"
                else -> "Bestätigung fertig – erneut versuchen"
            }
            setOnClickListener {
                CookieManager.getInstance().flush()
                if (supportsRenderedHandoff) {
                    webView.evaluateJavascript("document.documentElement.outerHTML") { encoded ->
                        val html = runCatching { JSONTokener(encoded).nextValue() as? String }.getOrNull()
                        if (isMueller && !html.isNullOrBlank()) MuellerRenderedPageStore.publish(html)
                        if (!html.isNullOrBlank()) RenderedPageStore.publish(url, html)
                        setResult(RESULT_OK)
                        finish()
                    }
                } else {
                    setResult(RESULT_OK)
                    finish()
                }
            }
        }
        val note = TextView(this).apply {
            text = if (supportsRenderedHandoff) {
                "Die Händlerseite wird direkt im Browser geladen. Wenn die Angebote sichtbar sind, tippe auf „${when { isMueller -> "Müller"; isRossmann -> "Rossmann"; else -> "ALDI Süd" }}-Angebote übernehmen“. Korbuino löst keine CAPTCHAs automatisch."
            } else {
                "Die Händlerseite wird direkt im Browser geladen. Wenn die Bestätigung abgeschlossen ist, tippe auf „Bestätigung fertig – erneut versuchen“. Korbuino löst keine CAPTCHAs automatisch."
            }
            setPadding(24, 18, 24, 18)
        }
        webView = web
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(note)
            addView(web, LinearLayout.LayoutParams(-1, 0, 1f))
            addView(done)
        })
        web.loadUrl(url)
    }

    companion object {
        private const val EXTRA_URL = "challenge_url"
        fun intent(activity: Activity, url: String) = android.content.Intent(activity, ChallengeActivity::class.java).putExtra(EXTRA_URL, url)
    }
}
