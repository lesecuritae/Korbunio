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

The transport is deliberately replaceable. The first implementation uses
OkHttp with a mobile browser User-Agent. A Cronet-backed OkHttp transport is
the next production transport when live Android validation shows that REWE
requires Chromium's HTTP/2/3 behavior. Certificate verification remains
enabled; no TLS bypass, private app certificate, or scraped mobile token is
allowed.

## Background and data safety

WorkManager is used only for opt-in periodic synchronization. Manual mode is
the default. Metered-network and charging constraints are user settings.
Provider failures never delete offers, lists, favorites, images, or settings.
Credentials belong in the Android Keystore-backed secure store and are not
part of JSON export or backup files.

## Migration boundary

The Flutter client and Docker service remain available during the provider
migration. Existing KorbKlar/Korbuino backups remain a compatibility input;
the native database uses a separate schema and must be migrated explicitly,
never by silently creating an empty replacement store.
