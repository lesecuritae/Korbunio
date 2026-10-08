# F-Droid distribution

The native app has two distributions with the same application ID
`de.korbunio.korbunio_app`:

- `standard`: direct-download releases, optional Play Services Cronet, existing
  GitHub updater.
- `fdroid`: OkHttp, bundled Conscrypt on Android 8/9, no Play Services discovery,
  no Cronet adapter, no HTTP updater/download/installer implementation. The UI
  directs users to F-Droid for app updates.

The F-Droid flavor leaves release signing unset. The standard flavor alone can
use the `KORBUINO_*` signing environment variables. TLS certificate and hostname
verification remain enabled; both transports retain retailer challenge cookies.
Conscrypt is Apache-2.0 licensed and distributed through Maven Central.

## Build and verify

With JDK 17 and the Android SDK configured, from `android/`:

```sh
./gradlew --no-daemon --max-workers=2 -PfdroidOnly=true verifyFdroidDependencies testFdroidDebugUnitTest lintFdroidDebug assembleFdroidRelease
./gradlew --no-daemon testStandardDebugUnitTest lintStandardDebug assembleStandardRelease
```

Outputs are under `android/app/build/outputs/apk/{fdroid,standard}/release/`.
The F-Droid output is `app-fdroid-release-unsigned.apk`. The explicit
`fdroidOnly=true` property skips loading the proprietary dependency script and
disables standard variants. `assembleRelease` without a flavor builds both,
so release automation must use the explicit distribution task.

For packaging, the recipe removes the Flutter compatibility client and the
standard-only sources/dependency script **before** F-Droid scans the checkout.
These files are outside the F-Droid build. No broad `scanignore` exemption is
needed. CI builds the remaining checkout to catch accidental links back to the
removed files.

The tests cover cookie handoff, rejection of an untrusted HTTPS certificate,
trusted HTTPS, authenticated self-hosted server requests, and the existing
provider parsers. They do not establish that
all retailer websites are reachable or free from anti-bot challenges. Android
9's native Conscrypt path and the release UI were smoke-tested in a clean
emulator without Google Play Services. Physical-device coverage, especially
Android 8, remains a separate check.

## Submission files

`fdroid/de.korbunio.korbunio_app.yml` is the fdroiddata build recipe. Copy it to
`metadata/de.korbunio.korbunio_app.yml` in a fork of
<https://gitlab.com/fdroid/fdroiddata>. The build is pinned to the full source commit associated with
`fdroid-v0.1.59`, not the older `v0.1.59` tag, which lacks this flavor.
The first F-Droid build keeps version 0.1.59 / code 59; no existing release tag
is changed. Future F-Droid releases use `fdroid-v<version>` tags and increasing version codes.
Automatic updates track only these distribution tags. Pushing a F-Droid tag triggers the existing
`Build Android app` workflow to build, test, and sign its reference APK using
the existing GitHub signing secrets. A manual workflow dispatch for the tag
can retry a failed run. Publishing the reference
does not publish a standard release or mark it as the latest GitHub release.

Store descriptions, icons and actual app screenshots live in
`fastlane/metadata/android/{de-DE,en-US}/`. Release changelogs should be added
there when a new version is tagged. All project-owned store artwork and text
are covered by the root BSD-3-Clause LICENSE.

Run in the F-Droid build environment:

```sh
fdroid rewritemeta de.korbunio.korbunio_app
fdroid lint de.korbunio.korbunio_app
fdroid build de.korbunio.korbunio_app
```

Then open a merge request titled `New App: Korbuino` against `fdroiddata`.
The recipe builds from `android/app`, the application module, so F-Droid can
locate its APK output. Building from the aggregator `android` directory produces
an APK but F-Droid looks for it in the wrong output directory.

Submission requires a GitLab account; GitHub and Forgejo accounts alone cannot
create that merge request. F-Droid's maintainers decide acceptance and any
Anti-Features. The recipe discloses retailer services as `NonFreeNet`.

## Signing and existing installs

The recipe uses `Binaries` and `AllowedAPKSigningKeys` to require the existing
developer signature. The signed **F-Droid-flavor** APK is published as
`korbuino-fdroid-<version>.apk` on a `fdroid-v<version>` GitHub release. F-Droid
must reproduce it before publishing. The standard APK contains different code
and cannot serve as that reference. The signing workflow uses `apksigner` 34.0.0
for compatibility with signature copying and never exposes the key/passwords.

When reproducibility succeeds, the F-Droid APK can update existing
GitHub-installed copies with the same application ID and developer signature.
If a reproduction fails, fix the differences rather than silently switching to
an F-Droid signing key. Exporting a local backup before changing distributions
remains useful. No developer key or passwords belong in the recipe or source
repository.

Official references:

- <https://f-droid.org/docs/Submitting_to_F-Droid_Quick_Start_Guide/>
- <https://f-droid.org/docs/Build_Metadata_Reference/>
- <https://f-droid.org/docs/Reproducible_Builds/>
