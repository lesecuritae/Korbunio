from __future__ import annotations

import html
import json
from functools import lru_cache
from pathlib import Path

from .loyalty import normalize_program_ids


STATIC_DIR = Path(__file__).with_name("static")


@lru_cache(maxsize=16)
def static_text(name: str) -> str:
    if not name or Path(name).name != name:
        raise ValueError("Ungültiger Static-Dateiname")
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def build_home_html(
    *,
    error: str = "",
    postal_code: str = "",
    default_postal_code: str = "",
    default_retailers: tuple[str, ...] = (),
) -> str:
    error_html = f'<div class="error" role="alert">{html.escape(error)}</div>' if error else ""
    return (
        static_text("home.html")
        .replace("__ERROR_HTML__", error_html)
        .replace("__POSTAL_CODE__", html.escape(postal_code, quote=True))
        .replace("__DEFAULT_POSTAL_CODE__", html.escape(default_postal_code, quote=True))
        .replace("__DEFAULT_RETAILERS__", html.escape(json.dumps(default_retailers, ensure_ascii=False), quote=True))
    )


def build_results_html(
    search_id: str,
    signature: str,
    selected_programs: tuple[str, ...] = (),
) -> str:
    selected = ",".join(normalize_program_ids(selected_programs))
    return (
        static_text("results.html")
        .replace("__SEARCH_ID__", html.escape(search_id, quote=True))
        .replace("__RESULT_TOKEN__", html.escape(signature, quote=True))
        .replace("__LOYALTY_PROGRAMS__", html.escape(selected, quote=True))
    )


def build_shopping_html() -> str:
    return static_text("shopping.html")
