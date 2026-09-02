from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .access import build_result_path, build_result_url, proxy_page_images, require_admin_auth, require_api_auth, require_app_result_auth, verify_result_token
from .api_models import AccessTokenRequest, SearchJobRequest, SupermarketRequest
from .jobs import SearchCapacityError
from .loyalty import normalize_program_ids
from .models import ToolError
from .security import create_client_token
from . import runtime
from .preferences import home_defaults

router = APIRouter()


@router.get("/api/v1/client", include_in_schema=False)
def client_connection(_: None = Depends(require_api_auth)) -> dict[str, Any]:
    postal_code, retailers = home_defaults()
    return {"status": "ok", "service": "korbklar", "default_postal_code": postal_code, "default_retailers": list(retailers)}


@router.post("/api/v1/access-tokens", include_in_schema=False)
def issue_access_token(request_data: AccessTokenRequest, _: None = Depends(require_admin_auth)) -> dict[str, str]:
    try:
        return {"token": create_client_token(request_data.label)}
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/v1/search/jobs", include_in_schema=False)
def start_api_search_job(request_data: SearchJobRequest, _: None = Depends(require_api_auth)) -> dict[str, str]:
    try:
        job_id = runtime.get_jobs().start(
            request_data.postal_code,
            "auto",
            request_data.refresh,
            tuple(request_data.retailers),
        )
    except SearchCapacityError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"job_id": job_id}


@router.get("/api/v1/search/jobs/{job_id}", include_in_schema=False)
def api_search_job(job_id: str, _: None = Depends(require_api_auth)) -> dict[str, Any]:
    job = runtime.get_jobs().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Suchauftrag nicht gefunden oder abgelaufen.")
    if job.get("search_id"):
        job["result_url"] = build_result_path(job["search_id"])
    return job


@router.post(
    "/api/v1/compare",
    operation_id="supermarkt_preisvergleich",
    summary="Supermarktangebote vergleichen",
    description="Lädt aktuelle regionale Supermarktangebote und gibt einen result_url zur interaktiven Liste zurück.",
)
def supermarket_compare(request_data: SupermarketRequest, request: Request, _: None = Depends(require_api_auth)) -> dict[str, Any]:
    try:
        engine = runtime.get_engine()
        snapshot_kwargs = {"retailers": tuple(request_data.retailers), "rewe_market_id": request_data.rewe_market_id, "netto_market_id": request_data.netto_market_id}
        if request_data.offer_week == "next":
            snapshot_kwargs["offer_week"] = "next"
        snapshot, from_cache = engine.snapshot(request_data.postal_code, request_data.aldi_region, request_data.refresh, **snapshot_kwargs)
        page = engine.page(snapshot, filter_text=request_data.filter_text, keywords=tuple(request_data.keywords), retailer=request_data.retailer, page=request_data.page, page_size=request_data.page_size, view=request_data.view, loyalty_programs=tuple(request_data.loyalty_programs), sort=request_data.sort, include_image_urls=False)
        page["status"] = "ok"
        page["from_cache"] = from_cache
        page["result_url"] = build_result_url(request, snapshot["search_id"], tuple(request_data.loyalty_programs))
        return page
    except ToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/v1/rewe/markets", summary="REWE-Märkte einer PLZ auflösen", include_in_schema=False)
def rewe_markets(postal_code: str = Query(min_length=5, max_length=5, pattern=r"^\d{5}$"), _: None = Depends(require_api_auth)) -> dict[str, Any]:
    try:
        markets = runtime.get_engine().loader.official_rewe.markets(postal_code)
        return {"postal_code": postal_code, "markets": markets}
    except ToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/v1/netto/markets", summary="Netto-Marken-Discount-Filialen einer PLZ auflösen", include_in_schema=False)
def netto_markets(postal_code: str = Query(min_length=5, max_length=5, pattern=r"^\d{5}$"), _: None = Depends(require_api_auth)) -> dict[str, Any]:
    try:
        markets = runtime.get_engine().loader.netto_marken_markets.markets(postal_code)
        return {"postal_code": postal_code, "markets": markets, "count": len(markets)}
    except ToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/v1/aldi/markets", summary="Belegte ALDI-Filialen einer PLZ auflösen", include_in_schema=False)
def aldi_markets(postal_code: str = Query(min_length=5, max_length=5, pattern=r"^\d{5}$"), _: None = Depends(require_api_auth)) -> dict[str, Any]:
    markets = runtime.get_engine().loader.aldi_region.markets(postal_code)
    return {"postal_code": postal_code, "markets": markets, "count": len(markets), "source": "OpenStreetMap/Nominatim"}


@router.get("/api/results/{search_id}", include_in_schema=False)
@router.get("/api/v1/results/{search_id}", include_in_schema=False)
def result_data(
    search_id: str,
    token: str = Query(default=""),
    q: str = Query(default="", max_length=120),
    keywords: list[str] = Query(default=[], max_length=50),
    retailer: str = Query(default="", max_length=60),
    retailers: list[str] = Query(default=[], max_length=20),
    category: str = Query(default="", max_length=120),
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=100, ge=1, le=100),
    view: Literal["best_only", "all"] = Query(default="best_only"),
    loyalty: str = Query(default="", max_length=500),
    sort: Literal["price", "unit_price", "retailer", "product"] = Query(default="price"),
    _: None = Depends(require_app_result_auth),
) -> dict[str, Any]:
    verify_result_token(search_id, token)
    try:
        engine = runtime.get_engine()
        snapshot = engine.by_id(search_id)
        return proxy_page_images(engine.page(snapshot, filter_text=q, keywords=tuple(keywords), retailer=retailer,
            retailer_filters=tuple(retailers), category=category, page=page, page_size=page_size, view=view,
            loyalty_programs=normalize_program_ids(loyalty.split(",")), sort=sort, include_image_urls=True))
    except ToolError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
