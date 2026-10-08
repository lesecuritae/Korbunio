package de.lesecuritae.korbuino.providers

import kotlinx.coroutines.runBlocking
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.IOException

class NetworkClientFactoryTest {
    @Test fun `free transport sends challenge cookies and preserves response`() {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("public offers"))
            val client = NetworkClientFactory.build(35) { "challenge=confirmed" }
            client.newCall(Request.Builder().url(server.url("/offers")).build()).execute().use {
                assertEquals("public offers", it.body!!.string())
            }
            assertEquals("challenge=confirmed", server.takeRequest().getHeader("Cookie"))
        }
    }

    @Test fun `free transport rejects an untrusted HTTPS certificate`() {
        val certificate = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val serverCertificates = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        MockWebServer().use { server ->
            server.useHttps(serverCertificates.sslSocketFactory(), false)
            server.enqueue(MockResponse().setBody("should not be accepted"))
            val client = NetworkClientFactory.build(35) { null }
            assertThrows(IOException::class.java) {
                client.newCall(Request.Builder().url(server.url("/offers")).build()).execute().close()
            }
        }
    }

    @Test fun `self hosted server works over HTTPS with the free transport and bearer token`() {
        val certificate = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val serverCertificates = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val trusted = HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        MockWebServer().use { server ->
            server.useHttps(serverCertificates.sslSocketFactory(), false)
            server.enqueue(MockResponse().setBody(
                """{"offers":[{"offer_id":"test","retailer":"Test","product":"Apfel","regular_price":1.99}]}""",
            ))
            val client = NetworkClientFactory.build(35) { null }.newBuilder()
                .sslSocketFactory(trusted.sslSocketFactory(), trusted.trustManager).build()
            val result = runBlocking {
                ServerProvider(server.url("/").toString(), "synthetic-token", client)
                    .fetch(RetailerRequest("12345"))
            }
            assertEquals(199, result.offers.single().priceCents)
            val request = server.takeRequest()
            assertEquals("/api/v1/compare", request.path)
            assertEquals("Bearer synthetic-token", request.getHeader("Authorization"))
            org.junit.Assert.assertTrue(request.body.readUtf8().contains("\"postal_code\":\"12345\""))
        }
    }

    @Test fun `trusted HTTPS is accepted with a matching hostname`() {
        val certificate = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val serverCertificates = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val trusted = HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        MockWebServer().use { server ->
            server.useHttps(serverCertificates.sslSocketFactory(), false)
            server.enqueue(MockResponse().setBody("secure offers"))
            val client = NetworkClientFactory.build(35) { null }.newBuilder()
                .sslSocketFactory(trusted.sslSocketFactory(), trusted.trustManager).build()
            client.newCall(Request.Builder().url(server.url("/offers")).build()).execute().use {
                assertEquals("secure offers", it.body!!.string())
            }
        }
    }
}
