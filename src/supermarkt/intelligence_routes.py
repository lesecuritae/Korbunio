from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from .access import require_api_auth
from . import runtime

router = APIRouter()


@router.get("/intelligence/providers", include_in_schema=False)
def intelligence_providers(_: None = Depends(require_api_auth)) -> list[dict[str, Any]]:
    return runtime.get_intelligence().providers()


@router.get("/intelligence/status", include_in_schema=False)
def intelligence_status(_: None = Depends(require_api_auth)) -> list[dict[str, Any]]:
    return runtime.get_intelligence().status()


@router.get("/intelligence/indicators", include_in_schema=False)
def intelligence_indicators(
    provider_id: str = Query(default="", max_length=120),
    limit: int = Query(default=1000, ge=1, le=10000),
    _: None = Depends(require_api_auth),
) -> list[dict[str, Any]]:
    return runtime.get_intelligence().store.indicators(provider_id=provider_id or None, limit=limit)


@router.get("/network/asn", include_in_schema=False)
def network_asn(
    asn: str = Query(default="", max_length=32),
    limit: int = Query(default=1000, ge=1, le=10000),
    _: None = Depends(require_api_auth),
) -> list[dict[str, Any]]:
    return runtime.get_intelligence().store.asn_records(asn=asn or None, limit=limit)


@router.get("/network/bgp", include_in_schema=False)
def network_bgp(
    prefix: str = Query(default="", max_length=64),
    limit: int = Query(default=1000, ge=1, le=10000),
    _: None = Depends(require_api_auth),
) -> list[dict[str, Any]]:
    return runtime.get_intelligence().store.bgp_events(prefix=prefix or None, limit=limit)


@router.get("/network/trust", include_in_schema=False)
def network_trust(_: None = Depends(require_api_auth)) -> list[dict[str, Any]]:
    return runtime.get_intelligence().trust.dashboard()
