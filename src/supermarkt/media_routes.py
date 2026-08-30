from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from .access import image_proxy_signature
from .images import ImageServiceError
from . import runtime

router = APIRouter()


@router.get("/image", include_in_schema=False)
def supermarket_image(
    src: str = Query(default="", max_length=5000),
    ref: str = Query(default="", max_length=5000),
    q: str = Query(..., min_length=1, max_length=300),
    retailer: str = Query(default="", max_length=80),
    sig: str = Query(..., min_length=16, max_length=64),
) -> Response:
    if not hmac.compare_digest(sig, image_proxy_signature(src, ref, q, retailer)):
        raise HTTPException(status_code=403, detail="Ungültiger Bildschlüssel")
    try:
        result = runtime.get_image_service().get(source_url=src, referer=ref, product=q, retailer=retailer)
    except ImageServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(content=result.data, media_type=result.content_type, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff", "X-Supermarkt-Image-Origin": result.origin})
