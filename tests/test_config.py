import os

from supermarkt import config


def test_env_int_falls_back_on_invalid_value(monkeypatch):
    monkeypatch.setenv("SUPERMARKT_TEST_INT", "kaputt")
    assert config._env_int("SUPERMARKT_TEST_INT", 25, 5, 120) == 25


def test_env_int_applies_bounds(monkeypatch):
    monkeypatch.setenv("SUPERMARKT_TEST_INT", "-10")
    assert config._env_int("SUPERMARKT_TEST_INT", 25, 5, 120) == 5
    monkeypatch.setenv("SUPERMARKT_TEST_INT", "999")
    assert config._env_int("SUPERMARKT_TEST_INT", 25, 5, 120) == 120


def test_env_text_uses_default_for_blank_value(monkeypatch):
    monkeypatch.setenv("SUPERMARKT_TEST_TEXT", "   ")
    assert config._env_text("SUPERMARKT_TEST_TEXT", "fallback") == "fallback"


def test_default_native_data_dir_prefers_korbklar_and_reuses_legacy(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    current = tmp_path / "korbklar"
    legacy = tmp_path / "supermarkt-preisvergleich"

    assert config._default_data_dir() == current

    legacy.mkdir()
    assert config._default_data_dir() == legacy

    current.mkdir()
    assert config._default_data_dir() == current
