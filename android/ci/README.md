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
and regional-settings persistence. It does not fetch live retailer offers in
the UI. Provider regression tests and separately recorded live regional API
checks cover the market-search request; physical-device acceptance remains
separate.
