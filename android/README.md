# Korbuino native Android client

This module is a native Kotlin/Jetpack Compose application. It does not embed
the Korbuino web UI, run a local HTTP server, or require the Korbuino Docker
service. Retailer providers fetch public source data directly and persist the
normalized result in Room.

The REWE provider intentionally uses public offer pages. Its transport is
isolated behind the provider interface and uses Cronet-backed OkHttp when
available, with normal OkHttp as a fallback. Certificate validation is never
disabled and private mobile-app credentials are never used.

The direct provider registry currently includes REWE, GLOBUS, ALDI Nord,
ALDI Süd, Kaufland, Rossmann, Müller and HOL'AB!. The generic flyer provider
accepts only cards with a product name and EUR price and keeps the source URL;
retailers that require a store-specific flow can be added without moving
network code into the Compose UI.

Background work is opt-in and scheduled with WorkManager. Manual mode is the
default; daily mode can require Wi-Fi and charging. A failed sync keeps the
last successful Room snapshot.

The native settings surface can check the latest GitHub release, download an
HTTPS APK, verify an optional SHA-256 sidecar, and hand installation to the
Android package installer. Android signature validation remains in control;
there is no silent installation.

The existing Flutter client under `app/` and the Docker service remain the
compatibility implementation while native providers are migrated one by one.
