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

When a location is already saved, the native app starts the complete
multi-retailer overview automatically at launch. The default selection is
`Alle Händler`; successful providers are merged into one Room-backed offer
list and a failed retailer is reported without hiding offers from the others.
The overview can be searched by product, retailer or category, while the
retailer selector remains available for a focused refresh.

After a successful refresh the app opens the offer overview as a separate
screen, matching the previous KorbKlar flow; the user can return to settings
and select another retailer set. A user-triggered Android location lookup can
fill a German PLZ and starts the same overview automatically. The Compose
theme follows the device light/dark setting.

## Background and data safety

WorkManager is used only for opt-in periodic synchronization. Manual mode is
the default. Metered-network and charging constraints are user settings.
Provider failures never delete offers, lists, favorites, images, or settings.
Credentials belong in the Android Keystore-backed secure store and are not
part of JSON export or backup files.

## Updates

Native updates are read from the public GitHub Releases API. The app only
accepts HTTPS APK URLs, verifies a published `.sha256` sidecar when present,
and starts the normal Android installation dialog through a `FileProvider`.
No background or silent installation is attempted, and a release signing key
is never stored in the repository.

## Manual anti-bot challenges and server mode

Direct retailer providers may receive a CAPTCHA or a rate-limit challenge.
The app opens a restricted, user-mediated challenge page only for an allowlisted
retailer host. Cookies are retained privately and the direct request is retried;
there is no CAPTCHA automation or bypass. The same native app can optionally
use a user-configured self-hosted Korbuino API, while KitchenOwl is always
connected directly over HTTPS.

## Migration boundary

The Flutter client and Docker service remain available during the provider
migration. Existing KorbKlar/Korbuino shopping-list JSON backups remain a
compatibility input. Native backups exclude SecureStore credentials, and Room
does not use destructive downgrade behavior; future schema changes must ship
an explicit migration rather than silently creating an empty replacement
store.

The app exposes JSON backup import/export through the Android document picker.
Legacy Flutter shopping-list documents are normalized into the local Room list;
unknown fields are ignored and SecureStore values are filtered by key name and
never written to the backup.

Room schema upgrades use explicit migrations. The image metadata migration
keeps GTIN, retailer, source type, confidence and verification timestamps so
external product images can be audited and reused offline.
