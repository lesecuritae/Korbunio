# F-Droid follow-up: review draft, not submitted

This document records the future-version reply draft and the separate metadata
correction already submitted after explicit user authorization. No release, tag
move, email or binary upload was performed.

## Sources and scope

- GitHub issue: https://github.com/lesecuritae/Korbunio/issues/58 (public API read 2026-10-15).
- F-Droid MR: https://gitlab.com/fdroid/fdroiddata/-/merge_requests/51680.
- Existing submitted source: `c0cbcc4`, version 0.1.59. Pipeline 2925446190 / job 17022680666 belong to that earlier submission. They do **not** validate the changes prepared here.
- Current F-Droid category names are defined by the official `config/categories.yml`: https://gitlab.com/fdroid/fdroiddata/-/blob/master/config/categories.yml. Both `Shopping List` and `Market & Price` are valid exact names. The existing recipe keeps `Shopping List`; adding another category is optional.
- Original submission checkout inspected at HEAD `73fa45977f11fb2e50c983b3ebef5c897fffe331` and kept unchanged. A separate worktree produced metadata correction `6544b5fcf9fa83d6d68f96598f383b79e1db6e33`, pushed to the existing GitLab submission branch after explicit user authorization.

The public REST notes/discussions API returned HTTP 401, but the actual discussion JSON endpoint succeeded: https://gitlab.com/fdroid/fdroiddata/-/merge_requests/51680/discussions.json (read 2026-10-15). The latest human note is by `mezinster`, 2026-10-10T18:28:15.108Z ([review note](https://gitlab.com/fdroid/fdroiddata/-/merge_requests/51680#note_3990456082)). It requires the German-only language disclosure, suggests `Market & Price` optionally, and explicitly leaves device checks open: startup/functions, terms, optional permissions/manual postal code on a device without Google services, and network capture including startup/update/unnecessary/tracker connections. Static success in that note is not device evidence.

## Separate submission recipe

The application changes and the future F-Droid metadata follow-up must remain separately reviewable. Do not retarget the existing 0.1.59 build or move `fdroid-v0.1.59`, and do not replace any historical artifact.

After application integration, record the full immutable application commit SHA below. Prepare a **new** build entry against that full SHA or a newly created, immutable version tag, with matching new versionName/versionCode. Keep the previous build entry and signing fingerprint. Do not publish a release as part of review preparation. A binary URL must refer to a newly produced artifact for that new version; a previous successful pipeline cannot be reused as its verification.

Application commit: `8b5f224df2830dccde83484b80a82221211803e6`

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

The follow-up application changes will be linked at [application commit](https://github.com/lesecuritae/Korbunio/commit/8b5f224df2830dccde83484b80a82221211803e6) after integration. The F-Droid recipe will pin that new immutable source revision in a separate patch. The previous 0.1.59 tag and its historical artifacts remain untouched. The standard and F-Droid product flavors retain their existing separation; no proprietary notification dependency has been introduced by the application changes.

The earlier successful pipeline 2925446190 (job 17022680666) tested source c0cbcc4 / 0.1.59. Verification of this follow-up is listed separately below. This future-version reply remains a draft; the separate current-build metadata reply is linked below.

## Verification matrix

| Area | Evidence / status |
| --- | --- |
| Existing F-Droid submission | Historical success reported for c0cbcc4 / 0.1.59; no claim about this patch |
| English metadata | Exact German-only disclosure and optional user ntfy setup added |
| F-Droid category syntax | Exact keys checked in official fdroiddata checkout; separate draft patch adds Market & Price alongside Shopping List |
| Python watch transport | Fake transport tests cover batches, failed batch retry, concurrency, filter migration and week transition; 148 targeted Python tests passed in `korbunio-test:local` with current mounted source (Kaufland, multi-buy, server watches, MCP, common, presentation, REWE, offer week, loyalty). After conditional base-price display adjustment, 17 multi-buy/presentation tests passed; scoped Ruff lint passed. Parent records Android/device/build results separately |
| Android / device / real network | All16 actual AOSP28 instrumentation tests passed in CI38815767838; physical device and app-attributed PCAPdroid checks remain open |
| Final integrated F-Droid build | Both local release builds passed; signed publication/reference and independent matching-commit comparison tracked separately |
| Latest GitLab reviewer notes | Actual discussions JSON read; latest human note 2026-10-10 by mezinster; remaining device/network checks listed above |

## Prepared submission patch

[Separate metadata patch](fdroid-v0.1.61-submission.patch) preserves the historical
0.1.59 entry, proposes a new 0.1.61 build and adds the valid optional category
`Market & Price` alongside `Shopping List`. It pins the immutable application revision shown above and retains an explicit
draft gate. Submitting it before the matching newly signed reference APK is
available is unsupported.
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


Exact language disclosure: [English description at the pinned source](https://github.com/lesecuritae/Korbunio/blob/8b5f224df2830dccde83484b80a82221211803e6/fastlane/metadata/android/en-US/full_description.txt).
The prepared recipe patch pins `8b5f224df2830dccde83484b80a82221211803e6` as its application review target. If a
future authorized release uses another immutable source commit, update the new
recipe entry and produce its matching new reference APK; never move an existing
release tag or replace historical artifacts.

## Current 0.1.59 metadata correction submitted

The user subsequently authorized updating the existing GitLab submission.
[Metadata commit 6544b5fcf](https://gitlab.com/lesecuritae/fdroiddata/-/commit/6544b5fcf9fa83d6d68f96598f383b79e1db6e33)
adds the exact language disclosure directly to `Description`, copied from the
0.1.59 English description, and adds `Market & Price`. This ensures the
currently pinned build receives the notice even before the upcoming application
version is released. The 0.1.59 source SHA, recipe, signing key and reference
artifact are unchanged. Official fdroidserver `lint de.korbunio.korbunio_app`
passed (exit0); the public checkout config permissions emitted a local warning.
The [maintainer reply](https://gitlab.com/fdroid/fdroiddata/-/merge_requests/51680#note_4024547036)
records the actual changes and explicitly leaves physical/network checks open.
This submission does not publish or substitute a 0.1.61 binary.

## CI execution boundary

The metadata-only fork pipeline
[2952955232](https://gitlab.com/lesecuritae/fdroiddata/-/pipelines/2952955232)
created no jobs. GitLab GraphQL reports: “The pipeline failed due to the user not
being verified.” This is not a metadata/test failure. The earlier successful
upstream run2925446190 was triggered by `linsui` on the F-Droid main project.
After the requested0.1.61 release/reference is available, request that upstream
execution again and pin the new metadata entry to the actual release commit.
The user authorized publishing the regular GitHub APK/Docker release first and
the F-Droid reference/submission afterward; neither result may be inferred from
this local record before publication completes.
