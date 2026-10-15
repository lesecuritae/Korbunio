package de.lesecuritae.korbuino.notifications

import kotlinx.coroutines.test.runTest
import okhttp3.*
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test
import java.net.SocketTimeoutException

class NtfySenderTest {
    private var requests = 0
    private var authorization: String? = null
    private fun client(code: Int = 200, timeout: Boolean = false) = OkHttpClient.Builder().addInterceptor { chain ->
        requests++
        authorization = chain.request().header("Authorization")
        if (timeout) throw SocketTimeoutException()
        Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(code).message("test")
            .body("{}".toResponseBody()).build()
    }.build()

    @Test fun disabledAndUnconfiguredNeverRequest() = runTest {
        val sender = NtfySender(client())
        assertFalse(sender.test(NtfySettings()).submitted)
        assertFalse(sender.test(NtfySettings(true)).submitted)
        assertEquals(0, requests)
    }
    @Test fun validatesUrlWithoutRequest() = runTest {
        val sender = NtfySender(client())
        listOf("http://example.org/topic", "garbage", "https://example.org/", "https://user:secret@example.org/topic", "https://example.org/topic?token=x").forEach {
            assertFalse(sender.test(NtfySettings(true, it)).submitted)
        }
        assertEquals(0, requests)
    }
    @Test fun submitsWithOptionalBearer() = runTest {
        val sender = NtfySender(client())
        assertTrue(sender.test(NtfySettings(true, "https://example.org/test-topic", "abc")).submitted)
        assertEquals("Bearer abc", authorization)
        assertTrue(sender.test(NtfySettings(true, "https://example.org/test-topic")).submitted)
        assertNull(authorization)
        assertEquals(2, requests)
    }
    @Test fun errorsAreActionableAndDoNotExposeTopicOrToken() = runTest {
        listOf(401, 403, 429, 500, 302).forEach { status ->
            val result = NtfySender(client(status)).test(NtfySettings(true, "https://example.org/private-topic", "private-token"))
            assertFalse(result.submitted)
            assertTrue(result.message.contains(status.toString()))
            assertFalse(result.message.contains("private"))
            assertEquals(status == 429 || status >= 500, result.retryable)
        }
    }
    @Test fun timeoutIsRetryable() = runTest {
        val result = NtfySender(client(timeout = true)).test(NtfySettings(true, "https://example.org/test-topic"))
        assertFalse(result.submitted)
        assertTrue(result.retryable)
        assertTrue(result.message.contains("Zeitüberschreitung"))
    }
}
