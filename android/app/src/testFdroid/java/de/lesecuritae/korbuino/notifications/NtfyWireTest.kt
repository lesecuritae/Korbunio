package de.lesecuritae.korbuino.notifications

import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.Assert.*
import org.junit.Test

class NtfyWireTest {
    @Test fun submitsHttpsPostToConfiguredTopicWithUtf8BodyAndBearer() = runTest {
        val certificate = HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").build()
        val serverCertificates = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val clientCertificates = HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        MockWebServer().use { server ->
            server.useHttps(serverCertificates.sslSocketFactory(), false)
            server.start()
            server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
            val client = OkHttpClient.Builder().sslSocketFactory(clientCertificates.sslSocketFactory(),clientCertificates.trustManager).build()
            val result = NtfySender(client).send(NtfySettings(true,server.url("/test-only-topic").toString(),"local-test-token"),"Coca-Cola – 1,49 €")
            assertTrue(result.submitted)
            val request = server.takeRequest()
            assertEquals("POST",request.method)
            assertEquals("/test-only-topic",request.path)
            assertEquals("Bearer local-test-token",request.getHeader("Authorization"))
            assertEquals("Coca-Cola – 1,49 €",request.body.readUtf8())
        }
    }
}
