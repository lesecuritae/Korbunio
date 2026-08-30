"""Locate a Chromium-compatible browser on the host."""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

# Every Chromium-based browser understands --headless=new --dump-dom, so Chrome and
# Edge stand in on hosts where no "chromium" package exists.
_PATH_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome-stable",
    "google-chrome",
    "chrome",
    "msedge",
)

_FILE_CANDIDATES = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


@lru_cache(maxsize=1)
def chromium_command() -> str:
    """Return the browser binary to invoke for headless page rendering.

    Falls back to the bare name so callers keep raising their existing
    OSError branch when no browser is installed at all.
    """
    # ponytail: resolved once per process, restart after installing a browser.
    override = os.getenv("SUPERMARKT_CHROMIUM", "").strip()
    if override:
        return override
    for name in _PATH_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    for candidate in _FILE_CANDIDATES:
        expanded = os.path.expandvars(candidate)
        if "%" not in expanded and Path(expanded).is_file():
            return expanded
    return "chromium"
