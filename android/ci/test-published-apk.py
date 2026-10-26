"""Install the actual signed release APK on a disposable, already booted AOSP emulator."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PACKAGE = "de.korbunio.korbunio_app"
REGIONS = [("Hamburg", "20095"), ("Berlin", "10115"), ("Cologne", "50667"),
           ("Munich", "80331"), ("Frankfurt", "60311"), ("Dresden", "01067"),
           ("Rastede", "26180"), ("Leipzig", "04109")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    assert args.apk.is_file()
    evidence = args.evidence_dir
    evidence.mkdir(parents=True, exist_ok=True)
    adb = str(Path(os.environ["ANDROID_HOME"]) / "platform-tools/adb")

    def command(*parts, binary=False):
        return subprocess.check_output(parts, timeout=45, text=not binary)

    devices = [line.split()[0] for line in command(adb, "devices").splitlines()
               if line.startswith("emulator-") and line.split()[-1] == "device"]
    assert len(devices) == 1, "Requires exactly one disposable emulator"
    serial = devices[0]

    def device(*parts, binary=False):
        return command(adb, "-s", serial, *parts, binary=binary)

    device("install", "-r", str(args.apk.resolve()))
    package_info = device("shell", "dumpsys", "package", PACKAGE)
    assert "versionName=" + args.expected_version in package_info
    assert "DEBUGGABLE" not in package_info, "Must test the release APK"
    component = device("shell", "cmd", "package", "resolve-activity", "--brief", PACKAGE).strip().splitlines()[-1]
    assert component.startswith(PACKAGE + "/"), component

    def launch():
        device("shell", "am", "start", "-W", "-n", component)

    def dump():
        device("shell", "uiautomator", "dump", "/sdcard/korbunio-release-smoke.xml")
        raw = device("exec-out", "cat", "/sdcard/korbunio-release-smoke.xml")
        root = ET.fromstring(raw)
        (evidence / "latest-window.xml").write_text(raw)
        assert not any(n.get("text") == "Korbuino ist abgestürzt" for n in root.iter("node"))
        return root, raw

    def wait_for_form(postal=None):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            root, raw = dump()
            fields = [n for n in root.iter("node") if n.get("class") == "android.widget.EditText"]
            texts = {n.get("text", "") for n in root.iter("node")}
            if fields and "Korbuino" in texts and (postal is None or fields[0].get("text") == postal):
                return fields[0], raw
            time.sleep(1)
        (evidence / "failure-screen.png").write_bytes(device("exec-out", "screencap", "-p", binary=True))
        (evidence / "failure-crash.log").write_text(device("logcat", "-d", "-b", "crash"))
        (evidence / "failure-activities.txt").write_text(device("shell", "dumpsys", "activity", "activities"))
        raise AssertionError(f"Release APK did not display postal code {postal!r}; fields={[n.get('text') for n in fields]}")

    launch()
    wait_for_form()
    receipts = []
    for region, postal in REGIONS:
        field, _ = wait_for_form()
        coordinates = list(map(int, re.findall(r"\d+", field.attrib["bounds"])))
        x1, y1, x2, y2 = coordinates
        device("shell", "input", "tap", str((x1+x2)//2), str((y1+y2)//2))
        device("shell", "input", "keyevent", "123")
        device("shell", "input", "keyevent", *("67" for _ in range(6)))
        device("shell", "input", "text", postal)
        # A focused Compose text field can keep UIAutomator's idle detector
        # busy with cursor/IME events. Check the persisted value after restart
        # rather than dumping that animated, focused field or pressing Back.
        time.sleep(1)
        device("shell", "am", "force-stop", PACKAGE)
        launch()
        _, raw = wait_for_form(postal)
        (evidence / (region.lower() + ".xml")).write_text(raw)
        receipts.append({"region": region, "postal_code": postal, "persisted_after_process_restart": True})
    crash_log = device("logcat", "-d", "-b", "crash")
    (evidence / "crash.log").write_text(crash_log)
    assert "FATAL EXCEPTION" not in crash_log
    (evidence / "release-screen.png").write_bytes(device("exec-out", "screencap", "-p", binary=True))
    result = {"apk_sha256": hashlib.sha256(args.apk.read_bytes()).hexdigest(), "package": PACKAGE,
              "version": args.expected_version, "release_apk": True,
              "android_api": device("shell", "getprop", "ro.build.version.sdk").strip(),
              "regional_ui_checks": receipts, "fatal_crashes": 0,
              "limits": ["Disposable AOSP emulator, not an affected physical phone",
                         "Install/startup and regional settings persistence; no live retailer fetching in this UI smoke test"]}
    (evidence / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
