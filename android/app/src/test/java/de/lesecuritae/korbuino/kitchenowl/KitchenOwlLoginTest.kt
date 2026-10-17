package de.lesecuritae.korbuino.kitchenowl

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class KitchenOwlLoginTest {
    private lateinit var server: MockWebServer
    private lateinit var http: OkHttpClient

    @Before fun setUp() {
        val certificate = HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").build()
        val serverCerts = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val clientCerts = HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        server = MockWebServer().apply { useHttps(serverCerts.sslSocketFactory(), false); start() }
        http = OkHttpClient.Builder().sslSocketFactory(clientCerts.sslSocketFactory(), clientCerts.trustManager).build()
    }
    @After fun tearDown() { server.shutdown() }
    private fun reply(body: String, code: Int = 200) { server.enqueue(MockResponse().setResponseCode(code).setBody(body)) }
    private fun login() = KitchenOwlClient.login(server.url("/").toString(), " user@example.org ", "  secret-password  ", http)

    @Test fun `password login obtains durable token and revokes temporary session`() {
        reply("""{"access_token":"short-token","refresh_token":"unused-refresh"}""")
        reply("""{"longlived_token":"durable-token"}""")
        reply("""{"msg":"DONE"}""")
        assertEquals("durable-token", login())
        val auth = server.takeRequest()
        assertEquals("/api/auth", auth.path)
        assertEquals("POST", auth.method)
        assertNull(auth.getHeader("Authorization"))
        val payload = Json.parseToJsonElement(auth.body.readUtf8()).jsonObject
        assertEquals("user@example.org", payload["username"]?.jsonPrimitive?.content)
        assertEquals("  secret-password  ", payload["password"]?.jsonPrimitive?.content)
        val durable = server.takeRequest()
        assertEquals("/api/auth/llt", durable.path)
        assertEquals("Bearer short-token", durable.getHeader("Authorization"))
        assertFalse(durable.body.readUtf8().contains("secret-password"))
        val logout = server.takeRequest()
        assertEquals("DELETE", logout.method)
        assertEquals("Bearer short-token", logout.getHeader("Authorization"))
        reply("""[{"id":2,"name":"Zuhause"}]""")
        reply("""[{"id":42,"name":"Einkauf"}]""")
        val targets = KitchenOwlClient(server.url("/api/").toString(), "durable-token", http).targets()
        assertEquals(KitchenOwlTarget("42", "Zuhause · Einkauf", "2"), targets.single())
        assertEquals("/api/household", server.takeRequest().path)
        val list = server.takeRequest()
        assertEquals("/api/household/2/shoppinglist", list.path)
        assertEquals("Bearer durable-token", list.getHeader("Authorization"))
    }
    @Test fun `rejected login never echoes server body or password`() {
        reply("secret-password echoed by server", 401)
        val error = assertThrows(IllegalStateException::class.java) { login() }
        assertTrue(error.message.orEmpty().contains("abgelehnt"))
        assertFalse(error.message.orEmpty().contains("secret-password"))
        assertEquals(1, server.requestCount)
    }
    @Test fun `SSO only login has actionable error and no retry`() {
        reply("not available", 404)
        val error = assertThrows(IllegalStateException::class.java) { login() }
        assertTrue(error.message.orEmpty().contains("SSO"))
        assertEquals(1, server.requestCount)
    }
    @Test fun `redirect never receives password or bearer`() {
        server.enqueue(MockResponse().setResponseCode(307).addHeader("Location", server.url("/unexpected")))
        assertThrows(IllegalStateException::class.java) { login() }
        assertEquals(1, server.requestCount)
    }
    @Test fun `missing durable token fails and still revokes temporary session`() {
        reply("""{"access_token":"short-token"}"""); reply("""{"longlived_token":null}"""); reply("{}")
        assertThrows(IllegalStateException::class.java) { login() }
        assertEquals(3, server.requestCount)
        server.takeRequest(); server.takeRequest()
        assertEquals("DELETE", server.takeRequest().method)
    }
    @Test fun `malformed auth response does not disclose credentials`() {
        reply("not-json secret-password")
        val error = assertThrows(IllegalStateException::class.java) { login() }
        assertFalse(error.message.orEmpty().contains("secret-password"))
        assertEquals(1, server.requestCount)
    }
    @Test fun `rate limit is not retried`() {
        reply("{}", 429)
        assertThrows(IllegalStateException::class.java) { login() }
        assertEquals(1, server.requestCount)
    }
    @Test fun `http and URLs containing credentials are rejected before login`() {
        for (url in listOf("http://localhost", "https://user:secret@example.org", "https://example.org?secret=value")) {
            assertThrows(IllegalStateException::class.java) { KitchenOwlClient.login(url, "user", "pass", http) }
        }
        assertEquals(0, server.requestCount)
    }
}
