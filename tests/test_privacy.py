from pathlib import Path

from pydantic import ValidationError
import pytest

from supermarkt.web import SupermarketRequest

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_has_no_default_postal_code_setting():
    config = (ROOT / "src/supermarkt/config.py").read_text(encoding="utf-8")
    assert "DEFAULT_POSTAL" not in config
    assert "POSTAL_CODE =" not in config


def test_request_requires_explicit_postal_code():
    with pytest.raises(ValidationError):
        SupermarketRequest()
