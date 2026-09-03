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
- opens straight into the last comparison and re-queries the retailers only
  after an offer change (Thursday, and Sunday for the new week), see below
- a refresh action that starts a new search by hand

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

## Starting

The postal code rarely changes, so the app does not ask for it every time.
With a saved postcode and a connected server it opens **straight into the
last comparison**: the stored result is shown at once, from the device cache
if the server is unreachable.

Whether the retailers are queried again is decided by the calendar, not by
how long the app was closed. German offers change for the new week, which the
server already selects on **Sunday**, and for the discounters again on
**Thursday**. If one of those lies between the last
search and now, a fresh search starts in the background while the old result
stays readable; a slim strip above the list shows its progress and the new
result replaces the old one when it completes. Between changes the app opens
in a second and makes no request at all beyond reading the stored result.

A different postcode is one tap away: the **PLZ** title of the result list
leads back to the search form. The behaviour can be switched off under
**Settings → Start**; the refresh icon in the result list always starts a new
search by hand.

## Shopping list

Every offer carries a **Zur Einkaufsliste** button that adds it to the
persistent local shopping list. That list opens from the basket icon and can
be exported through the clipboard without a server connection.

With a KitchenOwl connected in **Settings → Connections**, each offer gets a
second button, **Auf KitchenOwl**, that files it straight into the list named
in the bar above the results. The button then reads "in <article>" so a filed
offer stays recognisable while scrolling. Checking the article off in
KitchenOwl clears that mark again on the next load, since KitchenOwl removes
a checked entry from the list. The chosen list is remembered on the device.
The switch **Nur KitchenOwl verwenden** hides the local list altogether, so
the offer card keeps a single button; it falls back to the local list while
KitchenOwl is unreachable.

What KitchenOwl receives is an article, not a headline. The app reads the
household's own articles and files the offer on the one that matches, so
"JA! Weizenbrötchen 6 Stück" lands on the existing "Brötchen" with its icon
(`services/kitchenowl_articles.dart`, the same rules the browser side once
used: whole-word matching, head noun last, longest match wins). Where none
matches, the offer name is shortened to the staple: private-label shouting,
pack sizes and "aus der Region" go. The note under the article carries the
offer wording, the price and the validity, nothing else. The article is filed
under a category named after the shop with a colour dot, "🔴 REWE", so the
list sorts by store; missing categories are created.

The long-lived token stays on the device and is sent only to the configured
HTTPS KitchenOwl host. It is never forwarded to the KorbKlar server. If the
server provides its own compatible KitchenOwl endpoint, the client can still
use that as a fallback.

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

*Jetzt nach Updates suchen* under **App-Updates** in the settings asks this
repository's GitHub releases API for the latest tag, compares it with the
installed version and offers the APK built for the phone's ABI. The app never
checks on its own. The download is verified against the SHA-256 digest GitHub
records for the asset before it is handed to the system installer; a mismatch
discards the file. Because release APKs are signed with the persistent key, an
update keeps the app's data. Android only.

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
│   ├── app_update_flow.dart  update dialogs behind the settings button
│   └── offer_card.dart  one offer row
├── theme.dart           colour tokens taken from the web stylesheets
└── main.dart
```

`theme.dart` mirrors the CSS custom properties in `home.css` and `results.css`,
including the dark palette, so both clients look like one product.
