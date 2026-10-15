# F-Droid follow-up: review draft, not submitted

This document is a local maintainer reply draft. No email, issue comment, GitLab comment, tag, release or binary upload was sent or created by this work.

## Sources and scope

- GitHub issue: https://github.com/lesecuritae/Korbunio/issues/58 (public API read 2026-10-15).
- F-Droid MR: https://gitlab.com/fdroid/fdroiddata/-/merge_requests/51680.
- Existing submitted source: `c0cbcc4`, version 0.1.59. Pipeline 2925446190 / job 17022680666 belong to that earlier submission. They do **not** validate the changes prepared here.
- Current F-Droid category names are defined by the official `config/categories.yml`: https://gitlab.com/fdroid/fdroiddata/-/blob/master/config/categories.yml. Both `Shopping List` and `Market & Price` are valid exact names. The existing recipe keeps `Shopping List`; adding another category is optional.
- Submission checkout inspected at HEAD `73fa45977f11fb2e50c983b3ebef5c897fffe331`. It was not changed by this work.

The public REST notes/discussions API returned HTTP 401, but the actual discussion JSON endpoint succeeded: https://gitlab.com/fdroid/fdroiddata/-/merge_requests/51680/discussions.json (read 2026-10-15). The latest human note is by `mezinster`, 2026-10-10T18:28:15.108Z ([review note](https://gitlab.com/fdroid/fdroiddata/-/merge_requests/51680#note_3990456082)). It requires the German-only language disclosure, suggests `Market & Price` optionally, and explicitly leaves device checks open: startup/functions, terms, optional permissions/manual postal code on a device without Google services, and network capture including startup/update/unnecessary/tracker connections. Static success in that note is not device evidence.

## Separate submission recipe

The application changes and the future F-Droid metadata follow-up must remain separately reviewable. Do not retarget the existing 0.1.59 build or move `fdroid-v0.1.59`, and do not replace any historical artifact.

After application integration, record the full immutable application commit SHA below. Prepare a **new** build entry against that full SHA or a newly created, immutable version tag, with matching new versionName/versionCode. Keep the previous build entry and signing fingerprint. Do not publish a release as part of review preparation. A binary URL must refer to a newly produced artifact for that new version; a previous successful pipeline cannot be reused as its verification.

Application commit: **PENDING parent integration**

Reviewable recipe template (placeholders deliberately make this unsuitable for submission):

```yaml
# Append under Builds, keeping the 0.1.59 entry:
- versionName: <new-version>
  versionCode: <new-version-code>
  commit: <full-new-application-commit-sha>
  subdir: android/app
  gradle:
    - fdroid
  rm:
    - app
    - android/app/src/standard
    - android/app/src/testStandard
    - android/app/standard-dependencies.gradle
  gradleprops:
    - fdroidOnly=true
    - org.gradle.workers.max=2
```

## English maintainer reply draft

Thank you for reviewing Korbuino. The English description now states explicitly: “The app interface is currently German only.” It also discloses that offer notifications are optional, require a topic chosen by the user on a public or self-hosted ntfy server, and do not require a central Korbuino account.

The follow-up application changes will be linked at `https://github.com/lesecuritae/Korbunio/commit/<FULL_NEW_SHA>` after integration. The F-Droid recipe will pin that new immutable source revision in a separate patch. The previous 0.1.59 tag and its historical artifacts remain untouched. The standard and F-Droid product flavors retain their existing separation; no proprietary notification dependency has been introduced by the application changes.

The earlier successful pipeline 2925446190 (job 17022680666) tested source c0cbcc4 / 0.1.59. Verification of this follow-up is listed separately below. This reply is a draft and has not been posted.

## Verification matrix

| Area | Evidence / status |
| --- | --- |
| Existing F-Droid submission | Historical success reported for c0cbcc4 / 0.1.59; no claim about this patch |
| English metadata | Exact German-only disclosure and optional user ntfy setup added |
| F-Droid category syntax | Exact keys checked in official fdroiddata checkout; recipe category unchanged |
| Python watch transport | Fake transport tests cover batches, failed batch retry, concurrency, filter migration and week transition; 148 targeted Python tests passed in `korbunio-test:local` with current mounted source (Kaufland, multi-buy, server watches, MCP, common, presentation, REWE, offer week, loyalty). After conditional base-price display adjustment, 17 multi-buy/presentation tests passed; scoped Ruff lint passed. Parent records Android/device/build results separately |
| Android / device / real network | Parent integration evidence required; not implied by fake tests |
| Final integrated F-Droid build | Pending; must identify new full source SHA and its own build results |
| Latest GitLab reviewer notes | Actual discussions JSON read; latest human note 2026-10-10 by mezinster; remaining device/network checks listed above |

## Prepared submission patch

[Separate metadata patch](fdroid-v0.1.61-submission.patch) preserves the historical
0.1.59 entry, proposes a new 0.1.61 build and adds the valid optional category
`Market & Price` alongside `Shopping List`. It deliberately contains a commit
placeholder and an explicit draft gate. Applying/submitting it before a reviewed
immutable revision and newly signed reference APK are available is unsupported.
The user did not authorize publishing a release or a reference binary here.

## Manual device/network procedure still required

Use the newly identified F-Droid release APK (not the old 0.1.59 job). Record its
SHA-256, immutable source commit, device model and Android version. Start
PCAPdroid before cold launch and keep separate captures for:

1. First launch with location denied, no optional connections and no daily sync.
2. Manual postal-code search, including no-Geocoder backend.
3. Explicit location-button use and denied permission.
4. Optional integrations, enabled individually by the tester.
5. WorkManager daily refresh and an isolated test ntfy topic.

List observed destinations with purpose and triggering operation. In the
F-Droid flavor there must be no GitHub self-update requests. Without explicit
configuration there must be no ntfy, KitchenOwl or own-server requests. Check
for unexpected tracking/font/icon/connectivity requests using the capture,
rather than inferring their absence from source code. Review APK permissions;
no MANAGE_EXTERNAL_STORAGE or POST_NOTIFICATIONS was introduced.
A software AOSP emulator result is not a physical-device or PCAPdroid result.
