from __future__ import annotations

from fastapi import APIRouter

from .access import (
    build_image_proxy_url,
    build_result_path,
    build_result_url,
    image_proxy_signature,
    require_api_auth,
    result_token,
    verify_result_token,
)
from .api_models import SupermarketRequest
from .api_routes import router as api_router
from .browser_routes import router as browser_router
from .health_routes import router as health_router
from .media_routes import router as media_router, supermarket_image
from .runtime import get_engine, get_image_service as _image_service_instance

router = APIRouter(tags=["Supermarkt"])
router.include_router(browser_router)
router.include_router(api_router)
router.include_router(media_router)
router.include_router(health_router)
