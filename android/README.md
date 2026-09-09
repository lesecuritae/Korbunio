# Korbuino native Android client

This module is a native Kotlin/Jetpack Compose application. It does not embed
the Korbuino web UI, run a local HTTP server, or require the Korbuino Docker
service. Retailer providers fetch public source data directly and persist the
normalized result in Room.

The REWE provider intentionally uses public offer pages. Its transport is
isolated behind the provider interface so Cronet can be enabled without
changing parsing or storage. The provider never disables certificate
validation and never uses private mobile-app credentials.

Background work is opt-in and scheduled with WorkManager. Manual mode is the
default; daily mode can require Wi-Fi and charging. A failed sync keeps the
last successful Room snapshot.

The existing Flutter client under `app/` and the Docker service remain the
compatibility implementation while native providers are migrated one by one.
