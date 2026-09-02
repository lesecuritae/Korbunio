# KorbKlar App

Offline-first Flutter client for Android, styled after the web interface and
optionally connected to any self-hosted [KorbKlar](../README.md) server.

The app is a view, not a second implementation. Retailer adapters,
normalisation, unit prices, comparison groups and loyalty logic all stay on the
server, exactly as they do for the browser. The app never computes or formats a
price; it renders the values the comparison engine returns.

## What it does

- postal-code search with live progress, the same job endpoint the web page uses
- optional Android location permission to prefill the postcode; coordinates are discarded immediately
- result list with product and brand filter, retailer chips, sorting, and the
  cheapest-only / include-duplicates views
- unit prices, package sizes, validity and source links
- one row for an identical offer sold at several retailers for the same price
- loyalty program selection, with the server's benefit note
- product images through the server's signed image proxy
- warnings for failed or incomplete sources
- endless scrolling
- local result cache: previously loaded offers remain searchable without a server
- persistent local shopping list with offline view and clipboard export
- direct optional KitchenOwl connection, independent of the KorbKlar server
- a refresh action that bypasses the server's snapshot cache and re-queries
  every source

Server address, postal code, loyalty selection and target list are remembered
on the device. KorbKlar and KitchenOwl tokens are stored in Android's encrypted
Keystore rather than normal preferences.

On first connection, an app without its own saved postal code or retailer
selection adopts the server's optional `SUPERMARKT_DEFAULT_POSTAL_CODE` and
`SUPERMARKT_DEFAULT_RETAILERS`. Later choices in the app always take precedence.

If no postcode has been saved, Android asks whether the current location may be
used. Reverse geocoding runs through the device service; only the resulting
five-digit postcode is stored. Location permission can be denied without
losing any manual-search or offline feature.

## Shopping list

Every offer carries an **Auf KitchenOwl** button that files it straight into
the list named in the bar above the results, the same one-tap flow the browser
uses. The button then reads "in <list>" so a filed offer stays recognisable
while scrolling. Checking the article off in KitchenOwl clears that mark
again on the next load, since KitchenOwl removes a checked entry from the
list. The chosen list is remembered on the device.

The user can connect KitchenOwl directly in **Settings → Connections**. The
long-lived token stays on the device and is sent only to the configured HTTPS
KitchenOwl host. It is never forwarded to the KorbKlar server. If the server
provides its own compatible KitchenOwl endpoint, the client can still use that
as a fallback.

Where no KitchenOwl list is configured, offers go to the persistent local
shopping list. It can be opened from the basket icon and exported through the
clipboard without a server connection.

## Toolchain

The app is built and tested against the current Flutter **stable** channel.
Both workflows resolve the channel rather than a fixed version, so CI
follows each stable release; keep the local SDK on stable too, or `flutter
analyze` and the goldens can disagree with CI for no reason of yours:

```bash
flutter upgrade
flutter --version
```

`environment: sdk:` in `pubspec.yaml` states the oldest Dart the code needs,
not the one it is built with. It is deliberately not raised to whatever the
newest stable ships, so a contributor on a slightly older SDK is not shut out
for nothing.

## Running it

```bash
flutter pub get
flutter run
```

On first start the app asks for the server address, for example
`http://192.0.2.10:8000`, plus an optional API token, and verifies the service
before saving it. Connections can later be changed without deleting the offline
result cache.

The administrator sets `SUPERMARKT_API_KEY` on a protected server. In the app,
enter that key once and choose **Create personal app token**. The server creates
a separate random credential, stores only its SHA-256 digest, and the app
replaces the administrator key with that credential in Android's secure
storage. The administrator key therefore does not remain on the phone. A
tokenless server remains usable without this pairing step.

`/health` answers without authorisation but withholds its detail fields. The app
then verifies access through `/api/v1/client`, so it can distinguish a wrong
address from a missing token without triggering a search. Bearer tokens are
accepted only for HTTPS server addresses. Tokenless HTTP remains available for
an explicitly chosen LAN or VPN server.

### Installing on Android

The `Build Android app` workflow produces an installable APK on every push
that touches `app/`, and can also be started by hand from the Actions tab.
Download the `korbklar-apk` artifact and install `app-arm64-v8a-release.apk`
on the phone; Android asks once to allow installation from that source.

### Updating from GitHub releases

Once installed, the app keeps itself current from this repository's GitHub
releases. On start (at most every ten minutes, and only on Android) it asks
the releases API for the latest tag, compares it with the installed version
and offers the APK built for the phone's ABI. The download is verified against
the SHA-256 digest GitHub records for the asset before it is handed to the
system installer; a mismatch discards the file. "Überspringen" mutes that one
release, the switch under *App-Updates* in the settings turns the start-up
check off, and *Jetzt nach Updates suchen* runs it by hand. Because release
APKs are signed with the persistent key, an update keeps the app's data.

Building locally works too, when the machine's Gradle toolchain is healthy:

```bash
flutter build apk --release
```

Official release artifacts are signed with KorbKlar's persistent release key.
CI receives the key exclusively through encrypted repository secrets; no key or
password is stored in Git. Local release builds must provide the corresponding
signing environment variables and keystore. Unsigned or debug-signed release
builds fail instead of silently producing a differently signed APK.

### Cleartext HTTP

Some self-hosted instances run plain HTTP on a LAN or VPN, so Android permits a
tokenless connection to them. Application-level validation refuses to transmit
either a KorbKlar or KitchenOwl token over cleartext HTTP. Certificate
validation for HTTPS remains fully enabled.

## Tests

```bash
flutter analyze
flutter test
```

Two opt-in suites exist beyond the default run.

Against a real server:

```bash
flutter test --tags live --dart-define=KORBKLAR_URL=http://127.0.0.1:8000 --dart-define=KORBKLAR_PLZ=26188
```

Add `--dart-define=KORBKLAR_KEY=...` for an instance that requires an API key.

Golden images of the result list in both themes, useful for reviewing layout
and palette without a device:

```bash
flutter test --tags golden --update-goldens
```

The goldens load Roboto and the Material icon font from the Flutter SDK, so
`FLUTTER_ROOT` must be set for the rendered text and icons to be legible.

## Layout

```text
lib/
├── api/
│   ├── client.dart      server calls, signed result handles, image URLs
│   ├── kitchenowl_client.dart  direct HTTPS KitchenOwl adapter
│   └── models.dart      typed views over the REST responses
├── screens/
│   ├── home_screen.dart      server setup, postal code, search progress
│   ├── settings_screen.dart  server and KitchenOwl connections
│   └── results_screen.dart   filters, chips, loyalty, list, selection
├── services/
│   ├── shopping_list.dart  list route and the text format
│   ├── local_shopping_list.dart  persistent offline basket
│   ├── offline_store.dart  atomic device-local result cache
│   ├── app_update.dart   release check, verified APK download, installer
│   └── settings.dart    locally remembered preferences
├── widgets/
│   ├── app_update_flow.dart  update dialogs shared by start-up and settings
│   └── offer_card.dart  one offer row
├── theme.dart           colour tokens taken from the web stylesheets
└── main.dart
```

`theme.dart` mirrors the CSS custom properties in `home.css` and `results.css`,
including the dark palette, so both clients look like one product.
