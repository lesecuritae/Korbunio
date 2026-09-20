from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .access import build_result_path, build_result_url, proxy_page_images, require_admin_auth, require_api_auth, require_app_result_auth, verify_result_token
from .api_models import AccessTokenRequest, SearchJobRequest, ShoppingListItemRequest, ShoppingListWriteRequest, SupermarketRequest
from .jobs import SearchCapacityError
from .loyalty import normalize_program_ids
from .models import ToolError, resolve_retailer_names
from .security import create_client_token
from . import kitchenowl, runtime
from .preferences import home_defaults

router = APIRouter()


def _kitchenowl_settings(entity_id: str = "") -> kitchenowl.Settings:
    settings = kitchenowl.load()
    if settings is None:
        raise HTTPException(status_code=404, detail="KitchenOwl ist auf diesem Server nicht eingerichtet.")
    if entity_id and entity_id != settings.list_id:
        raise HTTPException(status_code=422, detail="Diese KitchenOwl-Liste ist auf dem Server nicht eingerichtet.")
    return settings


def _kitchenowl_item(item: ShoppingListItemRequest) -> tuple[str, str]:
    name = " ".join((item.name or item.product).split())[:120]
    if item.description.strip():
        return name, " ".join(item.description.split())[:500]
    parts = (
        f"bei {' '.join(item.retailer.split())[:80]}" if item.retailer.strip() else "",
        " ".join(item.price_text.split())[:80],
        " ".join(item.pack.split())[:120],
        " ".join(item.validity.split())[:120],
    )
    return name, " · ".join(part for part in parts if part)


def add_kitchenowl_items(request_data: ShoppingListWriteRequest) -> dict[str, list[str]]:
    settings = _kitchenowl_settings(request_data.entity_id)
    stored: list[str] = []
    try:
        for item in request_data.items:
            name, description = _kitchenowl_item(item)
            kitchenowl.add_item(settings, name, description)
            stored.append(name)
    except kitchenowl.KitchenOwlError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"added": stored}


@router.get("/api/v1/client", include_in_schema=False)
def client_connection(_: None = Depends(require_api_auth)) -> dict[str, Any]:
    postal_code, retailers = home_defaults()
    return {"status": "ok", "service": "korbunio", "default_postal_code": postal_code, "default_retailers": list(retailers)}


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
            netto_market_id=request_data.netto_market_id,
            netto_scottie_market_id=request_data.netto_scottie_market_id,
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
        page = engine.page(snapshot, filter_text=request_data.filter_text, keywords=tuple(request_data.keywords), retailer=request_data.retailer, page=request_data.page, page_size=request_data.page_size, view=request_data.view, loyalty_programs=tuple(request_data.loyalty_programs), sort=request_data.sort, include_image_urls=request_data.include_image_urls)
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


@router.get("/api/v1/trinkgut/markets", summary="trinkgut-Märkte einer PLZ auflösen", include_in_schema=False)
def trinkgut_markets(postal_code: str = Query(min_length=5, max_length=5, pattern=r"^\d{5}$"), _: None = Depends(require_api_auth)) -> dict[str, Any]:
    try:
        markets = runtime.get_engine().loader.official_trinkgut.markets(postal_code)
        return {"postal_code": postal_code, "markets": markets, "count": len(markets)}
    except ToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/v1/netto/markets", summary="Netto-Marken-Discount-Filialen einer PLZ auflösen", include_in_schema=False)
def netto_markets(postal_code: str = Query(min_length=5, max_length=5, pattern=r"^\d{5}$"), _: None = Depends(require_api_auth)) -> dict[str, Any]:
    try:
        markets = runtime.get_engine().loader.netto_marken_markets.markets(postal_code)
        return {"postal_code": postal_code, "markets": markets, "count": len(markets)}
    except ToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/v1/netto-scottie/markets", summary="Netto-schwarz-Filialen einer PLZ auflösen", include_in_schema=False)
def netto_scottie_markets(postal_code: str = Query(min_length=5, max_length=5, pattern=r"^\d{5}$"), _: None = Depends(require_api_auth)) -> dict[str, Any]:
    try:
        markets = runtime.get_engine().loader.netto_scottie_markets.markets(postal_code)
        return {"postal_code": postal_code, "markets": markets, "count": len(markets)}
    except ToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/v1/aldi/markets", summary="Belegte ALDI-Filialen einer PLZ auflösen", include_in_schema=False)
def aldi_markets(postal_code: str = Query(min_length=5, max_length=5, pattern=r"^\d{5}$"), _: None = Depends(require_api_auth)) -> dict[str, Any]:
    markets = runtime.get_engine().loader.aldi_region.markets(postal_code)
    return {"postal_code": postal_code, "markets": markets, "count": len(markets), "source": "OpenStreetMap/Nominatim"}


@router.get("/api/v1/markets", summary="Belegte Märkte der Korbuino-Händler auflösen", include_in_schema=False)
def retailer_markets(
    postal_code: str = Query(min_length=5, max_length=5, pattern=r"^\d{5}$"),
    retailers: list[str] = Query(default=[], max_length=20),
    _: None = Depends(require_api_auth),
) -> dict[str, Any]:
    canonical, _unknown = resolve_retailer_names(retailers)
    markets = runtime.get_engine().loader.aldi_region.retailer_markets(postal_code, canonical)
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
    sort: Literal["price", "unit_price", "retailer", "product", "category"] = Query(default="price"),
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


@router.get("/results/{search_id}/shopping-list/targets", include_in_schema=False)
def shopping_list_targets(search_id: str, token: str = Query(default="")) -> dict[str, Any]:
    verify_result_token(search_id, token)
    settings = kitchenowl.load()
    if settings is None:
        return {"configured": False, "targets": [], "default_entity": ""}
    return {
        "configured": True,
        "targets": [{"entity_id": settings.list_id, "label": settings.list_label or "KitchenOwl"}],
        "default_entity": settings.list_id,
    }


@router.get("/results/{search_id}/shopping-list/entries", include_in_schema=False)
def shopping_list_entries(search_id: str, token: str = Query(default=""), entity_id: str = Query(default="", max_length=12)) -> dict[str, Any]:
    verify_result_token(search_id, token)
    settings = _kitchenowl_settings(entity_id)
    try:
        return {"items": [item["name"] for item in kitchenowl.list_items(settings)]}
    except kitchenowl.KitchenOwlError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/results/{search_id}/shopping-list/items", include_in_schema=False)
def shopping_list_items(search_id: str, request_data: ShoppingListWriteRequest, token: str = Query(default="")) -> dict[str, list[str]]:
    verify_result_token(search_id, token)
    return add_kitchenowl_items(request_data)
