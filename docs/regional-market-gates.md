# Regional market checks (0.1.65)

Both native ALDI providers share official German Nord and Süd store lists.
Nord embeds locations in its public Next.js store-locator page; Süd publishes
its public Uberall widget identifier on its own store-locator page. The widget
identifier is not a private account credential. Listings are cached for one hour
and individual responses are limited to 4 MB. An unknown schema or an empty
store list is an error, not evidence that a chain has no local markets.

The search uses a 15 km straight-line radius. If a store has the requested PLZ,
its coordinates (averaged for multiple stores) locate the postal area. Otherwise
Nominatim resolves the German PLZ. Only the postal code is sent, without GPS or
account credentials; the result must confirm country and exact PLZ. Requests
identify Korbuino and are serialized at least 1.1 seconds apart; results are
cached. This adds optional traffic to nominatim.openstreetmap.org, alongside
aldi-nord.de and the official Süd widget on uberall.com. Geocoding data:
© OpenStreetMap contributors, ODbL, https://www.openstreetmap.org/copyright .
This is a regional availability check, not stock or price verification for a
particular branch. Border locations may legitimately include both ALDI chains.

aktiv & irma uses its official autocomplete endpoint and requires both the exact
PLZ and supermarket type `aktivirma`. Offices (`verwaltung`) and beverage shops
(`plopp`) do not qualify. The server uses the same rule. Its existing geographic
ALDI resolver now also applies when retailer filters select ALDI. Explicit
operator `aldi_region` overrides remain available; retailer selection alone
cannot override geography.

Confirmed market absence is carried separately from ordinary empty results or
HTTP/parser errors. Only confirmed absence clears that retailer's offer cache,
including previews. Products, shopping lists, favorites and settings are retained.
The Android foreground and scheduled refresh paths both apply this policy.
Server responses expose `unavailable_retailers`; the app understands both server
retailer names and direct provider IDs. Older servers without this field remain
compatible. Snapshot schema 13 avoids reusing previously contaminated snapshots.

## Docker/server region correction

The server now also reads both official chain catalogues, independently cached
for one hour. An exact matching store postcode supplies the geographic origin;
otherwise geocoding must confirm the German country code and exact postcode.
Both chains within 15 km remain eligible in border areas. A failed or empty
catalogue cannot prove that its chain is absent and does not block the other
chain. The existing versioned official postcode evidence remains supported.

Sparse OSM store search is only a positive-evidence fallback when both official
catalogues fail; stores beyond 15 km cannot select a chain. Finding one chain in
that incomplete source never proves absence of the other. Unresolved requested
chains produce response diagnostics and a server warning, including when other
retailers successfully return offers. Snapshot schema 15 prevents old incorrect
region exclusions from surviving an upgrade; shopping lists and settings remain.

This fixes issue #68's Docker case for 50939, previously misclassified as Nord
before a Süd offer request was even attempted. The correction uses catalogue
evidence rather than adding a special postcode exception.

Checks cover Munich 80331 (Süd only), Leipzig (Nord only), a border region,
missing/changed store responses, failed geocoding, office-only Irma results,
server retailer selection and cache behavior. Room device tests additionally
check retention of shopping lists, favorites and products. Unit fixtures are
synthetic; separately recorded official responses were replayed during release
validation. See release CI for device-test results.
