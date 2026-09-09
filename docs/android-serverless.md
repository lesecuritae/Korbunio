# Korbuino serverless Android architecture

The native Android client is a separate Kotlin/Compose application under
`android/`. It has no WebView main surface and no embedded Python or HTTP
server. Public retailer data flows through a provider interface into Room;
Compose observes Room through Kotlin Flow.

## REWE strategy

REWE has no stable public developer API. The native provider therefore uses
the public market and offer pages already used by the web adapter. Market URLs
are cached for 24 hours, offer cards are normalized locally, and the last
successful Room snapshot remains available after network or anti-bot failure.

The transport is deliberately replaceable. The implementation uses an
OkHttp client with a mobile browser User-Agent and prefers the official
Cronet transport for HTTP/2/3 when the Play Services engine is available.
Normal OkHttp remains the fallback. Certificate verification remains enabled;
there is no TLS bypass, private app certificate, or scraped mobile token.

Direct provider coverage is exposed through one `RetailerProvider` registry.
REWE and GLOBUS use their public structured pages; ALDI Nord, ALDI Süd,
Kaufland, Rossmann, Müller and HOL'AB! use their public flyer pages through a
conservative HTML parser. A provider returns an error or an empty result when
the public page changes, so stale Room data remains visible instead of being
silently deleted.

## Background and data safety

WorkManager is used only for opt-in periodic synchronization. Manual mode is
the default. Metered-network and charging constraints are user settings.
Provider failures never delete offers, lists, favorites, images, or settings.
Credentials belong in the Android Keystore-backed secure store and are not
part of JSON export or backup files.

## Migration boundary

The Flutter client and Docker service remain available during the provider
migration. Existing KorbKlar/Korbuino shopping-list JSON backups remain a
compatibility input. Native backups exclude SecureStore credentials, and Room
does not use destructive downgrade behavior; future schema changes must ship
an explicit migration rather than silently creating an empty replacement
store.
