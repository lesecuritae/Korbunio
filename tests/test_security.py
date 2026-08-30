import stat

from supermarkt import security


def test_signing_secret_is_generated_once_and_persisted(monkeypatch, tmp_path):
    secret_file = tmp_path / ".signing-secret"
    monkeypatch.delenv("SUPERMARKT_SIGNING_SECRET", raising=False)
    monkeypatch.setattr(security, "SIGNING_SECRET_FILE", secret_file)
    monkeypatch.setattr(security, "_CACHED_SECRET", None)

    first = security.signing_secret()
    assert len(first) >= 32
    assert secret_file.exists()
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600

    monkeypatch.setattr(security, "_CACHED_SECRET", None)
    second = security.signing_secret()
    assert second == first


def test_result_and_image_namespaces_do_not_share_signatures(monkeypatch):
    monkeypatch.setattr(security, "_CACHED_SECRET", b"test-signing-secret-0123456789-abcdef")
    value = "same-payload"
    assert security.signature(value, namespace="result") != security.signature(value, namespace="image")


def test_explicit_signing_secret_must_be_long_enough(monkeypatch):
    monkeypatch.setenv("SUPERMARKT_SIGNING_SECRET", "too-short")
    monkeypatch.setattr(security, "_CACHED_SECRET", None)

    try:
        security.signing_secret()
    except RuntimeError as exc:
        assert "mindestens 32 Zeichen" in str(exc)
    else:
        raise AssertionError("Kurzer Signierschlüssel wurde akzeptiert")
