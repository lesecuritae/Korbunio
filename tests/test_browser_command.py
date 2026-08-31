from supermarkt.sources.browser import chromium_command


def _reset():
    chromium_command.cache_clear()


def test_environment_override_wins(monkeypatch):
    _reset()
    monkeypatch.setenv("SUPERMARKT_CHROMIUM", r"C:\custom\brave.exe")
    assert chromium_command() == r"C:\custom\brave.exe"
    _reset()


def test_blank_override_is_ignored_and_path_lookup_wins(monkeypatch):
    _reset()
    monkeypatch.setenv("SUPERMARKT_CHROMIUM", "   ")
    monkeypatch.setattr(
        "supermarkt.sources.browser.shutil.which",
        lambda name: "/usr/bin/msedge" if name == "msedge" else None,
    )
    assert chromium_command() == "/usr/bin/msedge"
    _reset()


def test_falls_back_to_installed_windows_path(monkeypatch, tmp_path):
    _reset()
    monkeypatch.delenv("SUPERMARKT_CHROMIUM", raising=False)
    monkeypatch.setattr("supermarkt.sources.browser.shutil.which", lambda name: None)
    installed = tmp_path / "chrome.exe"
    installed.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "supermarkt.sources.browser._FILE_CANDIDATES",
        (r"%NOPE%\missing.exe", str(installed)),
    )
    assert chromium_command() == str(installed)
    _reset()


def test_bare_name_when_nothing_is_installed(monkeypatch):
    _reset()
    monkeypatch.delenv("SUPERMARKT_CHROMIUM", raising=False)
    monkeypatch.setattr("supermarkt.sources.browser.shutil.which", lambda name: None)
    monkeypatch.setattr("supermarkt.sources.browser._FILE_CANDIDATES", ())
    assert chromium_command() == "chromium"
    _reset()
