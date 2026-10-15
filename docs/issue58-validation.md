# Issue #58 — implementation and acceptance record

This branch starts at `5357871e25bc587f1c9bb308797f85678b27ae66` (main,
0.1.60). It prepares 0.1.61. The user subsequently requested the normal GitHub
release with APK/Docker first, followed by a matching F-Droid submission; existing
tags and historical artifacts must remain unchanged.
The native Android application is the implementation target. The historical
Flutter compatibility client is retained unchanged.

## Change and evidence matrix

| Issue point | Previous state | Implementation | Evidence | Remaining acceptance |
| --- | --- | --- | --- | --- |
| Shopping scroll | Ordinary Column rendered every row, without a scroll action | One bounded LazyColumn with stable entry keys, saved expansion/scroll state, IME padding and reachable undo | Original production screen genuinely reproduced the missing-scroll assertion on AOSP API28; replacement regression and last-row/undo test included | Final instrument run recorded below |
| Retailer plan | Product names deduplicated, quantities and concrete offer identity absent | Separate item/retailer/offer IDs; pack quantities; positions, retailer subtotals and honest overall totals | ShoppingPositions/OfferPricing unit regressions; retailer UI regression | Final Android build and device result below |
| Price conditions | Raw bundle total could look like one pack | Minimum quantity, advertised bundle total, source pack/base price and conditional derived unit price | Real unchanged Konstanz fixtures; quantities1,2,3,4,6; normal single-price regressions | No historical Em-eukal source proof claimed |
| Loyalty / deposit | Wish/offer assignment implicit | Selected direct prices only; cashback and deposit separate; unknown amounts remain unknown | Price/plan/loyalty regressions; no membership assumed for server-watch thresholds | Actual cashier conditions remain retailer-controlled |
| Favorites | Table existed without full native workflow | Independent queries with CRUD, stable retailer filters, optional threshold, week scope and separate notification choice | DAO/migration and Compose CRUD tests included | Final instrument result below |
| Optional ntfy | Server-only watches | Native protected topic/token settings, explicit test, opt-in publication after foreground/background sync, bounded durable retries and leased receipts | HTTPS MockWebServer, filter/week/receipt tests; actual Room concurrency/restart test included | User configures their own topic and external ntfy receiver |
| Server delivery | First5 included in message but every hit acknowledged | Send batches≤5; acknowledge only delivered batches; retain failed hits; consistent filters/default migration | Full Python suite, thread delivery and >5-hit tests | No real user topic contacted |
| Genuine preview | Current refresh could erase future stock | Date partitions, actual provider week requests, canonical product references, no redating, successful empty preview clears future partition | Provider, Berlin/year-transition, DAO and native preview integration tests | Preview availability depends on retailer publication |
| User-data upgrade | Existing list/favorite schema6 | Explicit Room6→7; independent entries; backup includes new data but excludes credentials | Exported real schema6 upgrade, duplicate-name backup roundtrip and persisted favorite tests included | No destructive migration |
| F-Droid review |0.1.59 source/recipe independently reviewed | Exact language disclosure, optional ntfy disclosure, separately reviewable recipe follow-up |[Maintainer draft](fdroid-issue58-review-draft.md), [recipe patch](fdroid-v0.1.61-submission.patch) | New signed reference binary and physical/network review remain separate gates |

## Kaufland source scope

Both Konstanz stores were requested independently with their public store
selection and regional availability. `bbyMessage` is the verified quantity
source; `bonusbuy` alone also marks ordinary Card offers and is insufficient.
Sales dates and local availability constrain validity. Old price fields are not
proof of a single-pack price, and action IDs are not proof of mix eligibility.

[Source provenance and unchanged fixture links](kaufland-mehrkauf-quellen-20261015.md).
The user clarified that Em-eukal was a previous-week promotion and ended the
historical investigation. No historical offer was redated or substituted from
another store. Synthetic arithmetic tests are explicitly identified as such.

## Recorded automated checks

- Full Python suite at current source: **464 passed,8 live tests deselected**.
- Scoped complete Ruff and Bandit checks passed before final acceptance rerun.
- Python wheel `korbunio-0.1.61-py3-none-any.whl` built successfully.
- Isolated Docker image built; `/health` and the0.1.61 homepage returned200;
  container was healthy and bound only to localhost; test resources removed.
- Runtime Python dependency audit: no known vulnerabilities found. The local
  project itself is not a PyPI dependency and is reviewed through its tests.
- Secret scan of clean source export passed; public signing-key fingerprints
  are not credentials. No production secrets, captures or machine logs included.
- Current-source Standard162 and F-Droid165 unit tests passed, including the
  new Card-condition regression; no failures/errors/skipped cases.
- Current-source `lintStandardDebug` and `lintFdroidDebug` passed in a serial run;
  no lint rule or test was disabled.
- Both standard and F-Droid release builds succeeded for0.1.61 before the last
  import/preview hardening. Those builds are not claimed as final-source evidence.
- A concurrent full-lint invocation crashed internally in Kotlin resolution;
  isolated serial `lintStandardDebug` subsequently passed without suppression.

## Android final run

All **16 instrumentation tests passed**, with **zero failures, errors or skipped
tests**, on a Google-free AOSP Android9/API28 emulator with hardware acceleration
in [CI run38815767838](https://github.com/lesecuritae/Korbunio/actions/runs/38815767838/job/116699915666).
Application branch at this gate: `e4237959b765b8534f4e5369e2cc0b56e2b6b029`.
The published job artifact includes the actual JUnit XML, not just APK compilation.

Coverage: long-list scrolling with expanded matches and increased font scale,
retailer subtotal/last-remove/undo, favorite create/edit/delete and selection,
invalid ntfy setup, real schema6→7 migration validated by Room, duplicate-name
backup roundtrip without credentials, week-partition retention, canonical product
references, successful-empty-preview cleanup and concurrent/restarted receipts.

The first complete instrument run passed15/16: the schema fixture loader required
an optional `indices` field on tables without indexes. The loader now handles an
absent list; all actual SQL migration validation and preservation assertions remain.
Earlier local software-only emulator attempts hit SystemUI/boot failures. Those
attempts are not counted as successful suites. The old production Column genuinely
failed the missing-scroll regression before replacement.

Final local Standard and F-Droid unsigned release builds succeeded. These local
artifacts are not the upcoming signed publication/reference artifacts:

| Variant | Local unsigned APK SHA-256 |
| --- | --- |
| Standard | `883de1f791ac05b0a12786b9181892f1943662ca8e14465b4a38eaf7be202c8f` |
| F-Droid | `fed89448a8f19ecdc403fe96f0df766bc6b4b9fc1954e406dd1dbe6e89575cf2` |

The new F-Droid APK retains exactly the previous permission set: INTERNET,
ACCESS_COARSE_LOCATION, WAKE_LOCK, ACCESS_NETWORK_STATE, RECEIVE_BOOT_COMPLETED,
FOREGROUND_SERVICE and the application DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION.
No POST_NOTIFICATIONS or MANAGE_EXTERNAL_STORAGE permission was added. The final
signed reference must additionally be compared with an independent build at its
actual immutable publication commit; preliminary builds do not prove that match.

## Unperformed physical and monitored-network review

There is no attached physical Android device or PCAPdroid session for this work.
Do not claim a physical test, Google-free physical-device certification, complete
app-attributed packet capture, or F-Droid admission. The exact manual procedure
is in the [maintainer draft](fdroid-issue58-review-draft.md). Test first launch,
permission denial/manual postal entry, no Geocoder, optional integrations,
background sync and an isolated ntfy topic separately. Record device/Android,
release APK hash and commit, destinations, triggers and disable switches.

After explicit follow-up user authorization, the existing GitLab submission
branch was updated with metadata-only commit `6544b5fcf` and a factual reviewer
reply (linked in the maintainer record). No email or historical tag/artifact replacement was performed. The later release
and factual GitHub issue reply are authorized after successful automated gates. The PR should reference#58 and preserve any genuinely
open acceptance points instead of closing the issue automatically.
