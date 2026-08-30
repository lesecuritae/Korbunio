from __future__ import annotations

import threading
from typing import Optional

from .config import (
    IMAGE_CACHE_DIR,
    IMAGE_CACHE_MAX_BYTES,
    IMAGE_CACHE_TTL_SECONDS,
    IMAGE_MAX_FILE_BYTES,
    TIMEOUT_SECONDS,
)
from .images import ImageService
from .service import SupermarketEngine
from .jobs import SearchJobStore

_engine: Optional[SupermarketEngine] = None
_engine_lock = threading.Lock()
_image_service: Optional[ImageService] = None
_image_service_lock = threading.Lock()
_jobs: Optional[SearchJobStore] = None
_jobs_lock = threading.Lock()


def get_engine() -> SupermarketEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = SupermarketEngine()
        return _engine


def get_image_service() -> ImageService:
    global _image_service
    with _image_service_lock:
        if _image_service is None:
            _image_service = ImageService(
                cache_dir=IMAGE_CACHE_DIR,
                ttl_seconds=IMAGE_CACHE_TTL_SECONDS,
                max_cache_bytes=IMAGE_CACHE_MAX_BYTES,
                max_file_bytes=IMAGE_MAX_FILE_BYTES,
                timeout_seconds=min(TIMEOUT_SECONDS, 30),
            )
        return _image_service


def get_jobs() -> SearchJobStore:
    global _jobs
    with _jobs_lock:
        if _jobs is None:
            _jobs = SearchJobStore(get_engine())
        return _jobs
