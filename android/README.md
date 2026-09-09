# Korbuino native Android client

This is the **serverless production Android app**. The published APK is built
from this Gradle project, not from the Flutter compatibility client in
`../app/`. It uses direct retailer providers, stores normalized offers in Room,
and remains usable with the Korbuino server completely stopped. Internet access
is still needed to refresh live retailer data; previously synchronized data and
the shopping list remain available offline.

This module is a native Kotlin/Jetpack Compose application. It does not embed
the Korbuino web UI, run a local HTTP server, or require the Korbuino Docker
service. Retailer providers fetch public source data directly and persist the
normalized result in Room.

The REWE provider intentionally uses public offer pages. Its transport is
isolated behind the provider interface and uses Cronet-backed OkHttp when
available, with normal OkHttp as a fallback. Certificate validation is never
disabled and private mobile-app credentials are never used.

The direct provider registry currently includes REWE, GLOBUS, ALDI Nord,
ALDI Süd, Kaufland, Rossmann, Müller, HOL'AB!, both Netto variants and dm.
Combi, famila Nordwest, Lidl and PENNY use the public regional Marktguru
adapter. The generic flyer provider accepts only cards with a product name and
EUR price and keeps the source URL; retailers that require a store-specific
flow can be added without moving network code into the Compose UI.

REWE has no stable public developer API. The Android adapter therefore uses
the public market and offer pages and falls back to the regional Marktguru
web client when the public page is unavailable. It does not ship private app
credentials, bypass TLS, or embed a browser server. A provider error preserves
the last Room snapshot so a temporary anti-bot response does not erase local
data.

Background work is opt-in and scheduled with WorkManager. Manual mode is the
default; daily mode can require Wi-Fi and charging. A failed sync keeps the
last successful Room snapshot.

The native settings surface can check the latest GitHub release, download an
HTTPS APK, verify an optional SHA-256 sidecar, and hand installation to the
Android package installer. Android signature validation remains in control;
there is no silent installation.

When a retailer presents a CAPTCHA or anti-bot challenge, the app offers a
manual confirmation page restricted to the retailer and known challenge hosts.
The user completes the check; Korbuino never solves or bypasses a CAPTCHA.
The resulting first-party session cookie is kept in the app's private cookie
store and the provider request is retried. A self-hosted Korbuino server can
also be configured in the same app; its token is stored in the encrypted
Android store. KitchenOwl remains a separate, direct HTTPS integration.

The existing Flutter client under `app/` and the Docker service remain the
compatibility implementation while native providers are migrated one by one.

With a saved five-digit postal code, the native app automatically loads the
`Alle Händler` overview on startup. Results from reachable providers are
merged into one searchable local list; a failed provider does not hide offers
from the others. The retailer selector can still be used for a focused
refresh, and an optional self-hosted server can provide the same overview.

The overview opens as its own screen after a successful load. A location
button can resolve a German postal code with a user-approved Android location
permission; manual PLZ entry remains supported. Compose follows the phone's
light or dark system setting.

Offer results use the KorbKlar-style card layout with product image, retailer,
category, price, base price and direct shopping-list actions.
The result screen mirrors the Docker/Flutter navigation with `Ergebnisse` and
`Einkauf` tabs, horizontal retailer tabs with counts, and sorting controls.
REWE regional results are paginated and no longer stop at a short HTML subset.
The overview also provides an `Alle Händler` selector, individual retailer
filters and retailer/product sorting like the Docker client.
Connection settings for an optional self-hosted server and KitchenOwl are
available from the gear icon in the home and offers screens.
