package de.lesecuritae.korbuino

import de.lesecuritae.korbuino.push.PushText
import de.lesecuritae.korbuino.push.ServerPushRegistration
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PushSupportTest {
    @Test fun messageTextIsShownAsSentWithTitleFromFirstLine() {
        val text = PushText.from("Korbuino: Kong im Angebot\nLidl: Kong 0,49 € (02.–07.11.)".toByteArray())
        assertEquals("Korbuino: Kong im Angebot" to "Lidl: Kong 0,49 € (02.–07.11.)", PushText.split(text))
    }

    @Test fun singleLineGetsDefaultTitle() {
        assertEquals("Korbuino" to "Lidl: Kong 0,49 €", PushText.split(PushText.from("Lidl: Kong 0,49 €".toByteArray())))
    }

    @Test fun controlCharactersAreDroppedAndLengthIsBounded() {
        val text = PushText.from(("a\u0000b\u0007" + "x".repeat(2000)).toByteArray())
        assertTrue(text.length == PushText.MAX_LENGTH && text.startsWith("abx"))
    }

    @Test fun emptyMessageFallsBack() {
        assertEquals(PushText.FALLBACK, PushText.from("  \u0000 ".toByteArray()))
    }

    @Test fun putCarriesEndpointAndBearerToken() {
        val request = ServerPushRegistration.request("https://korbunio.example/", "tok", "https://cloud.example/index.php/apps/uppush/push/abc")!!
        assertEquals("PUT", request.method)
        assertEquals("https://korbunio.example/api/v1/notify", request.url.toString())
        assertEquals("Bearer tok", request.header("Authorization"))
        val buffer = okio.Buffer().also { request.body!!.writeTo(it) }
        assertEquals("""{"url":"https://cloud.example/index.php/apps/uppush/push/abc"}""", buffer.readUtf8())
    }

    @Test fun nullEndpointDeletesAndBadServerUrlIsRefused() {
        assertEquals("DELETE", ServerPushRegistration.request("https://korbunio.example", "", null)!!.method)
        assertNull(ServerPushRegistration.request("kein url", "", "https://x.example/p"))
        assertNull(ServerPushRegistration.request("", "", "https://x.example/p").also { }) 
    }

    @Test fun tokenWithLineBreakIsNotSent() {
        val request = ServerPushRegistration.request("https://korbunio.example", "a\nb", "https://x.example/p")!!
        assertNull(request.header("Authorization"))
    }
}
