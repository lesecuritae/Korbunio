from __future__ import annotations

import os

from .common import validate_postal_code
from .models import resolve_retailer_names


def home_defaults() -> tuple[str, tuple[str, ...]]:
    """Return validated, optional instance defaults for all clients."""
    postal_code = validate_postal_code(os.getenv("SUPERMARKT_DEFAULT_POSTAL_CODE", "")) or ""
    raw_retailers = os.getenv("SUPERMARKT_DEFAULT_RETAILERS", "")
    requested = [value.strip() for value in raw_retailers.replace(";", ",").split(",") if value.strip()]
    retailers, _unknown = resolve_retailer_names(requested)
    return postal_code, retailers
