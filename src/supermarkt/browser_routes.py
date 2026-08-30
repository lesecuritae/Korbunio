from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .access import build_result_path, verify_result_token
from .assets import FAVICON_SVG
from .common import clean_text, normalize_aldi_region, validate_postal_code
from .loyalty import normalize_program_ids
from .models import ToolError, resolve_retailer_names
from . import runtime
from .ui import build_home_html, build_results_html, build_shopping_html

router = APIRouter()


def _wants_refresh(value: str) -> bool:
    return clean_text(value).casefold() in {"1", "on", "true", "ja", "yes"}


@router.get("/favicon.svg", include_in_schema=False)
def favicon_svg() -> Response:
    return Response(content=FAVICON_SVG, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"})


@router.get("/favicon.ico", include_in_schema=False)
def favicon_ico() -> Response:
    return favicon_svg()


@router.get("/", include_in_schema=False, response_class=HTMLResponse)
def home(postal_code: str = Query(default="", max_length=5)) -> HTMLResponse:
    postal = validate_postal_code(clean_text(postal_code)) or ""
    return HTMLResponse(build_home_html(postal_code=postal), headers={"Cache-Control": "no-store"})


@router.get("/shopping", include_in_schema=False, response_class=HTMLResponse)
def shopping() -> HTMLResponse:
    return HTMLResponse(build_shopping_html(), headers={"Cache-Control": "no-store"})


@router.get("/rewe/markets", include_in_schema=False)
def browser_rewe_markets(postal_code: str = Query(default="", min_length=5, max_length=5, pattern=r"^\d{5}$")) -> dict:
    try:
        return {"postal_code": postal_code, "markets": runtime.get_engine().loader.official_rewe.markets(postal_code)}
    except ToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/netto/markets", include_in_schema=False)
def browser_netto_markets(postal_code: str = Query(default="", min_length=5, max_length=5, pattern=r"^\d{5}$")) -> dict:
    try:
        return {"postal_code": postal_code, "markets": runtime.get_engine().loader.netto_marken_markets.markets(postal_code)}
    except ToolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/search", include_in_schema=False)
def browser_search(postal_code_input: Annotated[str, Form(alias="postal_code")] = "", aldi_region_input: Annotated[str, Form(alias="aldi_region")] = "auto", offer_week_input: Annotated[str, Form(alias="offer_week")] = "current", refresh_input: Annotated[str, Form(alias="refresh")] = "", retailers_input: Annotated[list[str], Form(alias="retailers")] = [], rewe_market_id_input: Annotated[str, Form(alias="rewe_market_id")] = "", netto_market_id_input: Annotated[str, Form(alias="netto_market_id")] = "") -> Response:
    raw_postal_code = clean_text(postal_code_input)
    postal_code = validate_postal_code(raw_postal_code)
    if postal_code is None:
        return HTMLResponse(build_home_html(error="Bitte eine gültige fünfstellige deutsche Postleitzahl eingeben.", postal_code=raw_postal_code), status_code=400, headers={"Cache-Control": "no-store"})
    try:
        retailers, unknown = resolve_retailer_names(retailers_input)
        if unknown:
            raise ToolError("Unbekannte Händler: " + ", ".join(unknown))
        snapshot_kwargs = {"retailers": retailers, "rewe_market_id": clean_text(rewe_market_id_input), "netto_market_id": clean_text(netto_market_id_input)}
        if clean_text(offer_week_input).casefold() == "next":
            snapshot_kwargs["offer_week"] = "next"
        snapshot, _ = runtime.get_engine().snapshot(postal_code, normalize_aldi_region(aldi_region_input), _wants_refresh(refresh_input), **snapshot_kwargs)
    except ToolError as exc:
        return HTMLResponse(build_home_html(error=str(exc), postal_code=postal_code), status_code=502, headers={"Cache-Control": "no-store"})
    return RedirectResponse(build_result_path(snapshot["search_id"]), status_code=303)


@router.post("/search/jobs", include_in_schema=False)
def start_search_job(postal_code_input: Annotated[str, Form(alias="postal_code")] = "", aldi_region_input: Annotated[str, Form(alias="aldi_region")] = "auto", offer_week_input: Annotated[str, Form(alias="offer_week")] = "current", refresh_input: Annotated[str, Form(alias="refresh")] = "", retailers_input: Annotated[list[str], Form(alias="retailers")] = [], rewe_market_id_input: Annotated[str, Form(alias="rewe_market_id")] = "", netto_market_id_input: Annotated[str, Form(alias="netto_market_id")] = "") -> dict[str, str]:
    postal_code = validate_postal_code(clean_text(postal_code_input))
    if postal_code is None:
        raise HTTPException(status_code=400, detail="Bitte eine gültige fünfstellige deutsche Postleitzahl eingeben.")
    retailers, unknown = resolve_retailer_names(retailers_input)
    if unknown:
        raise HTTPException(status_code=400, detail="Unbekannte Händler: " + ", ".join(unknown))
    args = (postal_code, normalize_aldi_region(aldi_region_input), _wants_refresh(refresh_input), retailers, clean_text(rewe_market_id_input), clean_text(netto_market_id_input))
    return {"job_id": runtime.get_jobs().start(*args, offer_week="next") if clean_text(offer_week_input).casefold() == "next" else runtime.get_jobs().start(*args)}


@router.get("/search/jobs/{job_id}", include_in_schema=False)
def search_job(job_id: str) -> dict:
    job = runtime.get_jobs().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Suchauftrag nicht gefunden oder abgelaufen.")
    if job.get("search_id"):
        job["result_url"] = build_result_path(job["search_id"])
    return job


@router.get("/results/{search_id}", include_in_schema=False, response_class=HTMLResponse, name="supermarket_results")
def results_page(search_id: str, token: str = Query(default=""), loyalty: str = Query(default="", max_length=500)) -> HTMLResponse:
    verify_result_token(search_id, token)
    try:
        runtime.get_engine().by_id(search_id)
    except ToolError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    selected = normalize_program_ids(loyalty.split(","))
    return HTMLResponse(build_results_html(search_id, token, selected), headers={"Cache-Control": "no-store"})
