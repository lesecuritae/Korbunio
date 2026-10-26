The `Published signed APK on AOSP` job downloads the actual APK and checksum
from the newly published GitHub release. It installs that file on a fresh
Google-free Android 28 emulator, checks the release version and starts it.
It then changes the postal code for eight German regions and verifies each
value survives an application-process restart. XML, screenshot, crash-log
and SHA-256 receipts are retained as workflow artifacts.

To repeat with an already booted disposable emulator and the Android SDK:

```sh
python3 android/ci/test-published-apk.py --apk korbuino-0.1.70.apk \
  --expected-version 0.1.70 --evidence-dir /tmp/korbunio-apk-evidence
```

The script requires exactly one emulator and does not target physical devices.
This checks the signed, minified release application's installation, startup
and regional-settings persistence. The application may start live retailer requests automatically; this smoke
test does not await or verify their completion. Provider regression tests and separately recorded live regional API
checks cover the market-search request; physical-device acceptance remains
separate.

After the regional settings checks, the script clears only the disposable
emulator's app data, selects EDEKA alone and lets the normal startup refresh
run. It records either a positive offer overview or the explicit action for
the retailer's browser confirmation. A confirmation-required result does not
prove that offers were loaded; that outcome is retained separately in the receipt.

The Android workflow also accepts the optional `release_smoke_tag` dispatch
input (for example `v0.1.70`). This tests the existing immutable public APK
without rebuilding or signing the application. It is useful when correcting
the test harness itself. The recorded APK SHA-256 must match the release asset.
