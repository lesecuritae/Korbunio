package de.lesecuritae.korbuino.security

import java.net.URI

/** Restricts interactive anti-bot pages to known retailer hosts. */
object ChallengePolicy {
    private val allowedHosts = setOf(
        "rewe.de", "www.rewe.de", "globus.de", "www.globus.de",
        "aldi-nord.de", "www.aldi-nord.de", "aldi-sued.de", "www.aldi-sued.de",
        "kaufland.de", "filiale.kaufland.de", "rossmann.de", "www.rossmann.de",
        "mueller.de", "www.mueller.de", "holab.de", "www.holab.de",
        "netto.de", "www.netto.de", "netto-online.de", "www.netto-online.de",
        "dm.de", "www.dm.de", "marktguru.de", "www.marktguru.de",
        "challenges.cloudflare.com", "google.com", "www.google.com",
        "gstatic.com", "www.gstatic.com", "hcaptcha.com", "www.hcaptcha.com",
        "newassets.hcaptcha.com",
    )

    fun isAllowed(raw: String): Boolean {
        val uri = runCatching { URI(raw) }.getOrNull() ?: return false
        val host = uri.host?.lowercase() ?: return false
        return uri.scheme.equals("https", ignoreCase = true) && allowedHosts.any { host == it || host.endsWith(".$it") }
    }
}
