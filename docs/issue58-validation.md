# Issue #58 — implementation and acceptance record

This branch starts at `5357871e25bc587f1c9bb308797f85678b27ae66` (main,
0.1.60). It prepares 0.1.61; it does not publish a release or move any tag.
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

**In progress; this section must be replaced with final counts, exact APK hashes,
source commit, build results and instrumentation outcome before acceptance.**

A dedicated Google-free AOSP Android9/API28 emulator is used, with software CPU
because this host does not expose KVM. The original unscrollable implementation
failed with `Semantic Node has no parent layout with a Scroll SemanticsAction`.
An early replacement run was interrupted after the emulator/adb transport
stalled; its one passed test does not mean its remaining tests passed.
A subsequent Android9 run encountered a SystemUI ANR and system crash at test2;
that is retained as a blocked environment result, not a successful UI suite.
The suite is being repeated on an independent AOSP Android15/API35 test image. The
selected transport was reconnected, rendering reduced to480×800, and subsequent
installs use `--no-streaming`. Infrastructure aborts remain separate from product
assertion failures. The CI workflow also runs actual AOSP instrumentation rather
than merely compiling the test APK.

## Unperformed physical and monitored-network review

There is no attached physical Android device or PCAPdroid session for this work.
Do not claim a physical test, Google-free physical-device certification, complete
app-attributed packet capture, or F-Droid admission. The exact manual procedure
is in the [maintainer draft](fdroid-issue58-review-draft.md). Test first launch,
permission denial/manual postal entry, no Geocoder, optional integrations,
background sync and an isolated ntfy topic separately. Record device/Android,
release APK hash and commit, destinations, triggers and disable switches.

No email, issue comment, GitLab comment, merge, tag move or release is authorized
by this acceptance record. The PR should reference#58 and preserve any genuinely
open acceptance points instead of closing the issue automatically.
