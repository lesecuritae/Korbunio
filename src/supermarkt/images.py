"""Direkter Produktbild-Service für KorbKlar."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


@dataclass(frozen=True)
class ImageResult:
    data: bytes
    content_type: str
    origin: str


class ImageServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 404) -> None:
        super().__init__(message)
        self.status_code = status_code


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_image_url(value: Any, base_url: str = "") -> str:
    if isinstance(value, dict):
        for field in ("url", "src", "contentUrl", "content_url", "href"):
            candidate = normalize_image_url(value.get(field), base_url)
            if candidate:
                return candidate
        return ""
    if isinstance(value, list):
        for item in value:
            candidate = normalize_image_url(item, base_url)
            if candidate:
                return candidate
        return ""
    text = _clean(value)
    if not text:
        return ""
    if "," in text and re.search(r"\s(?:\d+w|\d+(?:\.\d+)?x)(?:,|$)", text):
        parts = [item.strip().split()[0] for item in text.split(",") if item.strip()]
        for part in reversed(parts):
            candidate = normalize_image_url(part, base_url)
            if candidate:
                return candidate
        return ""
    if text.startswith("//"):
        text = "https:" + text
    elif base_url and text.startswith(("/", "./", "../")):
        text = urljoin(base_url, text)
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return text[:5000]


def is_rejected_image_url(value: Any) -> bool:
    url = normalize_image_url(value)
    if not url:
        return True
    folded = url.casefold()
    bad_tokens = (
        "servedby.flashtalking.com", "doubleclick.net", "googleadservices.com",
        "tracking", "pixel", "spacer.gif", "transparent.gif", "/logo", "logo.",
        "placeholder", "no-image", "no_image", "icon.", "/icons/", ".svg",
        "loyalty", "bonus-badge", "header_", "category-header",
    )
    return any(token in folded for token in bad_tokens)


def _public_url(value: str) -> str:
    url = normalize_image_url(value)
    if not url or is_rejected_image_url(url):
        raise ImageServiceError("Bildquelle nicht erlaubt", 403)
    parsed = urlsplit(url)
    host = (parsed.hostname or "").strip().casefold()
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise ImageServiceError("Bildquelle nicht erlaubt", 403)
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ImageServiceError("Bildquelle konnte nicht aufgelöst werden", 502) from exc
    if not infos:
        raise ImageServiceError("Bildquelle konnte nicht aufgelöst werden", 502)
    for info in infos:
        raw = info[4][0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ImageServiceError("Bildquelle nicht erlaubt", 403)
    return url


class _SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        _public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _sniff_image(data: bytes, declared: str = "") -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[4:12] in {b"ftypavif", b"ftypavis"}:
        return "image/avif"
    content_type = _clean(declared).split(";", 1)[0].casefold()
    if content_type in {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif"}:
        return content_type
    return ""


class ImageService:
    """Begrenzter Cache für direkte Händlerbilder."""

    def __init__(
        self,
        *,
        cache_dir: str | Path = "./data/supermarkt-images",
        ttl_seconds: int = 604800,
        max_cache_bytes: int = 512 * 1024 * 1024,
        max_file_bytes: int = 2 * 1024 * 1024,
        timeout_seconds: int = 20,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = max(3600, min(int(ttl_seconds), 30 * 86400))
        self.max_cache_bytes = max(16 * 1024 * 1024, int(max_cache_bytes))
        self.max_file_bytes = max(128 * 1024, min(int(max_file_bytes), 8 * 1024 * 1024))
        self.timeout_seconds = max(5, min(int(timeout_seconds), 60))
        self._lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._cleanup_next = 0.0
        self._opener = build_opener(_SafeRedirects())
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cleanup(force=True)

    def cache_key(self, *, source_url: str, product: str, retailer: str) -> str:
        identity = "\n".join((_clean(retailer).casefold(), _clean(product).casefold(), _clean(source_url)))
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def get(self, *, source_url: str = "", referer: str = "", product: str, retailer: str) -> ImageResult:
        key = self.cache_key(source_url=source_url, product=product, retailer=retailer)
        cached = self._read(key)
        if cached is not None:
            return cached
        direct = normalize_image_url(source_url)
        if not direct or is_rejected_image_url(direct):
            raise ImageServiceError("Kein direktes Produktbild verfügbar", 404)
        self.cleanup()
        data, content_type = self._download(direct, referer=referer)
        result = ImageResult(data, content_type, "source")
        self._write(key, result, direct)
        return result

    def health(self) -> dict[str, Any]:
        self.cleanup()
        files = list(self.cache_dir.glob("*.bin"))
        size = 0
        for path in files:
            try:
                size += path.stat().st_size
            except OSError:
                pass
        return {
            "image_cache_files": len(files),
            "image_cache_bytes": size,
            "image_cache_ttl_seconds": self.ttl_seconds,
            "image_cache_max_bytes": self.max_cache_bytes,
            "image_mode": "direct-only",
        }

    def cleanup(self, force: bool = False) -> None:
        now = time.time()
        if not force and now < self._cleanup_next:
            return
        with self._cleanup_lock:
            now = time.time()
            if not force and now < self._cleanup_next:
                return
            entries: list[tuple[float, int, Path, Path]] = []
            total = 0
            for data_path in self.cache_dir.glob("*.bin"):
                try:
                    stat = data_path.stat()
                except OSError:
                    continue
                meta_path = data_path.with_suffix(".json")
                if now - stat.st_mtime > self.ttl_seconds:
                    data_path.unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                    continue
                total += stat.st_size
                entries.append((stat.st_mtime, stat.st_size, data_path, meta_path))
            if total > self.max_cache_bytes:
                for _mtime, size, data_path, meta_path in sorted(entries):
                    data_path.unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                    total -= size
                    if total <= self.max_cache_bytes:
                        break
            self._cleanup_next = now + 1800

    def _paths(self, key: str) -> tuple[Path, Path]:
        return self.cache_dir / f"{key}.bin", self.cache_dir / f"{key}.json"

    def _read(self, key: str) -> ImageResult | None:
        data_path, meta_path = self._paths(key)
        try:
            stat = data_path.stat()
            if time.time() - stat.st_mtime > self.ttl_seconds:
                data_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                return None
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            data = data_path.read_bytes()
            content_type = _clean(meta.get("content_type"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not data or not _sniff_image(data, content_type):
            return None
        return ImageResult(data, content_type, "cache")

    def _write(self, key: str, result: ImageResult, remote_url: str) -> None:
        data_path, meta_path = self._paths(key)
        tmp_suffix = f".{os.getpid()}.{threading.get_ident()}.tmp"
        tmp_data = data_path.with_name(data_path.name + tmp_suffix)
        tmp_meta = meta_path.with_name(meta_path.name + tmp_suffix)
        with self._lock:
            current = self._read(key)
            if current is not None:
                return
            tmp_data.write_bytes(result.data)
            tmp_meta.write_text(json.dumps({
                "content_type": result.content_type,
                "remote_url": remote_url,
                "fetched_at": time.time(),
            }, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp_data, data_path)
            os.replace(tmp_meta, meta_path)

    def _download(self, url: str, *, referer: str = "") -> tuple[bytes, str]:
        url = _public_url(url)
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/jpeg,image/png,image/gif,image/*;q=0.8,*/*;q=0.3",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        }
        ref = normalize_image_url(referer)
        if ref:
            headers["Referer"] = ref
        request = Request(url, headers=headers, method="GET")
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                _public_url(response.geturl())
                length = _clean(response.headers.get("Content-Length"))
                if length.isdigit() and int(length) > self.max_file_bytes:
                    raise ImageServiceError("Produktbild ist zu groß", 413)
                declared = response.headers.get("Content-Type", "")
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = response.read(min(128 * 1024, self.max_file_bytes + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > self.max_file_bytes:
                        raise ImageServiceError("Produktbild ist zu groß", 413)
        except ImageServiceError:
            raise
        except HTTPError as exc:
            raise ImageServiceError(f"Bildquelle antwortet mit HTTP {exc.code}", 502) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ImageServiceError(f"Bildquelle nicht erreichbar ({type(exc).__name__})", 502) from exc
        data = b"".join(chunks)
        content_type = _sniff_image(data, declared)
        if not content_type:
            raise ImageServiceError("Bildquelle lieferte kein unterstütztes Bild", 415)
        return data, content_type


class ImagePrefetcher:
    def __init__(self, service: ImageService, workers: int = 8, retry_seconds: int = 3600) -> None:
        self.service = service
        self.retry_seconds = max(60, int(retry_seconds))
        self._pool = ThreadPoolExecutor(max_workers=max(1, min(int(workers), 8)), thread_name_prefix="supermarkt-image")
        self._lock = threading.Lock()
        self._queued: dict[str, float] = {}

    def queue(self, *, source_url: str = "", referer: str = "", product: str, retailer: str) -> None:
        source_url = normalize_image_url(source_url)
        if not source_url or is_rejected_image_url(source_url):
            return
        key = self.service.cache_key(source_url=source_url, product=product, retailer=retailer)
        now = time.monotonic()
        with self._lock:
            previous = self._queued.get(key)
            if previous is not None and now - previous < self.retry_seconds:
                return
            self._queued[key] = now
        self._pool.submit(self._prefetch, source_url, referer, product, retailer)

    def _prefetch(self, source_url: str, referer: str, product: str, retailer: str) -> None:
        try:
            self.service.get(source_url=source_url, referer=referer, product=product, retailer=retailer)
        except ImageServiceError:
            pass
