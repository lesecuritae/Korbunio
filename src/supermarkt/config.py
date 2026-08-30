from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from .version import __version__

BERLIN = ZoneInfo("Europe/Berlin")


def _default_data_dir() -> Path:
    state_home = os.getenv("XDG_STATE_HOME")
    base = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    current = base / "korbklar"
    legacy = base / "supermarkt-preisvergleich"
    if current.exists() or not legacy.exists():
        return current
    return legacy


def _env_text(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _env_path(name: str, default: Path) -> Path:
    return Path(_env_text(name, str(default))).expanduser()


def _env_int(name: str, default: int, minimum: int, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None and raw.strip() else int(default)
    except (TypeError, ValueError):
        value = int(default)
    value = max(int(minimum), value)
    if maximum is not None:
        value = min(value, int(maximum))
    return value


DATA_DIR = _env_path("SUPERMARKT_DATA_DIR", _default_data_dir())
CACHE_DB = _env_path("SUPERMARKT_CACHE_DB", DATA_DIR / "supermarkt-cache.sqlite3")
SIGNING_SECRET_FILE = _env_path("SUPERMARKT_SIGNING_SECRET_FILE", DATA_DIR / ".signing-secret")
IMAGE_CACHE_DIR = _env_path("SUPERMARKT_IMAGE_CACHE_DIR", DATA_DIR / "supermarkt-images")
KAUFLAND_CACHE_DIR = _env_path("SUPERMARKT_KAUFLAND_CACHE_DIR", DATA_DIR / "kaufland")
REWE_CACHE_DIR = _env_path("SUPERMARKT_REWE_CACHE_DIR", DATA_DIR / "rewe")

KAUFLAND_STORE_CACHE_TTL_SECONDS = _env_int(
    "SUPERMARKT_KAUFLAND_STORE_CACHE_TTL_SECONDS", 86400, 300, 7 * 86400
)
REWE_STORE_CACHE_TTL_SECONDS = _env_int(
    "SUPERMARKT_REWE_STORE_CACHE_TTL_SECONDS", 86400, 300, 7 * 86400
)
IMAGE_CACHE_TTL_SECONDS = _env_int(
    "SUPERMARKT_IMAGE_CACHE_TTL_SECONDS", 604800, 3600, 30 * 86400
)
IMAGE_CACHE_MAX_BYTES = _env_int(
    "SUPERMARKT_IMAGE_CACHE_MAX_BYTES", 512 * 1024 * 1024, 16 * 1024 * 1024, 16 * 1024 * 1024 * 1024
)
IMAGE_MAX_FILE_BYTES = _env_int(
    "SUPERMARKT_IMAGE_MAX_FILE_BYTES", 4 * 1024 * 1024, 128 * 1024, 8 * 1024 * 1024
)
CACHE_TTL_MINUTES = _env_int("SUPERMARKT_CACHE_TTL_MINUTES", 30, 1, 1440)
CACHE_MAX_SNAPSHOTS = _env_int("SUPERMARKT_CACHE_MAX_SNAPSHOTS", 100, 4, 500)
RESULT_RETENTION_HOURS = _env_int("SUPERMARKT_RESULT_RETENTION_HOURS", 168, 1, 24 * 30)
TIMEOUT_SECONDS = _env_int("SUPERMARKT_TIMEOUT_SECONDS", 25, 5, 120)
MARKTGURU_PAGE_SIZE = _env_int("SUPERMARKT_MARKTGURU_PAGE_SIZE", 500, 100, 1000)
MAX_WORKERS = _env_int("SUPERMARKT_MAX_WORKERS", 8, 2, 24)

MARKTGURU_HOME = "https://www.marktguru.de/"
MARKTGURU_SEARCH_API = "https://api.marktguru.de/api/v1/offers/search"
USER_AGENT = _env_text("SUPERMARKT_USER_AGENT", f"korb-klar/{__version__}")
SEARCH_TERMS = (
    "Obst", "Gemüse", "Fleisch", "Wurst", "Käse", "Milch", "Joghurt", "Butter", "Brot",
    "Backwaren", "Getränke", "Wasser", "Limonade", "Saft", "Bier", "Wein", "Kaffee", "Tee",
    "Tiefkühl", "Pizza", "Eis", "Süßigkeiten", "Schokolade", "Nudeln", "Reis", "Konserven",
    "Frühstück", "Gewürze", "Haushalt", "Waschmittel", "Reiniger", "Drogerie", "Kosmetik",
    "Tiernahrung", "Baby", "Freizeit", "Elektronik", "Garten", "Küche", "Textil", "Werkzeug",
)
